"""
@file engine.py
@brief Patho-COT 统一推理引擎
       封装全部五级模型的加载与推理，提供 run_full_pipeline() 统一流水线接口，
       通过 progress_callback 向外推送每步的进度与结果。

       五级流水线：
       Step 0: WSI 质量检测 (PathProfilerQC2) → QCRreport
       Step 1: 器官分类 (ViT-B/16)          → organ / top5 probs
       Step 2: 细胞检测 (YOLOv8 + SAM)     → lesion count / ROI 图
       Step 3: 病变性质 (GCN)              → Normal / Abnormal
       Step 4: 亚型分类 (MobileNetV3)      → 组织亚型提示

       每个步骤返回统一结构：
       {
           "step_id": <int>,
           "step_name": <str>,
           "status": "running" | "done" | "error",
           "progress": <float 0~1>,
           "data": <dict of step-specific results>,
           "message": <str>
       }
"""
import os
import sys
import gc
import warnings

# 强制 CUDA 同步，让错误在正确的位置被捕获
os.environ["CUDA_LAUNCH_BLOCKING"] = "1"

# 抑制 PyTorch weights_only 警告
warnings.filterwarnings("ignore", message=".*weights_only=False.*")
warnings.filterwarnings("ignore", message=".*You are using `torch.load`.*")

import traceback
import time

# 加载系统配置（config.yaml 自动创建，路径无关，项目可整体拷贝运行）
if os.path.dirname(os.path.abspath(__file__)) not in sys.path:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import load_config
_CFG = load_config()

# ============================================================
# 模型根目录解析
# ------------------------------------------------------------
# 代码目录（patho_cot_web）可以与模型资产目录分离部署：权重体积大（数 GB），
# 常放在代码目录之外。解析优先级：
#   1) config.yaml -> paths.model_root（绝对路径）
#   2) 环境变量 PATHO_COT_MODEL_ROOT
#   3) 默认项目根（patho_cot_web 的上一级）
#   4) 自动发现：沿代码目录向上，在各层级的兄弟目录中寻找含
#      transformer_organ_classifier 标志文件夹的目录
# 找不到时回退默认项目根（加载器会给出明确的缺权重报错）。
_ENGINE_DIR = os.path.dirname(os.path.abspath(__file__))
_DEFAULT_BASE_DIR = os.path.dirname(_ENGINE_DIR)
_MODEL_MARKER_DIR = "transformer_organ_classifier"


def _resolve_model_root() -> str:
    candidates = []

    cfg_root = str(_CFG.get("paths", {}).get("model_root", "") or "").strip()
    if cfg_root:
        candidates.append(os.path.expandvars(os.path.expanduser(cfg_root)))

    env_root = os.environ.get("PATHO_COT_MODEL_ROOT", "").strip()
    if env_root:
        candidates.append(os.path.expandvars(os.path.expanduser(env_root)))

    candidates.append(_DEFAULT_BASE_DIR)

    # 自动发现：从项目根向上最多 4 层，扫描每层父目录下的兄弟文件夹
    probe = _DEFAULT_BASE_DIR
    for _ in range(4):
        parent = os.path.dirname(probe)
        if not parent or parent == probe:
            break
        try:
            for name in os.listdir(parent):
                sibling = os.path.join(parent, name)
                if os.path.isdir(sibling):
                    candidates.append(sibling)
        except OSError:
            pass
        probe = parent

    for cand in candidates:
        if cand and os.path.isdir(cand) and os.path.isdir(
            os.path.join(cand, _MODEL_MARKER_DIR)
        ):
            return os.path.abspath(cand)
    return _DEFAULT_BASE_DIR


_MODEL_ROOT = _resolve_model_root()

import cv2
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm

# 配置 matplotlib 中文字体
_cn_font_found = False
_cn_font_names = ['Microsoft YaHei', 'SimHei', 'WenQuanYi Micro Hei',
                  'Noto Sans CJK SC', 'Source Han Sans CN', 'sans-serif']
for _fn in _cn_font_names:
    try:
        _matches = [f for f in fm.findSystemFonts() if _fn.lower() in f.lower()]
        if _matches:
            plt.rcParams['font.sans-serif'] = [_fn] + plt.rcParams['font.sans-serif']
            plt.rcParams['axes.unicode_minus'] = False
            _cn_font_found = True
            break
    except Exception:
        continue
if not _cn_font_found:
    # 尝试查找任意系统中的 CJK 字体
    _all_fonts = [f.name for f in fm.fontManager.ttflist]
    _cjk_patterns = ['YaHei', 'SimHei', 'SimSun', 'KaiTi', 'FangSong',
                     'Noto Sans CJK', 'WenQuanYi', 'Source Han Sans']
    for _pat in _cjk_patterns:
        _found = [f for f in _all_fonts if _pat in f]
        if _found:
            plt.rcParams['font.sans-serif'] = [_found[0]] + plt.rcParams['font.sans-serif']
            plt.rcParams['axes.unicode_minus'] = False
            _cn_font_found = True
            break
import matplotlib.patches as patches
from PIL import Image
import json
import torch
import torch.nn as nn
import torch.nn.functional as F
from torchvision import models, transforms
from ultralytics import YOLO
from segment_anything import sam_model_registry, SamPredictor


def _imread_unicode(path):
    """Unicode 安全读图：cv2.imread 在部分 Windows 环境对含中文路径失败，
    改用 np.fromfile + cv2.imdecode 读取，兼容任意路径。"""
    try:
        data = np.fromfile(path, dtype=np.uint8)
        if data.size == 0:
            return None
        return cv2.imdecode(data, cv2.IMREAD_COLOR)
    except Exception:
        return cv2.imread(path)

# --- Patch for torchvision compatibility ---
if not hasattr(torch.library, 'register_fake'):
    torch.library.register_fake = lambda name: lambda func: func

# ============================================================
# 常量定义
# ============================================================

ORGANS = [
    "Adrenal-gland", "Bile-duct", "Bladder", "Breast", "Cervix",
    "Colon", "Esophagus", "Head-and-Neck", "Kidney", "Liver",
    "Lung", "Ovarian", "Pancreatic", "Prostate", "Skin",
    "Stomach", "Testis", "Thyroid", "Uterus"
]

NATURE_CLASSES = ["Normal", "Abnormal"]

# YOLO 细胞检测运行阈值。PanNuke patch 上部分细胞候选置信度偏低，
# 适当降低阈值以提升召回，并保持检测展示与 GCN 图推理输入口径一致。
# 以下参数均可通过 config.yaml 调整（自动生成，默认值见 config.py）。
YOLO_CELL_CONF_THRESHOLD = float(_CFG.get("detection", {}).get("conf_threshold", 0.15))
ENABLE_SAM_SEGMENTATION = bool(_CFG.get("detection", {}).get("enable_sam", False))
DETECTION_MIN_SIDE = int(_CFG.get("detection", {}).get("min_side", 512))
DETECTION_MAX_SIDE = int(_CFG.get("detection", {}).get("max_side", 1024))
QC_CFG = _CFG.get("qc", {})

# 动态导入病变性质模块（避免循环依赖和加载顺序问题）
_nature_dir = os.path.join(_MODEL_ROOT, "病变性质")
if _nature_dir not in sys.path:
    sys.path.insert(0, _nature_dir)

# 延迟导入，在 __init__ 之后才真正 import
_pathlogy_gcn_cls = None
_extract_features_fn = None
_build_adj_fn = None

def _lazy_import_nature():
    """懒加载病变性质模块"""
    global _pathlogy_gcn_cls, _extract_features_fn, _build_adj_fn
    if _pathlogy_gcn_cls is None:
        from model import PathlogyGCN as _cls
        from preprocess import extract_node_features as _ef, build_adjacency as _ba
        _pathlogy_gcn_cls = _cls
        _extract_features_fn = _ef
        _build_adj_fn = _ba

# 中文名称映射
ORGAN_CN = {
    "Adrenal-gland":  "肾上腺", "Bile-duct":      "胆管",
    "Bladder":        "膀胱",   "Breast":          "乳腺",
    "Cervix":         "宫颈",   "Colon":           "结肠",
    "Esophagus":      "食管",   "Head-and-Neck":   "头颈部",
    "Kidney":         "肾脏",   "Liver":           "肝脏",
    "Lung":           "肺",     "Ovarian":         "卵巢",
    "Pancreatic":     "胰腺",   "Prostate":        "前列腺",
    "Skin":           "皮肤",   "Stomach":         "胃",
    "Testis":         "睾丸",   "Thyroid":         "甲状腺",
    "Uterus":         "子宫",
}

NATURE_CN = {
    "Normal":   "正常",
    "Abnormal": "异常",
}

SUBTYPE_CN = {
    "ADI":  "脂肪组织",    "BACK": "背景",
    "DEB":  "碎片",        "LYM":  "淋巴细胞",
    "MUC":  "黏液",        "MUS":  "平滑肌",
    "NORM": "正常组织/黏膜", "STR":  "肿瘤相关间质",
    "TUM":  "肿瘤上皮",
}

SUBTYPE_FULL_NAMES = {
    "ADI":  "ADI (Adipose)",
    "BACK": "BACK (Background)",
    "DEB":  "DEB (Debris)",
    "LYM":  "LYM (Lymphocytes)",
    "MUC":  "MUC (Mucus)",
    "MUS":  "MUS (Smooth muscle)",
    "NORM": "NORM (Normal tissue)",
    "STR":  "STR (Cancer-associated stroma)",
    "TUM":  "TUM (Tumor epithelium)"
}

PIPELINE_STEPS = [
    {"id": 1, "name": "切片质量检测",    "icon": "shield-check"},
    {"id": 2, "name": "器官分类",        "icon": "chart-bar"},
    {"id": 3, "name": "细胞检测与分割",   "icon": "search-circle"},
    {"id": 4, "name": "病变性质判定",     "icon": "beaker"},
    {"id": 5, "name": "组织亚型分类",     "icon": "tag"},
]

# 所有模型权重 / 外部模块的根目录（见文件顶部的解析规则；支持代码与权重分离部署）
base_dir = _MODEL_ROOT


def _missing_weight(step_name: str, rel_path: str):
    """权重缺失时统一抛出明确异常，避免模型对象为 None 被调用时报
    "'NoneType' object is not callable" 这类无法定位根因的错误。"""
    full = os.path.join(base_dir, rel_path)
    raise FileNotFoundError(
        f"[{step_name}] 模型权重缺失: {full}\n"
        f"当前模型根目录(base_dir) = {base_dir}\n"
        "请将模型资产放到该目录下，或在 config.yaml 的 paths.model_root 中"
        "指定权重目录（也可用环境变量 PATHO_COT_MODEL_ROOT）。"
    )


def _safe_prob(prob_array, idx) -> float:
    """安全提取概率值，处理 NaN 和 Inf，保留 6 位小数避免四舍五入失真"""
    try:
        val = float(prob_array[idx])
        if np.isnan(val) or np.isinf(val):
            return 0.0
        return round(min(val, 0.99), 6)
    except (TypeError, ValueError, IndexError):
        return 0.0


def _cap_probability(value) -> float:
    """模型置信度统一上限为 0.99，避免展示和报告中出现 100%。"""
    try:
        val = float(value)
        if np.isnan(val) or np.isinf(val):
            return 0.0
        return round(min(max(val, 0.0), 0.99), 6)
    except (TypeError, ValueError):
        return 0.0


def _qc_with_details(result: dict) -> dict:
    """补充 QC 门控阈值、逐项通过情况和失败原因（阈值来自 config.yaml）。"""
    thresholds = {
        "usability_score": float(QC_CFG.get("usability_threshold", 0.6)),
        "focus_score": float(QC_CFG.get("focus_threshold", 4.0)),
        "stain_score": float(QC_CFG.get("stain_threshold", 4.0)),
        "tissue_ratio_min_hint": float(QC_CFG.get("tissue_ratio_min_hint", 0.01)),
    }
    usability = float(result.get("usability_score") or 0)
    focus = float(result.get("focus_score") or 0)
    stain = float(result.get("stain_score") or 0)
    tissue = float(result.get("tissue_ratio") or 0)

    flags = {
        "usability_pass": usability >= thresholds["usability_score"],
        "focus_pass": focus >= thresholds["focus_score"],
        "stain_pass": stain >= thresholds["stain_score"],
        "tissue_has_content": tissue >= thresholds["tissue_ratio_min_hint"],
    }
    fail_reasons = []
    if not flags["usability_pass"]:
        fail_reasons.append(
            f"综合质量分低于阈值({usability:.2f} < {thresholds['usability_score']:.2f})"
        )
    if not flags["focus_pass"]:
        fail_reasons.append(
            f"对焦质量不足({focus:.1f} < {thresholds['focus_score']:.1f})"
        )
    if not flags["stain_pass"]:
        fail_reasons.append(
            f"染色质量不足({stain:.1f} < {thresholds['stain_score']:.1f})"
        )
    if not flags["tissue_has_content"]:
        fail_reasons.append("组织占比过低，可能为空白或背景区域")
    for warning in result.get("warnings", []) or []:
        if warning and warning not in fail_reasons:
            fail_reasons.append(str(warning))

    result["qc_thresholds"] = thresholds
    result["qc_flags"] = flags
    result["fail_reasons"] = fail_reasons
    return result


def _make_error_payload(step_id: int, step_name: str, exc: Exception) -> dict:
    message = str(exc)
    recovery_hint = ""
    if _is_cuda_context_failure(exc):
        recovery_hint = "CUDA 上下文已损坏，请重启 Web 服务进程后重新分析；若仍频繁出现，请减少多 patch 数量或关闭 SAM 分割。"
        message = f"{message}；{recovery_hint}"
    return {
        "error_message": message,
        "error_type": type(exc).__name__,
        "failed_step_id": step_id,
        "failed_step_name": step_name,
        "recovery_hint": recovery_hint,
    }


def _is_cuda_context_failure(exc: Exception) -> bool:
    msg = str(exc).lower()
    return (
        "cuda error" in msg
        and (
            "unspecified launch failure" in msg
            or "device-side assert" in msg
            or "illegal memory access" in msg
        )
    )


# ============================================================
# 工具：构建步骤事件
# ============================================================

def _make_event(step_id: int, step_name: str, status: str,
                progress: float, data: dict = None, message: str = "") -> dict:
    """构建统一的流水线步骤事件"""
    return {
        "step_id": step_id,
        "step_name": step_name,
        "status": status,
        "progress": progress,
        "data": data or {},
        "message": message,
    }


# ============================================================
# ModelManager：统一模型管理与五级流水线
# ============================================================

class ModelManager:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(ModelManager, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        if hasattr(self, '_initialized') and self._initialized:
            return
        self.device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
        print(f"ModelManager initializing on {self.device} (Lazy Loading Mode)...")

        self.vit_model = None
        self.vit_transform = None
        self.phikon_model = None
        self.phikon_transform = None
        self.phikon_head = None
        self.nature_phikon_head = None
        self.anomaly_model = None
        self.anomaly_sched = None
        self.anomaly_resolution = 64
        self.anomaly_timesteps = [300]
        self.anomaly_tf = None
        self.yolo_model = None
        self.sam_predictor = None
        self.gcn_model = None
        self.subtype_model = None
        self.subtype_classes = []
        self.subtype_transform = transforms.Compose([
            transforms.ToTensor(),
            transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225])
        ])
        self._cuda_unhealthy = False
        self.keep_loaded = bool(_CFG.get("models", {}).get("keep_loaded", True))
        self.organ_backbone = _CFG.get("organ", {}).get("backbone", "vit")
        self.nature_backbone = _CFG.get("nature", {}).get("model", "gcn")
        self.anomaly_enabled = bool(_CFG.get("anomaly", {}).get("enabled", True))
        self.anomaly_timesteps = list(_CFG.get("anomaly", {}).get("timesteps", [300]))
        self._initialized = True

    # ============================================================
    # GPU 管理
    # ============================================================

    def _unload_ollama_model(self):
        """要求 Ollama 卸载模型以释放 GPU 显存给推理管道使用"""
        model_name = "qwen3.5:4b"
        try:
            import requests

            def _loaded_model_names():
                ps_resp = requests.get("http://localhost:11434/api/ps", timeout=3)
                if ps_resp.status_code != 200:
                    return []
                return [
                    item.get("name") or item.get("model") or ""
                    for item in ps_resp.json().get("models", [])
                ]

            loaded_names = _loaded_model_names()
            if not any(model_name in name for name in loaded_names):
                print("[GPU] Ollama 模型未驻留，跳过卸载请求")
                return

            requests.post(
                "http://localhost:11434/api/generate",
                json={"model": model_name, "prompt": "", "keep_alive": 0},
                timeout=10,
            )
            print("[GPU] 已通知 Ollama 卸载模型")

            for _ in range(20):
                try:
                    loaded_names = _loaded_model_names()
                    if not any(model_name in name for name in loaded_names):
                        print("[GPU] Ollama 模型已卸载，视觉模型可启动")
                        return
                    print(f"[GPU] 等待 Ollama 卸载中: {loaded_names}")
                except Exception as e:
                    print(f"[GPU] 查询 Ollama 运行模型失败: {e}")
                time.sleep(0.5)
            print("[GPU] Ollama 卸载等待超时，将继续尝试启动视觉模型")
        except Exception as e:
            print(f"[GPU] 通知 Ollama 卸载失败: {e}")

    def _reset_gpu(self):
        """彻底重置 GPU 状态，清空所有进程的残留显存"""
        if not torch.cuda.is_available():
            return
        if self._cuda_unhealthy:
            print("[GPU] CUDA 上下文已标记为异常，跳过 GPU 重置；请重启 Web 服务")
            return
        self._unload_ollama_model()
        gc.collect()
        time.sleep(0.5)
        try:
            torch.cuda.empty_cache()
        except RuntimeError as e:
            if _is_cuda_context_failure(e):
                self._cuda_unhealthy = True
                print(f"[GPU] CUDA 上下文异常，empty_cache 失败: {e}")
                return
            raise
        try:
            torch.cuda.reset_peak_memory_stats()
        except Exception:
            pass
        try:
            free, total = torch.cuda.mem_get_info()
            print(f"[GPU] 可用显存: {free/1024**3:.1f}GB / {total/1024**3:.1f}GB")
        except RuntimeError as e:
            if _is_cuda_context_failure(e):
                self._cuda_unhealthy = True
                print(f"[GPU] CUDA 上下文异常，无法读取显存: {e}")
                return
            raise

    # ============================================================
    # 懒加载方法（保持原有逻辑）
    # ============================================================

    def load_vit_model(self):
        if self.organ_backbone == "phikon":
            return self.load_phikon_organ_model()
        if self.vit_model is not None:
            return
        vit_path = os.path.join(base_dir, "transformer_organ_classifier", "best_vit_organ.pth")
        if os.path.exists(vit_path):
            # 本地权重为完整 state_dict（含 conv_proj 等全部 152 个 key），
            # 直接加载即可，无需联网下载 ImageNet 预训练权重；
            # 预处理变换按 ViT-B/16 ImageNet 标准手工构造（Resize 256 → CenterCrop 224）。
            self.vit_transform = transforms.Compose([
                transforms.Resize(256),
                transforms.CenterCrop(224),
                transforms.ToTensor(),
                transforms.Normalize(mean=[0.485, 0.456, 0.406],
                                    std=[0.229, 0.224, 0.225]),
            ])
            self.vit_model = models.vit_b_16(weights=None)
            in_features = self.vit_model.heads.head.in_features
            self.vit_model.heads.head = nn.Linear(in_features, len(ORGANS))
            self.vit_model.load_state_dict(torch.load(vit_path, map_location=self.device))
            self.vit_model = self.vit_model.to(self.device)
            self.vit_model.eval()
            print("Lazy Loaded ViT Organ Model.")
        else:
            _missing_weight("器官分类(ViT)",
                            os.path.join("transformer_organ_classifier", "best_vit_organ.pth"))

    def load_phikon_organ_model(self):
        """冻结 Phikon-v2 + 线性分类头（P0 升级：器官分类 +5.57pp，零训练）"""
        if self.phikon_model is not None:
            return
        phikon_dir = os.path.join(base_dir, "models", "phikon-v2")
        head_path = os.path.join(base_dir, "transformer_organ_classifier", "organ_phikon_head.pt")
        if not (os.path.exists(phikon_dir) and os.path.exists(head_path)):
            print("[Phikon] 未找到 phikon-v2 权重或分类头，回退到 ViT")
            self.organ_backbone = "vit"
            return self.load_vit_model()
        from transformers import AutoModel
        self.phikon_model = AutoModel.from_pretrained(phikon_dir)
        self.phikon_model.eval().to(self.device)
        self.phikon_transform = transforms.Compose([
            transforms.Resize(224, interpolation=transforms.InterpolationMode.BICUBIC),
            transforms.CenterCrop(224),
            transforms.ToTensor(),
            transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
        ])
        head = torch.load(head_path, map_location=self.device)
        self.phikon_head = {
            "mean": head["scaler_mean"].to(self.device),
            "scale": head["scaler_scale"].to(self.device),
            "weight": head["weight"].to(self.device),
            "bias": head["bias"].to(self.device),
        }
        print("Lazy Loaded Phikon-v2 Organ Model + linear head.")

    def load_yolo_model(self):
        if self.yolo_model is not None:
            return
        yolo_path = os.path.join(base_dir, "yolo训练", "yolo的调参权重",
                                  "yolov8m_p2_512-2", "weights", "best.pt")
        if os.path.exists(yolo_path):
            self.yolo_model = YOLO(yolo_path)
            print("Lazy Loaded YOLO Model.")
        else:
            _missing_weight("细胞检测(YOLO)",
                            os.path.join("yolo训练", "yolo的调参权重",
                                         "yolov8m_p2_512-2", "weights", "best.pt"))

    def load_sam_model(self):
        if self.sam_predictor is not None:
            return
        sam_path = os.path.join(base_dir, "yolo+sam切割", "sam_vit_h_4b8939.pth")
        if os.path.exists(sam_path):
            sam = sam_model_registry["vit_h"](checkpoint=sam_path)
            sam.to(device=self.device)
            self.sam_predictor = SamPredictor(sam)
            print("Lazy Loaded SAM Model.")
        else:
            _missing_weight("细胞分割(SAM)",
                            os.path.join("yolo+sam切割", "sam_vit_h_4b8939.pth"))

    def load_gcn_model(self):
        if self.gcn_model is not None:
            return
        gcn_path = os.path.join(base_dir, "病变性质", "gcn_nature_model.pth")
        if os.path.exists(gcn_path):
            _lazy_import_nature()
            self.gcn_model = _pathlogy_gcn_cls(
                node_features=14, hidden_dim=128, num_classes=2, dropout=0.3
            ).to(self.device)
            self.gcn_model.load_state_dict(torch.load(gcn_path, map_location=self.device))
            self.gcn_model.eval()
            print("Lazy Loaded GCN Nature Model v1.")
        else:
            _missing_weight("病变性质(GCN)",
                            os.path.join("病变性质", "gcn_nature_model.pth"))

    def load_nature_phikon_head(self):
        """病变性质线性头（P1 升级：图像特征判 Normal/Abnormal，+13.26pp）"""
        if self.nature_phikon_head is not None:
            return
        head_path = os.path.join(base_dir, "病变性质", "nature_phikon_head.pt")
        if not os.path.exists(head_path):
            print("[Phikon] 未找到病变性质头，回退到 GCN")
            self.nature_backbone = "gcn"
            return self.load_gcn_model()
        self.nature_phikon_head = torch.load(head_path, map_location=self.device)
        print("Lazy Loaded Phikon Nature Head.")

    def load_anomaly_model(self):
        """P2 扩散异常检测：加载 AnoDDPM（64px，2.6M 参数，实验性参考）"""
        if not self.anomaly_enabled or self.anomaly_model is not None:
            return
        ckpt_path = os.path.join(base_dir, "research", "anoddpm_64.pt")
        if not os.path.exists(ckpt_path):
            print("[Anomaly] 未找到 AnoDDPM 权重，自动禁用异常检测")
            self.anomaly_enabled = False
            return
        from diffusers import DDPMScheduler, UNet2DModel
        ck = torch.load(ckpt_path, map_location=self.device)
        a = ck.get("args", {}) or {}
        res = int(a.get("resolution", 64))
        chans = tuple(int(c) for c in str(a.get("channels", "32,64,128")).split(","))
        if len(chans) == 3:
            dt = ("DownBlock2D", "AttnDownBlock2D", "DownBlock2D")
            ut = ("UpBlock2D", "AttnUpBlock2D", "UpBlock2D")
        else:
            dt = ("DownBlock2D", "AttnDownBlock2D")
            ut = ("UpBlock2D", "AttnUpBlock2D")
        model = UNet2DModel(
            sample_size=res, in_channels=3, out_channels=3,
            layers_per_block=int(a.get("layers_per_block", 1)),
            block_out_channels=chans, down_block_types=dt, up_block_types=ut,
        ).to(self.device)
        model.load_state_dict(ck["model"])
        model.eval()
        self.anomaly_model = model
        self.anomaly_sched = DDPMScheduler(num_train_timesteps=1000,
                                           beta_schedule="squaredcos_cap_v2")
        self.anomaly_resolution = res
        self.anomaly_tf = transforms.Compose([
            transforms.Resize(res, interpolation=transforms.InterpolationMode.BICUBIC),
            transforms.CenterCrop(res),
            transforms.ToTensor(),
            transforms.Normalize([0.5, 0.5, 0.5], [0.5, 0.5, 0.5]),
        ])
        print(f"[Anomaly] Lazy Loaded AnoDDPM (res={res}, t={self.anomaly_timesteps})")

    def load_nature_model(self):
        """Step 4 加载：按 config 的 nature.model 切换 GCN / Phikon + 附带 AnoDDPM"""
        if self.nature_backbone == "phikon":
            self.load_phikon_organ_model()   # 复用 Phikon 编码器
            self.load_nature_phikon_head()
        else:
            self.load_yolo_model()
            self.load_gcn_model()
        self.load_anomaly_model()

    def load_subtype_model(self):
        if self.subtype_model is not None:
            return
        subtype_path = os.path.join(base_dir, "亚型分类", "subtype_mobilenet_v3.pth")
        subtype_classes_path = os.path.join(base_dir, "亚型分类", "subtype_classes.txt")
        if os.path.exists(subtype_path) and os.path.exists(subtype_classes_path):
            with open(subtype_classes_path, "r") as f:
                self.subtype_classes = [line.strip() for line in f.readlines()]
            if len(self.subtype_classes) > 0:
                self.subtype_model = models.mobilenet_v3_large(weights=None)
                in_features = self.subtype_model.classifier[3].in_features
                self.subtype_model.classifier[3] = nn.Linear(in_features, len(self.subtype_classes))
                self.subtype_model.load_state_dict(torch.load(subtype_path, map_location=self.device))
                self.subtype_model = self.subtype_model.to(self.device)
                self.subtype_model.eval()
                print("Lazy Loaded MobileNetV3 Subtype Model.")
        if self.subtype_model is None:
            _missing_weight("亚型分类(MobileNetV3)",
                            os.path.join("亚型分类", "subtype_mobilenet_v3.pth"))

    # ============================================================
    # 模型释放方法（节约 GPU 显存）
    # ============================================================

    def _free_gpu(self):
        """安全释放 GPU 缓存，不要调用 ipc_collect"""
        if not torch.cuda.is_available():
            return
        try:
            torch.cuda.empty_cache()
        except Exception:
            pass

    def release_vit_model(self):
        if self.vit_model is not None:
            self.vit_model = None
            gc.collect()
            self._free_gpu()
            print("Released ViT Organ Model from GPU.")

    def release_sam_model(self):
        if self.sam_predictor is not None:
            self.sam_predictor = None
            gc.collect()
            self._free_gpu()
            print("Released SAM Model from GPU.")

    def release_yolo_model(self):
        if self.yolo_model is not None:
            self.yolo_model = None
            gc.collect()
            self._free_gpu()
            print("Released YOLO Model from GPU.")

    def release_gcn_model(self):
        if self.gcn_model is not None:
            self.gcn_model = None
            gc.collect()
            self._free_gpu()
            print("Released GCN Model from GPU.")

    def release_subtype_model(self):
        if self.subtype_model is not None:
            self.subtype_model = None
            gc.collect()
            self._free_gpu()
            print("Released Subtype Model from GPU.")

    def release_all_models(self):
        """释放所有模型以释放 GPU 显存"""
        self.vit_model = None
        self.sam_predictor = None
        self.yolo_model = None
        self.gcn_model = None
        self.subtype_model = None
        gc.collect()
        self._free_gpu()
        print("All models released from GPU.")

    # ============================================================
    # 统一流水线入口
    # ============================================================

    def warm_up(self):
        """
        预热全部视觉模型（常驻模式）。首次调用后，分步向导的每一步秒开。
        单个模型加载失败不影响其余模型，只记录日志。
        """
        self._reset_gpu()
        results = []
        for name, loader in [
            ("ViT", self.load_vit_model),
            ("YOLO", self.load_yolo_model),
            ("GCN", self.load_gcn_model),
            ("MobileNetV3", self.load_subtype_model),
        ]:
            try:
                loader()
                results.append(f"{name}:ok")
            except Exception as e:
                results.append(f"{name}:fail({e})")
        print("[WarmUp] " + ", ".join(results))
        self._free_gpu()
        return results

    def _release_models_after_step(self):
        """分步向导每步结束后的释放策略：常驻模式下只清缓存、不卸载模型。"""
        if self.keep_loaded:
            self._free_gpu()
        else:
            self._hard_release()

    def run_step(self, step_id: int, image_path: str, results_dir: str):
        """
        分步向导模式：独立执行单步分析。

        step_id: 1=质量检测 2=器官分类 3=细胞检测与分割 4=病变性质判定 5=组织亚型分类
        每步独立 加载模型 → 推理 → 彻底释放，与整体流水线行为一致，
        因此某一步失败可单独重试，无需重跑其他步骤。

        @return: event dict（status: done / error）
        """
        step_id = int(step_id)
        if step_id < 1 or step_id > 5:
            raise ValueError(f"无效步骤: {step_id}")

        name = PIPELINE_STEPS[step_id - 1]["name"]

        if self._cuda_unhealthy:
            exc = RuntimeError("CUDA 上下文已损坏，需要重启 Web 服务进程后再运行 GPU 模型")
            return _make_event(step_id, name, "error", 1.0,
                               data=_make_error_payload(step_id, name, exc),
                               message=f"{name}失败: {str(exc)}")

        self._reset_gpu()

        # Step 1: 纯 CPU 质量检测
        if step_id == 1:
            try:
                qc_result = self._run_qc(image_path, results_dir)
                return _make_event(1, name, "done", 0.2, qc_result)
            except Exception as e:
                print(f"[Pipeline] 质量检测失败: {e}")
                traceback.print_exc()
                return _make_event(1, name, "error", 0.2,
                                   data=_make_error_payload(1, name, e),
                                   message=f"质量检测失败: {str(e)}")

        # Step 2~5: GPU 模型（懒加载 → 推理 → 释放）
        loaders = {
            2: self.load_vit_model,
            3: self.load_yolo_model,
            4: lambda: self.load_nature_model(),
            5: self.load_subtype_model,
        }
        runners = {
            2: self._run_organ,
            3: self._run_detection,
            4: self._run_nature,
            5: self._run_subtype,
        }
        try:
            loaders[step_id]()
            result = runners[step_id](image_path, results_dir)
            return _make_event(step_id, name, "done", step_id / 5, result)
        except Exception as e:
            print(f"[Pipeline] {name}失败: {e}")
            traceback.print_exc()
            if _is_cuda_context_failure(e):
                self._cuda_unhealthy = True
            return _make_event(step_id, name, "error", step_id / 5,
                               data=_make_error_payload(step_id, name, e),
                               message=f"{name}失败: {str(e)}")
        finally:
            self._release_models_after_step()

    def run_full_pipeline(self, image_path: str, results_dir: str,
                          progress_callback=None):
        """
        五级流水线统一执行

        每步独立加载 → 推理 → 完全释放，GPU 上始终只有一个模型在运行

        @param image_path: 用户上传的图片路径
        @param results_dir: 结果图片输出目录
        @param progress_callback: 可选，进度/结果回调函数
        @return: 所有步骤的 event_dict 列表
        """
        events = []

        def _push(event):
            events.append(event)
            if progress_callback:
                try:
                    progress_callback(event)
                except Exception:
                    pass

        def _do_step(step_id, step_name, load_fn, run_fn):
            """加载 → 推理 → 彻底释放"""
            if self._cuda_unhealthy:
                exc = RuntimeError("CUDA 上下文已损坏，需要重启 Web 服务进程后再运行 GPU 模型")
                _push(_make_event(step_id, step_name, "error",
                                  step_id / 5,
                                  data=_make_error_payload(step_id, step_name, exc),
                                  message=f"{step_name}失败: {str(exc)}"))
                return False
            self._notify_running(_push, step_id, 5)
            try:
                load_fn()
                result = run_fn(image_path, results_dir)
                _push(_make_event(step_id, step_name, "done",
                                  step_id / 5, result))
                return True
            except Exception as e:
                print(f"[Pipeline] {step_name}失败: {e}")
                traceback.print_exc()
                if _is_cuda_context_failure(e):
                    self._cuda_unhealthy = True
                _push(_make_event(step_id, step_name, "error",
                                  step_id / 5,
                                  data=_make_error_payload(step_id, step_name, e),
                                  message=f"{step_name}失败: {str(e)}"))
                return False
            finally:
                self._hard_release()

        # ---- Step 1: WSI 质量检测（纯 CPU，无需 GPU）----
        # 提前卸载 Ollama 模型以释放 GPU 显存
        self._reset_gpu()
        self._notify_running(_push, 1, 5)
        qc_pass = True
        try:
            qc_result = self._run_qc(image_path, results_dir)
            _push(_make_event(1, PIPELINE_STEPS[0]["name"], "done", 1/5, qc_result))
            qc_pass = qc_result.get("is_usable", True)
        except Exception as e:
            print(f"[Pipeline] 质量检测失败: {e}")
            traceback.print_exc()
            qc_pass = False
            _push(_make_event(1, PIPELINE_STEPS[0]["name"], "error", 1/5,
                              data=_make_error_payload(1, PIPELINE_STEPS[0]["name"], e),
                              message=f"质量检测失败: {str(e)}"))

        if not qc_pass:
            # 质量不通过，跳过后续 GPU 步骤，直接进入报告阶段
            print("[Pipeline] Step 1 质量检测 REJECT，跳过 Step 2~5")
            for sid in range(2, 6):
                _push(_make_event(sid, PIPELINE_STEPS[sid - 1]["name"], "skipped",
                                  sid / 5,
                                  message="图像质量不合格，已跳过此检测"))
        else:
            # ---- Step 2: 器官分类（ViT 独立加载 → 释放）----
            gpu_ok = _do_step(2, PIPELINE_STEPS[1]["name"],
                              self.load_vit_model, self._run_organ)

            # ---- Step 3: 细胞检测（默认仅 YOLO，SAM 代码保留但默认关闭）----
            if gpu_ok:
                gpu_ok = _do_step(3, PIPELINE_STEPS[2]["name"],
                                  lambda: (
                                      self.load_yolo_model(),
                                      self.load_sam_model() if ENABLE_SAM_SEGMENTATION else None,
                                  ),
                                  self._run_detection)
            else:
                _push(_make_event(3, PIPELINE_STEPS[2]["name"], "skipped", 3 / 5,
                                  message="前置 GPU 步骤失败，已跳过此检测"))

            # ---- Step 4: 病变性质判定（YOLO + GCN 独立加载 → 释放）----
            if gpu_ok:
                gpu_ok = _do_step(4, PIPELINE_STEPS[3]["name"],
                                  lambda: self.load_nature_model(),
                                  self._run_nature)
            else:
                _push(_make_event(4, PIPELINE_STEPS[3]["name"], "skipped", 4 / 5,
                                  message="前置 GPU 步骤失败，已跳过此检测"))

            # ---- Step 5: 亚型分类（MobileNetV3 独立加载 → 释放）----
            if gpu_ok:
                _do_step(5, PIPELINE_STEPS[4]["name"],
                         self.load_subtype_model, self._run_subtype)
            else:
                _push(_make_event(5, PIPELINE_STEPS[4]["name"], "skipped", 5 / 5,
                                  message="前置 GPU 步骤失败，已跳过此检测"))

        # 最终清理
        self.release_all_models()
        print(f"[Pipeline] 五步流水线完成，共 {len(events)} 个事件")
        return events

    def run_multi_patch_pipeline(self, patch_paths: list, results_dir: str,
                                 patch_names: list = None,
                                 patch_urls: list = None,
                                 progress_callback=None):
        """
        多 patch 流水线统一执行。

        该入口用于模拟 WSI 初步切割后的批量 patch 分析：每个 patch 复用现有
        五级流水线，质量不合格的 patch 自动跳过后续模型，最后汇总所有合格
        patch 的模型结果，形成跨 patch 的综合分析依据。
        """
        patch_names = patch_names or [
            os.path.basename(p) for p in patch_paths
        ]
        patch_urls = patch_urls or [""] * len(patch_paths)
        total = len(patch_paths)
        all_events = []
        patch_results = []

        def _push(event):
            all_events.append(event)
            if progress_callback:
                try:
                    progress_callback(event)
                except Exception:
                    pass

        _push(_make_event(
            0, "多 patch 初始化", "started", 0.0,
            data={
                "total_patches": total,
                "patches": [
                    {
                        "patch_index": idx + 1,
                        "patch_name": patch_names[idx],
                        "patch_url": patch_urls[idx],
                    }
                    for idx in range(total)
                ],
            },
            message=f"已接收 {total} 个 patch，准备逐块分析",
        ))

        for idx, patch_path in enumerate(patch_paths):
            patch_index = idx + 1
            patch_name = patch_names[idx]
            patch_url = patch_urls[idx] if idx < len(patch_urls) else ""
            start_progress = (idx / max(total, 1)) * 0.95

            _push(_make_event(
                0, "patch 分析开始", "running", start_progress,
                data={
                    "event_type": "patch_started",
                    "patch_index": patch_index,
                    "patch_total": total,
                    "patch_name": patch_name,
                    "patch_url": patch_url,
                },
                message=f"正在分析 Patch {patch_index}/{total}",
            ))

            patch_events = []

            def _patch_callback(event):
                wrapped = dict(event)
                wrapped_data = dict(wrapped.get("data") or {})
                wrapped_data.update({
                    "event_type": "patch_step",
                    "patch_index": patch_index,
                    "patch_total": total,
                    "patch_name": patch_name,
                    "patch_url": patch_url,
                    "patch_progress": event.get("progress", 0),
                })
                wrapped["data"] = wrapped_data
                wrapped["event_type"] = "patch_step"
                wrapped["patch_index"] = patch_index
                wrapped["patch_total"] = total
                wrapped["patch_name"] = patch_name
                wrapped["progress"] = min(
                    0.95,
                    ((idx + float(event.get("progress", 0))) / max(total, 1)) * 0.95,
                )
                if wrapped.get("message"):
                    wrapped["message"] = (
                        f"Patch {patch_index}/{total} · {wrapped['message']}"
                    )
                patch_events.append(wrapped)
                _push(wrapped)

            raw_events = self.run_full_pipeline(
                patch_path, results_dir, _patch_callback
            )
            patch_result = self._build_patch_result(
                patch_index, patch_name, patch_url, raw_events or patch_events
            )
            patch_results.append(patch_result)

            _push(_make_event(
                0, "patch 分析完成", "done",
                min(0.95, (patch_index / max(total, 1)) * 0.95),
                data={
                    "event_type": "patch_done",
                    "patch_index": patch_index,
                    "patch_total": total,
                    "patch_name": patch_name,
                    "patch_url": patch_url,
                    "patch_result": patch_result,
                },
                message=f"patch {patch_index}/{total} 分析完成",
            ))

        summary = self._summarize_multi_patch(patch_results)
        _push(_make_event(
            6, "多 patch 综合汇总", "done", 1.0,
            data={
                "event_type": "multi_summary",
                "summary": summary,
                "patch_results": patch_results,
            },
            message="多 patch 综合分析完成",
        ))
        return all_events

    @staticmethod
    def _extract_step_data(events: list, step_id: int) -> dict:
        for event in reversed(events):
            if event.get("step_id") == step_id and event.get("status") == "done":
                return event.get("data") or {}
        return {}

    def _build_patch_result(self, patch_index: int, patch_name: str,
                            patch_url: str, events: list) -> dict:
        qc = self._extract_step_data(events, 1)
        organ = self._extract_step_data(events, 2)
        detection = self._extract_step_data(events, 3)
        nature = self._extract_step_data(events, 4)
        subtype = self._extract_step_data(events, 5)
        errors = [
            {
                "step_id": e.get("step_id"),
                "step_name": e.get("step_name"),
                "message": e.get("message", ""),
                "error_message": (e.get("data") or {}).get("error_message", ""),
                "error_type": (e.get("data") or {}).get("error_type", ""),
            }
            for e in events
            if e.get("status") == "error"
        ]
        is_usable = bool(qc.get("is_usable", True)) if qc else False
        is_abnormal = nature.get("top_nature") == "Abnormal"

        return {
            "patch_index": patch_index,
            "patch_name": patch_name,
            "patch_url": patch_url,
            "is_usable": is_usable,
            "qc": qc,
            "organ": organ,
            "detection": detection,
            "nature": nature,
            "subtype": subtype,
            "abnormal_prob": self._prob_from_nature(nature, "Abnormal"),
            "normal_prob": self._prob_from_nature(nature, "Normal"),
            "is_abnormal": is_abnormal,
            "has_error": len(errors) > 0,
            "errors": errors,
        }

    @staticmethod
    def _prob_from_nature(nature: dict, name: str) -> float:
        for item in nature.get("probs", []) or []:
            if item.get("name") == name:
                return _cap_probability(item.get("prob") or 0)
        if nature.get("top_nature") == name:
            return _cap_probability(nature.get("top_prob") or 0)
        return 0.0

    @staticmethod
    def _weighted_distribution(patch_results: list, key: str, name_key: str) -> dict:
        dist = {}
        for item in patch_results:
            data = item.get(key) or {}
            name = data.get(name_key)
            if not name:
                continue
            dist[name] = dist.get(name, 0) + 1
        return dict(sorted(dist.items(), key=lambda kv: kv[1], reverse=True))

    def _summarize_multi_patch(self, patch_results: list) -> dict:
        total = len(patch_results)
        usable = [p for p in patch_results if p.get("is_usable")]
        rejected = total - len(usable)
        abnormal = [p for p in usable if p.get("nature", {}).get("top_nature") == "Abnormal"]

        total_lesion = sum(
            int((p.get("detection") or {}).get("lesion_count") or 0)
            for p in usable
        )
        total_non_lesion = sum(
            int((p.get("detection") or {}).get("non_lesion_count") or 0)
            for p in usable
        )
        abnormal_probs = [float(p.get("abnormal_prob") or 0) for p in usable]
        mean_abnormal_prob = (
            sum(abnormal_probs) / len(abnormal_probs)
            if abnormal_probs else 0.0
        )

        organ_distribution = self._weighted_distribution(
            usable, "organ", "top_organ_cn"
        )
        subtype_distribution = self._weighted_distribution(
            usable, "subtype", "top_subtype_cn"
        )
        nature_distribution = self._weighted_distribution(
            usable, "nature", "top_nature_cn"
        )

        representative = sorted(
            usable,
            key=lambda p: (
                float(p.get("abnormal_prob") or 0),
                int((p.get("detection") or {}).get("lesion_count") or 0),
                float((p.get("qc") or {}).get("usability_score") or 0),
            ),
            reverse=True,
        )[:3]

        top_organ = next(iter(organ_distribution), "未知")
        top_subtype = next(iter(subtype_distribution), "未知")

        return {
            "total_patches": total,
            "usable_patches": len(usable),
            "rejected_patches": rejected,
            "usable_ratio": round(len(usable) / total, 4) if total else 0.0,
            "abnormal_patches": len(abnormal),
            "abnormal_ratio": round(len(abnormal) / len(usable), 4) if usable else 0.0,
            "mean_abnormal_prob": round(mean_abnormal_prob, 6),
            "total_lesion_count": total_lesion,
            "total_non_lesion_count": total_non_lesion,
            "total_cells": total_lesion + total_non_lesion,
            "top_organ_cn": top_organ,
            "organ_distribution": organ_distribution,
            "top_subtype_cn": top_subtype,
            "subtype_distribution": subtype_distribution,
            "nature_distribution": nature_distribution,
            "representative_patches": [
                {
                    "patch_index": p.get("patch_index"),
                    "patch_name": p.get("patch_name"),
                    "patch_url": p.get("patch_url"),
                    "abnormal_prob": p.get("abnormal_prob"),
                    "lesion_count": (p.get("detection") or {}).get("lesion_count", 0),
                    "roi_image_url": (p.get("detection") or {}).get("roi_image_url", ""),
                    "nature": (p.get("nature") or {}).get("top_nature_cn", ""),
                    "subtype": (p.get("subtype") or {}).get("top_subtype_cn", ""),
                }
                for p in representative
            ],
        }

    def _hard_release(self):
        """彻底清空 GPU 上所有模型和缓存"""
        self.vit_model = None
        self.phikon_model = None
        self.phikon_head = None
        self.phikon_transform = None
        self.nature_phikon_head = None
        self.anomaly_model = None
        self.anomaly_sched = None
        self.anomaly_tf = None
        self.yolo_model = None
        self.sam_predictor = None
        self.gcn_model = None
        self.subtype_model = None
        self.vit_transform = None
        gc.collect()
        if torch.cuda.is_available():
            try:
                torch.cuda.synchronize()
            except RuntimeError as e:
                if _is_cuda_context_failure(e):
                    self._cuda_unhealthy = True
                    print(f"[GPU] CUDA 上下文异常，synchronize 失败: {e}")
                else:
                    print(f"[GPU] synchronize 失败: {e}")
            try:
                torch.cuda.empty_cache()
            except RuntimeError as e:
                if _is_cuda_context_failure(e):
                    self._cuda_unhealthy = True
                    print(f"[GPU] CUDA 上下文异常，empty_cache 失败: {e}")
                else:
                    print(f"[GPU] empty_cache 失败: {e}")
            # 不要调用 ipc_collect()，会破坏 Ollama 等其它 CUDA 进程的上下文


    def _notify_running(self, _push, step_id: int, total: int):
        step_info = PIPELINE_STEPS[step_id - 1]  # step_id 是 1-based，数组是 0-based
        _push(_make_event(step_id, step_info["name"],
                          "running", step_id / total))

    # ============================================================
    # Step 0: WSI 质量检测（复用 wsi_qc 模块）
    # ============================================================

    def _run_qc(self, image_path: str, results_dir: str) -> dict:
        """
        WSI 质量检测 → 返回结构化结果

        所有格式统一走质量检测：
        - 小图（PNG/JPG/BMP/TIFF）走 OpenCV 实时评估
        - 大切片（.svs/.ndpi）走 lazyslide/tiatoolbox

        @return: {
            "is_usable": bool,
            "usability_score": float (0~1),
            "focus_score": float (0~10),
            "stain_score": float (0~10),
            "tissue_ratio": float (0~1),
            "warnings": [str],
        }
        """
        try:
            sys.path.insert(0, base_dir)
            from wsi_qc import WSISlideQC
            qc = WSISlideQC()
            qc.USABILITY_THRESHOLD = float(QC_CFG.get("usability_threshold", 0.6))
            qc.FOCUS_THRESHOLD = float(QC_CFG.get("focus_threshold", 4.0))
            qc.STAIN_THRESHOLD = float(QC_CFG.get("stain_threshold", 4.0))
            report = qc.check(image_path)
            return _qc_with_details({
                "is_usable": report.is_usable,
                "usability_score": round(report.usability_score, 4),
                "focus_score": round(report.focus_score, 1),
                "stain_score": round(report.stain_score, 1),
                "tissue_ratio": round(report.tissue_ratio, 4),
                "warnings": report.warnings,
            })
        except ImportError:
            return self._qc_fallback(image_path)

    def _qc_fallback(self, image_path: str) -> dict:
        """wsi_qc 不可用时的内联 OpenCV 质量检测"""
        import cv2
        import numpy as np
        try:
            img = _imread_unicode(image_path)
            if img is None:
                return _qc_with_details({"is_usable": False, "usability_score": 0.0,
                        "focus_score": 0.0, "stain_score": 0.0,
                        "tissue_ratio": 0.0, "warnings": ["无法读取图像"]})
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            tissue_mask = (gray < np.percentile(gray, 25)).astype(np.uint8) * 255
            kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
            tissue_mask = cv2.morphologyEx(tissue_mask, cv2.MORPH_CLOSE, kernel)
            tp = np.sum(tissue_mask > 0)
            tissue_ratio = tp / tissue_mask.size
            masked = gray.copy()
            masked[tissue_mask == 0] = 0
            lv = cv2.Laplacian(masked, cv2.CV_64F).var()
            focus = min(10.0, max(0.0, lv / 50.0))
            hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
            stain = min(10.0, max(0.0, hsv[:,:,1][tissue_mask>0].mean()/25.5)) if tp>0 else 0.0
            usability = round(min(1.0, tissue_ratio/0.3)*0.3 + focus/10.0*0.35 + stain/10.0*0.35, 4)
            _u_thr = float(QC_CFG.get("usability_threshold", 0.6))
            _f_thr = float(QC_CFG.get("focus_threshold", 4.0))
            _s_thr = float(QC_CFG.get("stain_threshold", 4.0))
            is_usable = usability >= _u_thr and focus >= _f_thr and stain >= _s_thr
            warnings = []
            if tissue_ratio < float(QC_CFG.get("tissue_ratio_min_hint", 0.01)):
                warnings.append("组织占比过低")
            if focus < _f_thr:
                warnings.append(f"对焦不足({focus:.1f})")
            if stain < _s_thr:
                warnings.append(f"染色不足({stain:.1f})")
            return _qc_with_details({"is_usable": is_usable, "usability_score": usability,
                    "focus_score": round(focus,1), "stain_score": round(stain,1),
                    "tissue_ratio": round(tissue_ratio,4), "warnings": warnings})
        except Exception as e:
            return _qc_with_details({"is_usable": True, "usability_score": 1.0,
                    "focus_score": 10.0, "stain_score": 10.0,
                    "tissue_ratio": 1.0, "warnings": [f"QC异常: {e}"]})

    # ============================================================
    # Step 1: 器官分类 (ViT-B/16)
    # ============================================================

    def _run_organ(self, image_path: str, results_dir: str) -> dict:
        """
        器官分类 → 结构化结果（按 config 的 organ.backbone 在 ViT / Phikon 间切换）

        @return: {
            "top_organ": str,
            "top_prob": float,
            "top5": [{"name": str, "prob": float}, ...],
            "chart_url": str (relative),
        }
        """
        if self.organ_backbone == "phikon" and self.phikon_model is not None:
            return self._run_organ_phikon(image_path, results_dir)

        img = Image.open(image_path).convert("RGB")
        img_t = self.vit_transform(img).unsqueeze(0).to(self.device)

        with torch.no_grad():
            out = self.vit_model(img_t)
            probs = F.softmax(out[0], dim=0).cpu().numpy()

        top_idx = int(np.argmax(probs))
        top5_idx = np.argsort(probs)[-5:][::-1]

        top5 = [
            {"name": ORGANS[i], "name_cn": ORGAN_CN.get(ORGANS[i], ORGANS[i]),
             "prob": _safe_prob(probs, i)}
            for i in top5_idx
        ]

        # 保存图表
        import uuid
        chart_name = f"organ_{uuid.uuid4().hex[:8]}.png"
        chart_path = os.path.join(results_dir, chart_name)

        fig, ax = plt.subplots(figsize=(6, 4))
        top5_names = [ORGAN_CN.get(ORGANS[i], ORGANS[i]) for i in top5_idx]
        top5_probs = probs[top5_idx]
        y_pos = np.arange(len(top5_names))
        bars = ax.barh(y_pos, top5_probs, align='center', color='#2563eb')
        ax.set_yticks(y_pos)
        ax.set_yticklabels(top5_names, fontsize=10)
        ax.invert_yaxis()
        ax.set_xlabel('Probability')
        ax.set_xlim(0, 1.0)
        for bar in bars:
            w = bar.get_width()
            ax.text(w + 0.01, bar.get_y() + bar.get_height() / 2.,
                    f'{w:.1%}', va='center', fontsize=9)
        plt.tight_layout()
        plt.savefig(chart_path, bbox_inches='tight', dpi=100)
        plt.close(fig)

        return {
            "top_organ": ORGANS[top_idx],
            "top_organ_cn": ORGAN_CN.get(ORGANS[top_idx], ORGANS[top_idx]),
            "top_prob": _safe_prob(probs, top_idx),
            "top5": top5,
            "chart_url": f"/static/results/{chart_name}",
        }

    def _run_organ_phikon(self, image_path: str, results_dir: str) -> dict:
        """冻结 Phikon-v2 抽特征 + 线性头 → 器官分类（P0 升级路径）"""
        img = Image.open(image_path).convert("RGB")
        img_t = self.phikon_transform(img).unsqueeze(0).to(self.device)

        with torch.no_grad():
            with torch.autocast(device_type="cuda", dtype=torch.float16):
                out = self.phikon_model(img_t)
            feat = out.last_hidden_state.float()[:, 0]            # CLS (1, 1024)
            feat = (feat - self.phikon_head["mean"]) / self.phikon_head["scale"]
            logits = feat @ self.phikon_head["weight"].T + self.phikon_head["bias"]
            probs = F.softmax(logits[0], dim=0).cpu().numpy()

        top_idx = int(np.argmax(probs))
        top5_idx = np.argsort(probs)[-5:][::-1]
        top5 = [
            {"name": ORGANS[i], "name_cn": ORGAN_CN.get(ORGANS[i], ORGANS[i]),
             "prob": _safe_prob(probs, i)}
            for i in top5_idx
        ]

        import uuid
        chart_name = f"organ_{uuid.uuid4().hex[:8]}.png"
        chart_path = os.path.join(results_dir, chart_name)
        fig, ax = plt.subplots(figsize=(6, 4))
        top5_names = [ORGAN_CN.get(ORGANS[i], ORGANS[i]) for i in top5_idx]
        y_pos = np.arange(len(top5_names))
        bars = ax.barh(y_pos, probs[top5_idx], align='center', color='#2563eb')
        ax.set_yticks(y_pos)
        ax.set_yticklabels(top5_names, fontsize=10)
        ax.invert_yaxis()
        ax.set_xlabel('Probability')
        ax.set_xlim(0, 1.0)
        for bar in bars:
            w = bar.get_width()
            ax.text(w + 0.01, bar.get_y() + bar.get_height() / 2., f'{w:.1%}', va='center', fontsize=9)
        plt.tight_layout()
        plt.savefig(chart_path, bbox_inches='tight', dpi=100)
        plt.close(fig)

        return {
            "top_organ": ORGANS[top_idx],
            "top_organ_cn": ORGAN_CN.get(ORGANS[top_idx], ORGANS[top_idx]),
            "top_prob": _safe_prob(probs, top_idx),
            "top5": top5,
            "chart_url": f"/static/results/{chart_name}",
        }

    # ============================================================
    # Step 2: 细胞检测与分割 (YOLOv8 + SAM)
    # ============================================================

    def _run_detection(self, image_path: str, results_dir: str) -> dict:
        """
        YOLO + SAM 细胞检测 → 结构化结果

        @return: {
            "lesion_count": int,
            "non_lesion_count": int,
            "total_boxes": int,
            "roi_image_url": str (relative),
        }
        """
        image = _imread_unicode(image_path)
        if image is None:
            return {"lesion_count": 0, "non_lesion_count": 0,
                    "total_boxes": 0, "roi_image_url": ""}

        # 大图等比缩放到 DETECTION_MAX_SIDE 以内，降低显存压力；
        # 小图放大到 DETECTION_MIN_SIDE（模型按 512 训练，放大显著提升小目标召回）
        h, w = image.shape[:2]
        if max(h, w) > DETECTION_MAX_SIDE:
            scale = DETECTION_MAX_SIDE / max(h, w)
            image = cv2.resize(image, (int(w * scale), int(h * scale)),
                               interpolation=cv2.INTER_AREA)
        elif max(h, w) < DETECTION_MIN_SIDE:
            scale = DETECTION_MIN_SIDE / max(h, w)
            image = cv2.resize(image, (int(w * scale), int(h * scale)),
                               interpolation=cv2.INTER_CUBIC)

        image_rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)

        # 注意：YOLO 模型按 BGR 通道训练，必须传 BGR 图（传 RGB 会导致检出数暴跌）
        results = self.yolo_model(image, verbose=False, conf=YOLO_CELL_CONF_THRESHOLD)
        boxes = results[0].boxes

        # SAM 分割 — 先清空显存缓存再加载 SAM，避免 ViT 释放后的碎片
        all_masks = []
        if ENABLE_SAM_SEGMENTATION and self.sam_predictor and len(boxes) > 0:
            torch.cuda.empty_cache()
            self.sam_predictor.set_image(image_rgb)
            for box in boxes:
                cls_id = int(box.cls[0].item())
                input_box = box.xyxy[0].cpu().numpy()
                masks, _, _ = self.sam_predictor.predict(
                    point_coords=None, point_labels=None,
                    box=input_box[None, :], multimask_output=False,
                )
                all_masks.append((masks[0], cls_id, input_box))

        # 绘制结果图
        fig, ax = plt.subplots(figsize=(8, 8))
        ax.imshow(image_rgb)

        lesion_count = 0
        non_lesion_count = 0

        if len(all_masks) > 0:
            for mask, cls_id, box_coords in all_masks:
                x1, y1, x2, y2 = box_coords
                color = 'red' if cls_id == 0 else 'green'
                label = "lesion" if cls_id == 0 else "non_lesion"
                if cls_id == 0:
                    lesion_count += 1
                else:
                    non_lesion_count += 1

                mask_color = np.array([1, 0, 0, 0.6]) if cls_id == 0 else np.array([0, 1, 0, 0.6])
                h_m, w_m = mask.shape[-2:]
                mask_image = mask.reshape(h_m, w_m, 1) * mask_color.reshape(1, 1, -1)
                ax.imshow(mask_image)
                rect = patches.Rectangle((x1, y1), x2 - x1, y2 - y1,
                                         fill=False, edgecolor=color, linewidth=1.5)
                ax.add_patch(rect)
                ax.text(x1, y1 - 2, label, color='white', fontsize=8,
                        bbox=dict(facecolor=color, alpha=0.5))
        else:
            for box in boxes:
                cls_id = int(box.cls[0].item())
                x1, y1, x2, y2 = box.xyxy[0].cpu().numpy()
                color = 'red' if cls_id == 0 else 'green'
                label = "lesion" if cls_id == 0 else "non_lesion"
                if cls_id == 0:
                    lesion_count += 1
                else:
                    non_lesion_count += 1
                rect = patches.Rectangle((x1, y1), x2 - x1, y2 - y1,
                                         fill=False, edgecolor=color, linewidth=1.5)
                ax.add_patch(rect)
                ax.text(x1, y1 - 2, label, color='white', fontsize=8,
                        bbox=dict(facecolor=color, alpha=0.5))

        plt.axis('off')

        import uuid
        roi_name = f"detect_{uuid.uuid4().hex[:8]}.png"
        roi_path = os.path.join(results_dir, roi_name)
        plt.savefig(roi_path, bbox_inches='tight', pad_inches=0)
        plt.close(fig)

        return {
            "lesion_count": lesion_count,
            "non_lesion_count": non_lesion_count,
            "total_boxes": len(boxes),
            "roi_image_url": f"/static/results/{roi_name}",
        }

    # ============================================================
    # Step 3: 病变性质判定 (GCN)
    # ============================================================

    def _run_nature(self, image_path: str, results_dir: str) -> dict:
        """
        病变性质判定 → 结构化结果（按 config 的 nature.model 在 GCN / Phikon 间切换）

        @return: {
            "top_nature": str,
            "top_prob": float,
            "probs": [{"name": str, "prob": float}, ...],
            "chart_url": str (relative),
        }
        """
        if self.nature_backbone == "phikon" and self.phikon_model is not None:
            return self._run_nature_phikon(image_path, results_dir)

        image = _imread_unicode(image_path)
        if image is None:
            return {"top_nature": "Unknown", "top_prob": 0,
                    "probs": [], "chart_url": ""}

        # 与检测步骤保持一致：小图放大到 DETECTION_MIN_SIDE，提升细胞召回
        h, w = image.shape[:2]
        if max(h, w) < DETECTION_MIN_SIDE:
            scale = DETECTION_MIN_SIDE / max(h, w)
            image = cv2.resize(image, (int(w * scale), int(h * scale)),
                               interpolation=cv2.INTER_CUBIC)

        image_rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        # 注意：YOLO 模型按 BGR 通道训练，必须传 BGR 图（传 RGB 会导致检出数暴跌）
        results = self.yolo_model(image, verbose=False, conf=YOLO_CELL_CONF_THRESHOLD)
        boxes = results[0].boxes

        if len(boxes) == 0:
            x = torch.zeros((1, 14), dtype=torch.float32)
            adj = torch.ones((1, 1), dtype=torch.float32)
        else:
            cls_ids = []
            sizes = []
            coords = []
            img_h, img_w = image_rgb.shape[:2]
            for box in boxes:
                cls_ids.append(int(box.cls[0].item()))
                x1, y1, x2, y2 = box.xyxy[0].cpu().numpy()
                sizes.append([(x2 - x1) / img_w, (y2 - y1) / img_h])
                coords.append([((x1 + x2) / 2) / img_w, ((y1 + y2) / 2) / img_h])

            cls_ids = np.array(cls_ids, dtype=np.int32)
            coords = np.array(coords, dtype=np.float32)
            sizes = np.array(sizes, dtype=np.float32)

            _lazy_import_nature()
            features = _extract_features_fn(cls_ids, coords, sizes, image_rgb)
            x = torch.tensor(features, dtype=torch.float32)
            adj = _build_adj_fn(coords)

        x = x.to(self.device)
        adj = adj.to(self.device)

        with torch.no_grad():
            out = self.gcn_model([x], [adj])
            probs = F.softmax(out[0], dim=0).cpu().numpy()

        top_idx = int(np.argmax(probs))
        all_probs = [
            {"name": NATURE_CLASSES[i], "name_cn": NATURE_CN.get(NATURE_CLASSES[i], NATURE_CLASSES[i]),
             "prob": _safe_prob(probs, i)}
            for i in range(len(NATURE_CLASSES))
        ]

        # 图表 — 使用中文标签
        import uuid
        chart_name = f"nature_{uuid.uuid4().hex[:8]}.png"
        chart_path = os.path.join(results_dir, chart_name)

        fig, ax = plt.subplots(figsize=(6, 4))
        colors = ['#22c55e', '#ef4444']
        y_pos = np.arange(len(NATURE_CLASSES))
        nature_cn_labels = [NATURE_CN.get(n, n) for n in NATURE_CLASSES]
        bars = ax.barh(y_pos, probs, align='center', color=colors)
        ax.set_yticks(y_pos)
        ax.set_yticklabels(nature_cn_labels, fontsize=10)
        ax.invert_yaxis()
        ax.set_xlabel('Probability')
        ax.set_xlim(0, 1.0)
        for bar in bars:
            w = bar.get_width()
            ax.text(w + 0.01, bar.get_y() + bar.get_height() / 2.,
                    f'{w:.2%}', va='center', fontsize=9)
        plt.tight_layout()
        plt.savefig(chart_path, bbox_inches='tight', dpi=100)
        plt.close(fig)

        result = {
            "top_nature": NATURE_CLASSES[top_idx],
            "top_nature_cn": NATURE_CN.get(NATURE_CLASSES[top_idx], NATURE_CLASSES[top_idx]),
            "top_prob": _safe_prob(probs, top_idx),
            "probs": all_probs,
            "chart_url": f"/static/results/{chart_name}",
        }
        return self._attach_anomaly(result, image_path, results_dir)

    def _run_nature_phikon(self, image_path: str, results_dir: str) -> dict:
        """冻结 Phikon-v2 抽特征 + 线性头 → 病变性质（P1 升级路径，图像证据直接判读）"""
        img = Image.open(image_path).convert("RGB")
        img_t = self.phikon_transform(img).unsqueeze(0).to(self.device)
        with torch.no_grad():
            with torch.autocast(device_type="cuda", dtype=torch.float16):
                out = self.phikon_model(img_t)
            feat = out.last_hidden_state.float()[:, 0]
            feat = (feat - self.nature_phikon_head["scaler_mean"]) / self.nature_phikon_head["scaler_scale"]
            logits = feat @ self.nature_phikon_head["weight"].T + self.nature_phikon_head["bias"]
            p_abn = torch.sigmoid(logits[0, 0]).item()
        probs = np.array([1.0 - p_abn, p_abn])   # [Normal, Abnormal]

        top_idx = int(np.argmax(probs))
        all_probs = [
            {"name": NATURE_CLASSES[i], "name_cn": NATURE_CN.get(NATURE_CLASSES[i], NATURE_CLASSES[i]),
             "prob": _safe_prob(probs, i)}
            for i in range(len(NATURE_CLASSES))
        ]

        import uuid
        chart_name = f"nature_{uuid.uuid4().hex[:8]}.png"
        chart_path = os.path.join(results_dir, chart_name)
        fig, ax = plt.subplots(figsize=(6, 4))
        colors = ['#22c55e', '#ef4444']
        y_pos = np.arange(len(NATURE_CLASSES))
        nature_cn_labels = [NATURE_CN.get(n, n) for n in NATURE_CLASSES]
        bars = ax.barh(y_pos, probs, align='center', color=colors)
        ax.set_yticks(y_pos)
        ax.set_yticklabels(nature_cn_labels, fontsize=10)
        ax.invert_yaxis()
        ax.set_xlabel('Probability')
        ax.set_xlim(0, 1.0)
        for bar in bars:
            w = bar.get_width()
            ax.text(w + 0.01, bar.get_y() + bar.get_height() / 2., f'{w:.2%}', va='center', fontsize=9)
        plt.tight_layout()
        plt.savefig(chart_path, bbox_inches='tight', dpi=100)
        plt.close(fig)

        result = {
            "top_nature": NATURE_CLASSES[top_idx],
            "top_nature_cn": NATURE_CN.get(NATURE_CLASSES[top_idx], NATURE_CLASSES[top_idx]),
            "top_prob": _safe_prob(probs, top_idx),
            "probs": all_probs,
            "chart_url": f"/static/results/{chart_name}",
        }
        return self._attach_anomaly(result, image_path, results_dir)

    def _attach_anomaly(self, result: dict, image_path: str, results_dir: str) -> dict:
        """把 P2 扩散异常检测结果附加到病变性质结果上（失败不阻断主流程）"""
        if not self.anomaly_enabled or self.anomaly_model is None:
            return result
        try:
            result.update(self._run_anomaly(image_path, results_dir))
        except Exception as e:
            print(f"[Anomaly] 异常检测失败（不影响主流程）: {e}")
        return result

    def _run_anomaly(self, image_path: str, results_dir: str) -> dict:
        """DDPM 重建误差 → 异常分数 + 热力图（实验性参考，AUROC≈0.67）"""
        import uuid

        res = self.anomaly_resolution
        img = Image.open(image_path).convert("RGB")
        x0 = self.anomaly_tf(img).unsqueeze(0).to(self.device)
        acc = torch.zeros(1, device=self.device)
        accmap = torch.zeros_like(x0)
        with torch.no_grad():
            for t_val in self.anomaly_timesteps:
                t = torch.full((1,), int(t_val), device=self.device, dtype=torch.long)
                noise = torch.randn_like(x0)
                x_t = self.anomaly_sched.add_noise(x0, noise, t)
                eps = self.anomaly_model(x_t, t).sample
                ab = self.anomaly_sched.alphas_cumprod[int(t_val)].to(self.device)
                x0_pred = (x_t - (1.0 - ab).sqrt() * eps) / ab.sqrt()
                err = (x0 - x0_pred).abs()
                acc += err.flatten(1).mean(1)
                accmap += err
        score = float((acc / len(self.anomaly_timesteps)).item())
        heat = (accmap / len(self.anomaly_timesteps))[0].mean(0).cpu().numpy()
        heat = (heat - heat.min()) / (heat.max() - heat.min() + 1e-8)

        # 展示层：模型推理输入固定 64px，但出图按 256px 平滑渲染。
        # 原图复刻与输入一致的视野（短边缩放+中心裁切），热力图三次插值放大，
        # 避免 64px 小图被直接放大成马赛克。
        disp_res = 256
        disp_tf = transforms.Compose([
            transforms.Resize(disp_res, interpolation=transforms.InterpolationMode.BICUBIC),
            transforms.CenterCrop(disp_res),
        ])
        orig_disp = np.array(disp_tf(img))
        heat_disp = cv2.resize(heat.astype(np.float32), (disp_res, disp_res),
                               interpolation=cv2.INTER_CUBIC)
        heat_disp = np.clip(heat_disp, 0.0, 1.0)

        heat_name = f"anomaly_{uuid.uuid4().hex[:8]}.png"
        heat_path = os.path.join(results_dir, heat_name)
        fig, ax = plt.subplots(1, 3, figsize=(12, 4))
        ax[0].imshow(orig_disp); ax[0].set_title("原始"); ax[0].axis("off")
        ax[1].imshow(heat_disp, cmap="jet", interpolation="bilinear"); ax[1].set_title("异常热力图"); ax[1].axis("off")
        ax[2].imshow(orig_disp); ax[2].imshow(heat_disp, cmap="jet", alpha=0.45, interpolation="bilinear"); ax[2].set_title("叠加"); ax[2].axis("off")
        plt.tight_layout(); plt.savefig(heat_path, dpi=130, bbox_inches="tight", pad_inches=0.06); plt.close(fig)

        return {
            "anomaly_score": round(score, 6),
            "anomaly_heatmap_url": f"/static/results/{heat_name}",
            "anomaly_note": "扩散模型重建误差（实验性参考，AUROC≈0.67，仅供参考）",
        }

    # ============================================================
    # Step 4: 亚型分类 (MobileNetV3)
    # ============================================================

    def _run_subtype(self, image_path: str, results_dir: str) -> dict:
        """
        MobileNetV3 亚型分类 → 结构化结果

        @return: {
            "top_subtype": str,
            "top_prob": float,
            "top5": [{"name": str, "prob": float}, ...],
            "chart_url": str (relative),
        }
        """
        img = Image.open(image_path).convert("RGB")
        img_t = self.subtype_transform(img).unsqueeze(0).to(self.device)

        with torch.no_grad():
            out = self.subtype_model(img_t)
            probs = F.softmax(out[0], dim=0).cpu().numpy()

        top_idx = int(np.argmax(probs))
        num_show = min(5, len(self.subtype_classes))
        top_indices = np.argsort(probs)[-num_show:][::-1]

        top5 = []
        for i in top_indices:
            s = self.subtype_classes[i]
            top5.append({
                "name": SUBTYPE_FULL_NAMES.get(s, s),
                "name_cn": SUBTYPE_CN.get(s, s),
                "code": s,
                "prob": _safe_prob(probs, i),
            })

        # 图表 — 中文标签
        import uuid
        chart_name = f"subtype_{uuid.uuid4().hex[:8]}.png"
        chart_path = os.path.join(results_dir, chart_name)

        fig, ax = plt.subplots(figsize=(8, 5))
        top5_names = [SUBTYPE_CN.get(self.subtype_classes[i], self.subtype_classes[i])
                      for i in top_indices]
        top5_probs = probs[top_indices]
        y_pos = np.arange(len(top5_names))
        bars = ax.barh(y_pos, top5_probs, align='center', color='#d97706')
        ax.set_yticks(y_pos)
        ax.set_yticklabels(top5_names, fontsize=10)
        ax.invert_yaxis()
        ax.set_xlabel('Probability')
        ax.set_xlim(0, 1.0)
        for bar in bars:
            w = bar.get_width()
            ax.text(w + 0.01, bar.get_y() + bar.get_height() / 2.,
                    f'{w:.2%}', va='center', fontsize=9)
        plt.tight_layout()
        plt.savefig(chart_path, bbox_inches='tight', dpi=100)
        plt.close(fig)

        top_s = self.subtype_classes[top_idx]
        return {
            "top_subtype": SUBTYPE_FULL_NAMES.get(top_s, top_s),
            "top_subtype_cn": SUBTYPE_CN.get(top_s, top_s),
            "top_prob": _safe_prob(probs, top_idx),
            "top5": top5,
            "chart_url": f"/static/results/{chart_name}",
        }

    # ============================================================
    # 保留原有公开方法（向后兼容，供旧 API 使用）
    # ============================================================

    def predict_organ(self, image_path, output_path):
        result = self._run_organ(image_path, os.path.dirname(output_path))
        chart_path = os.path.join(os.path.dirname(output_path),
                                  os.path.basename(result["chart_url"]))
        return result["top_organ"], result["top_prob"]

    def process_roi(self, image_path, output_path):
        result = self._run_detection(image_path, os.path.dirname(output_path))
        return result["lesion_count"]

    def predict_nature(self, image_path, output_path):
        self.load_gcn_model()
        self.load_yolo_model()
        result = self._run_nature(image_path, os.path.dirname(output_path))
        return result["top_nature"], result["top_prob"]

    def predict_subtype(self, image_path, output_path):
        result = self._run_subtype(image_path, os.path.dirname(output_path))
        return result["top_subtype"], result["top_prob"]


# ============================================================
# LLM 报告生成器（优先 Ollama；无 Ollama 时回退到内置本地小模型）
# ============================================================

class ReportGenerator:
    """
    LLM 病理分析报告生成器

    接收五步检测结果 + 用户病情描述 → 生成结构化中文报告。
    后端优先级：
      1) 本地 Ollama（若已安装并运行，模型 qwen3.5:4b）
      2) 内置 transformers 小模型（models/qwen2.5-1.5b-instruct），无需任何外部服务
    """

    OLLAMA_URL = "http://localhost:11434/api/generate"
    MODEL = "qwen3.5:4b"
    LOCAL_MODEL_DIR = os.path.join(base_dir, "models", "qwen2.5-1.5b-instruct")
    _local_pipe = None

    @classmethod
    def generate(cls, description: str, step_results: list,
                 progress_callback=None) -> str:
        """
        生成病理分析报告：Ollama 优先，失败则用内置本地模型兜底。
        """
        try:
            return cls._generate_with_llm(description, step_results, progress_callback)
        except Exception as e:
            print(f"[ReportGenerator] Ollama 不可用（{type(e).__name__}: {e}），"
                  f"改用内置本地小模型生成报告")
        return cls._generate_with_local_model(description, step_results, progress_callback)

    # ---------- 内置本地模型（无需 Ollama） ----------
    @classmethod
    def _build_local_pipeline(cls):
        if cls._local_pipe is not None:
            return cls._local_pipe
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        path = cls.LOCAL_MODEL_DIR
        if not os.path.isdir(path):
            raise FileNotFoundError(f"未找到内置报告模型目录: {path}")

        tok = AutoTokenizer.from_pretrained(path)
        last_err = None
        for device, dtype in ((("cuda", torch.float16) if torch.cuda.is_available()
                               else ("cpu", torch.float32)),
                              ("cpu", torch.float32)):
            try:
                model = AutoModelForCausalLM.from_pretrained(path, torch_dtype=dtype)
                model = model.to(device).eval()
                cls._local_pipe = (tok, model, device)
                print(f"[ReportGenerator] 内置报告模型已加载: {path} ({device})")
                return cls._local_pipe
            except Exception as e:      # 显存不足等 → 退到 CPU
                last_err = e
                print(f"[ReportGenerator] 以 {device} 加载失败: {e}，尝试退避")
        raise last_err

    @classmethod
    def _generate_with_local_model(cls, description: str, step_results: list,
                                   progress_callback=None) -> str:
        import torch

        prompt = cls._build_prompt(description, step_results)
        print(f"[ReportGenerator] 内置模型 Prompt 长度: {len(prompt)} 字符")
        if progress_callback:
            progress_callback({"status": "generating",
                               "message": "正在调用内置本地模型生成报告..."})

        tok, model, device = cls._build_local_pipeline()
        messages = [{"role": "user", "content": prompt}]
        text = tok.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        inputs = tok(text, return_tensors="pt").to(device)

        with torch.no_grad():
            out = model.generate(**inputs, max_new_tokens=1400, do_sample=True,
                                 temperature=0.3, top_p=0.9, repetition_penalty=1.05,
                                 pad_token_id=tok.eos_token_id)
        report = tok.decode(out[0][inputs["input_ids"].shape[1]:],
                            skip_special_tokens=True).strip()
        if not report:
            raise ValueError("内置本地模型返回空响应")
        for pre in ("好的", "以下是", "好的，"):
            if report.startswith(pre):
                report = report.split("\n", 1)[-1].strip()
                break
        print(f"[ReportGenerator] 内置模型报告生成成功 ({len(report)} 字符)")
        return report

    @classmethod
    def _build_summary(cls, step_results: list) -> dict:
        """从五步结果中提取关键摘要"""
        for evt in step_results:
            data = evt.get("data", {}) or {}
            if evt.get("event_type") == "multi_summary" or data.get("event_type") == "multi_summary":
                patch_summaries = []
                for patch in data.get("patch_results", []) or []:
                    qc = patch.get("qc") or {}
                    organ = patch.get("organ") or {}
                    detect = patch.get("detection") or {}
                    nature = patch.get("nature") or {}
                    subtype = patch.get("subtype") or {}
                    patch_summaries.append({
                        "patch_index": patch.get("patch_index"),
                        "usable": patch.get("is_usable"),
                        "quality_score": qc.get("usability_score", 0),
                        "focus_score": qc.get("focus_score", 0),
                        "stain_score": qc.get("stain_score", 0),
                        "tissue_ratio": qc.get("tissue_ratio", 0),
                        "fail_reasons": qc.get("fail_reasons", []),
                        "organ": organ.get("top_organ_cn", organ.get("top_organ", "")),
                        "organ_prob": organ.get("top_prob", 0),
                        "lesion_cells": detect.get("lesion_count", 0),
                        "non_lesion_cells": detect.get("non_lesion_count", 0),
                        "nature": nature.get("top_nature_cn", nature.get("top_nature", "")),
                        "nature_prob": nature.get("top_prob", 0),
                        "abnormal_prob": patch.get("abnormal_prob", 0),
                        "subtype": subtype.get("top_subtype_cn", subtype.get("top_subtype", "")),
                        "subtype_prob": subtype.get("top_prob", 0),
                        "errors": patch.get("errors", []),
                    })
                return {
                    "mode": "multi_patch",
                    "multi": data.get("summary", {}),
                    "patch_results": patch_summaries,
                }

        summary = {}
        for evt in step_results:
            sid = evt.get("step_id", -1)
            data = evt.get("data", {})
            if sid == 1:  # QC
                summary["qc"] = {
                    "usable": "通过" if data.get("is_usable") else "未通过",
                    "score": data.get("usability_score", 0),
                    "focus": data.get("focus_score", 0),
                    "stain": data.get("stain_score", 0),
                }
            elif sid == 2:  # Organ
                summary["organ"] = {
                    "name": data.get("top_organ_cn", data.get("top_organ", "未知")),
                    "prob": data.get("top_prob", 0),
                }
            elif sid == 3:  # Detection
                summary["detect"] = {
                    "lesion": data.get("lesion_count", 0),
                    "non_lesion": data.get("non_lesion_count", 0),
                    "total": data.get("total_boxes", 0),
                }
            elif sid == 4:  # Nature
                summary["nature"] = {
                    "name": data.get("top_nature_cn", data.get("top_nature", "未知")),
                    "prob": data.get("top_prob", 0),
                    "anomaly_score": data.get("anomaly_score"),
                    "anomaly_note": data.get("anomaly_note"),
                }
            elif sid == 5:  # Subtype
                summary["subtype"] = {
                    "name": data.get("top_subtype_cn", data.get("top_subtype", "未知")),
                    "prob": data.get("top_prob", 0),
                }
        summary["mode"] = "single_image"
        return summary

    @classmethod
    def _build_prompt(cls, description: str, step_results: list) -> str:
        """构建 LLM prompt"""
        import json
        from datetime import datetime
        summary = cls._build_summary(step_results)
        summary_json = json.dumps(summary, ensure_ascii=False, indent=2)
        now_str = datetime.now().strftime("%Y年%m月%d日 %H:%M:%S")

        if summary.get("mode") == "multi_patch":
            instruction = f"""## 多 patch 综合检测结果摘要
{summary_json}

## 报告要求
1. 用中文撰写，专业且通俗易懂。
2. 报告应体现“大图初步切割为多个 patch → patch 级质量检测 → 合格 patch 进入模型分析 → 跨 patch 汇总”的业务流程。
3. 结构建议：基本信息 → patch 质量覆盖情况 → 器官来源综合判断 → 细胞检测汇总 → 病变性质综合判断 → 组织亚型提示 → 代表性 patch 说明 → 综合意见与复核建议。
4. 对低质量 patch 只说明其被拦截或未纳入后续模型分析，不要把低质量 patch 的缺失结果写成阴性结果。
5. 病变性质统一使用 Normal / Abnormal 二分类口径；组织亚型结果写作辅助提示，不写成最终病理分型结论。
6. 综合意见需要结合病情描述、异常 patch 占比、异常概率、细胞检测数量和代表性 patch 信息进行分析。"""
        else:
            # 判断质控是否通过
            qc_data = summary.get("qc", {})
            qc_passed = qc_data.get("usable") == "通过"

            if not qc_passed:
                # 质控未通过：只做了 Step 1
                instruction = f"""## 重要提示
Step 1 图像质量检测结果为**未通过**，后续器官分类、细胞检测、病变性质和亚型分类均已自动跳过。
请重点关注以下方面：
1. 告知用户图像质量不达标的具体原因（对焦、染色或组织占比问题）
2. 给出改进建议（如重新扫描、重新染色、更换切片区域等）
3. 如果有病情描述，可以结合描述给出初步建议
4. 最后提醒用户：建议更换质量合格的图像重新分析"""
            else:
                instruction = f"""## 检测结果摘要
{summary_json}

## 报告要求
1. 用中文撰写，专业且通俗易懂
2. 结构：基本信息 → 图像质量 → 器官分类(附置信度) → 细胞检测(病变/非病变细胞数) → 病变性质(附置信度) → 组织亚型提示(附置信度) → 综合意见 → 建议
3. 病变性质统一使用 Normal / Abnormal 二分类口径，组织亚型结果不得写成最终病理分型结论
4. 综合意见需要结合病情描述和检测数据做临床关联分析
5. 若存在 anomaly_score（扩散模型重建误差），仅作为实验性参考提及，不要写成诊断结论"""

        return f"""你是一位资深病理学专家。当前系统时间为 {now_str}。请根据以下检测数据和病情描述，生成一份结构化的病理分析报告。

## 病情描述
{description if description else "（无额外描述）"}

{instruction}

4. 最后加一行免责声明：「⚠ 本报告由AI辅助生成，仅供参考，请以病理医生诊断为准」
5. 使用 Markdown 格式，标题用 ##

请开始生成报告："""

    @classmethod
    def _generate_with_llm(cls, description: str, step_results: list,
                           progress_callback=None) -> str:
        """调用 Ollama API 生成报告"""
        import requests

        prompt = cls._build_prompt(description, step_results)
        print(f"[ReportGenerator] Prompt 长度: {len(prompt)} 字符")

        payload = {
            "model": cls.MODEL,
            "prompt": prompt,
            "stream": False,
            "think": False,
            "keep_alive": 0,
            "options": {
                "temperature": 0.3,
                "top_p": 0.9,
                "num_ctx": 8192,
                "num_predict": 8192,
            }
        }

        if progress_callback:
            progress_callback({"status": "generating", "message": "正在调用本地 LLM 生成报告..."})

        print(f"[ReportGenerator] 正在请求 Ollama: {cls.OLLAMA_URL}")
        # Ollama 可能在管道结束后首次请求时冷启动，加一次 500 重试
        for attempt in range(3):
            resp = requests.post(cls.OLLAMA_URL, json=payload, timeout=600)
            print(f"[ReportGenerator] Ollama 响应状态: {resp.status_code} (attempt {attempt+1})")
            if resp.status_code == 500 and attempt < 2:
                print(f"[ReportGenerator] Ollama 返回 500，等待 3s 后重试...")
                time.sleep(3)
                continue
            break
        resp.raise_for_status()
        result = resp.json()
        meta = {
            "done": result.get("done"),
            "done_reason": result.get("done_reason"),
            "prompt_eval_count": result.get("prompt_eval_count"),
            "eval_count": result.get("eval_count"),
            "total_duration": result.get("total_duration"),
            "load_duration": result.get("load_duration"),
        }
        print(f"[ReportGenerator] Ollama 返回元信息: {meta}")
        report = result.get("response", "").strip()
        if not report:
            thinking_len = len(result.get("thinking", ""))
            result_keys = ", ".join(sorted(result.keys()))
            raise ValueError(
                "Ollama 返回空响应 "
                f"(thinking: {thinking_len}字符, meta: {meta}, keys: {result_keys})"
            )
        if report.startswith("好的") or report.startswith("以下是") or report.startswith("好的，"):
            report = report.split("\n", 1)[-1].strip()
        print(f"[ReportGenerator] LLM 报告生成成功 ({len(report)} 字符)")
        return report
