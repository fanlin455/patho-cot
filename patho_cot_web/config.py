# -*- coding: utf-8 -*-
"""
@file config.py
@brief 系统配置加载模块

配置文件 config.yaml 与本文件同目录；不存在时自动创建默认配置。
所有路径均基于本文件位置推导，不依赖任何绝对路径，
因此整个项目复制到任意目录、任意电脑都能开箱即用。
"""
import os

import yaml

_CONFIG_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(_CONFIG_DIR, "config.yaml")

DEFAULT_CONFIG = {
    # 模型资产根目录（权重、外部模块）。留空时自动发现：
    # 先看本项目根，再沿上级目录寻找含 transformer_organ_classifier 的文件夹；
    # 也可用环境变量 PATHO_COT_MODEL_ROOT 覆盖。支持代码与大体积权重分离部署。
    "paths": {
        "model_root": "",
    },
    # 器官分类（Step 2）骨干：vit=现有 ViT-B/16；phikon=冻结 Phikon-v2 + 线性头（+5.57pp）
    "organ": {
        "backbone": "vit",
    },
    # 病变性质（Step 4）模型：gcn=现有图卷积；phikon=冻结 Phikon-v2 + 线性头（+13.26pp）
    "nature": {
        "model": "gcn",
    },
    # 扩散异常检测（Step 4 附带输出，实验性参考；P2 升级，AUROC≈0.67）
    "anomaly": {
        "enabled": True,          # 是否在病变性质步骤附带输出异常分数 + 热力图
        "timesteps": [300],       # DDPM 重建时间步（消融最优 t=300）
    },
    # 质量检测（Step 1）判定分数线：可在此放宽/收紧质检
    "qc": {
        "usability_threshold": 0.6,      # 综合可用性分数（0~1）
        "focus_threshold": 4.0,          # 对焦评分（0~10）
        "stain_threshold": 4.0,          # 染色评分（0~10）
        "tissue_ratio_min_hint": 0.01,   # 组织占比下限提示
    },
    # 细胞检测（Step 3）
    "detection": {
        "conf_threshold": 0.15,          # YOLO 置信度阈值
        "min_side": 512,                 # 小图放大到的边长（与训练尺度一致，提升召回）
        "max_side": 1024,                # 大图压缩到的边长上限（控制显存）
        "enable_sam": False,             # 是否启用 SAM 像素级分割（8GB 显存建议关闭）
    },
    # 模型加载策略：keep_loaded=True 时常驻 4 个视觉模型（约 500MB 显存），
    # 分步分析每步秒开；设为 False 可省显存（每步重新加载）
    "models": {
        "keep_loaded": True,
    },
}


def _deep_merge(base: dict, override: dict) -> dict:
    """递归合并用户配置到默认配置上，缺失的键保持默认值。"""
    out = dict(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def load_config(path: str = None) -> dict:
    """加载配置。文件不存在则自动生成默认配置文件。"""
    path = path or CONFIG_PATH
    if not os.path.exists(path):
        try:
            with open(path, "w", encoding="utf-8") as f:
                yaml.safe_dump(DEFAULT_CONFIG, f, allow_unicode=True, sort_keys=False)
            print(f"[Config] 已生成默认配置文件: {path}")
        except OSError as e:
            print(f"[Config] 无法写入配置文件 {path}: {e}，使用内置默认值")
        return _deep_merge(DEFAULT_CONFIG, {})
    try:
        with open(path, "r", encoding="utf-8") as f:
            user_cfg = yaml.safe_load(f) or {}
    except Exception as e:
        print(f"[Config] 配置文件解析失败 {path}: {e}，使用内置默认值")
        user_cfg = {}
    return _deep_merge(DEFAULT_CONFIG, user_cfg)
