"""
@file wsi_qc.py
@brief PathProfilerQC2 WSI 切片质量检测模块
       作为 Patho-COT 诊断流水线的 Step 0 前置步骤，对全切片图像(WSI)
       进行自动化质量评估，检测伪影、模糊、染色不良等问题。

       支持两种质量检测模式：
       1. 全局模式（默认）：整图缩略图评估，速度快
       2. 分块模式（--patch_size 指定）：将大图切割后逐 patch 检测再聚合，
          可精确定位低质量区域，支持生成质量热力图

       三种检测引擎（自动降级）：
       1. lazyslide 模式（推荐）：直接加载 PathProfiler 预训练模型
       2. tiatoolbox 模式（备选）：TIAToolbox 组织检测 + 启发式评估
       3. OpenCV 模式（回退）：纯图像处理，无需额外依赖

       使用方式：
           python wsi_qc.py --wsi_path slide.svs --patch_size 512
        或：
           from wsi_qc import WSISlideQC
           qc = WSISlideQC()
           report = qc.check("sample.png", patch_size=512)
"""

import os
import argparse
import warnings
import json
from dataclasses import dataclass, field
from typing import Optional, List, Tuple

import numpy as np
import cv2

# --- 尝试导入依赖，缺失时给出明确提示 ---
_TIATOOLBOX_AVAILABLE = False
_LAZYSLIDE_AVAILABLE = False

try:
    from tiatoolbox.wsicore.wsireader import WSIReader
    _TIATOOLBOX_AVAILABLE = True
except ImportError:
    pass

try:
    from lazyslide.seg import tissue
    _LAZYSLIDE_AVAILABLE = True
except ImportError:
    pass


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


# ============================================================
# 数据结构
# ============================================================

@dataclass
class PatchResult:
    """
    单个图像块（patch）的质量检测结果

    在分块模式下，大图被切割成多个 patch 逐一评估，
    每个 patch 独立产生一份 PatchResult。
    """
    row: int                               # patch 所在行索引
    col: int                               # patch 所在列索引
    x: int                                 # patch 在原图中的 x 坐标
    y: int                                 # patch 在原图中的 y 坐标
    width: int                             # patch 宽度
    height: int                            # patch 高度
    focus_score: float = 10.0              # 对焦评分 0~10
    stain_score: float = 10.0              # 染色评分 0~10
    tissue_ratio: float = 0.0              # 该 patch 内组织占比
    is_usable: bool = True                 # 单 patch 是否合格
    warnings: list = field(default_factory=list)


@dataclass
class QCRreport:
    """WSI 质量检测报告（全局 / 分块聚合）"""
    wsi_path: str                           # WSI 文件路径
    mode: str = "global"                    # 检测模式: global / patch
    patch_size: int = 0                     # 分块尺寸（0=全局模式）
    is_usable: bool = True                  # 整体可用性
    usability_score: float = 1.0            # 可用性评分 0.0 ~ 1.0
    focus_score: float = 10.0               # 对焦质量评分 0 ~ 10（聚合）
    stain_score: float = 10.0               # 染色质量评分 0 ~ 10（聚合）
    tissue_ratio: float = 0.0               # 有效组织占比
    artifact_regions: list = field(default_factory=list)  # 伪影区域列表
    patch_results: List[PatchResult] = field(default_factory=list)  # 分块检测详情
    bad_patch_count: int = 0                # 不合格 patch 数量
    total_patch_count: int = 0              # patch 总数
    warnings: list = field(default_factory=list)

    def __str__(self):
        status = "PASS" if self.is_usable else "REJECT"
        lines = [
            f"========== WSI Quality Report ==========",
            f"  File          : {os.path.basename(self.wsi_path)}",
            f"  Mode          : {self.mode}"
        ]
        if self.mode == "patch":
            lines.append(
                f"  Patch         : {self.total_patch_count} total, "
                f"{self.bad_patch_count} bad "
                f"(size={self.patch_size}px)"
            )
        lines.extend([
            f"  Status        : {status}",
            f"  Usability     : {self.usability_score:.2f} / 1.0",
            f"  Focus         : {self.focus_score:.1f} / 10",
            f"  Stain         : {self.stain_score:.1f} / 10",
            f"  Tissue Ratio  : {self.tissue_ratio:.1%}",
            f"  Artifacts     : {len(self.artifact_regions)} regions detected",
        ])
        if self.warnings:
            lines.append(f"  Warnings      : {'; '.join(self.warnings[:5])}")
        lines.append("=" * 43)
        return "\n".join(lines)

    def to_dict(self) -> dict:
        """导出为字典，方便序列化"""
        d = {
            "wsi_path": self.wsi_path,
            "mode": self.mode,
            "patch_size": self.patch_size,
            "is_usable": self.is_usable,
            "usability_score": self.usability_score,
            "focus_score": self.focus_score,
            "stain_score": self.stain_score,
            "tissue_ratio": self.tissue_ratio,
            "artifact_count": len(self.artifact_regions),
            "bad_patch_count": self.bad_patch_count,
            "total_patch_count": self.total_patch_count,
            "warnings": self.warnings,
        }
        if self.patch_results:
            d["patch_details"] = [
                {
                    "row": p.row, "col": p.col,
                    "x": p.x, "y": p.y,
                    "focus": round(p.focus_score, 1),
                    "stain": round(p.stain_score, 1),
                    "tissue_ratio": round(p.tissue_ratio, 3),
                    "usable": p.is_usable,
                }
                for p in self.patch_results
            ]
        return d

    def save_json(self, output_path: str):
        """保存报告为 JSON 文件"""
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)


# ============================================================
# 质量检测核心类
# ============================================================

class WSISlideQC:
    """
    WSI 切片质量检测器

    封装 PathProfiler 模型（通过 lazyslide / tiatoolbox），
    提供简洁的统一调用接口。

    两种检测模式：
    - 全局模式 (patch_size=None)：快速整图评估
    - 分块模式 (patch_size=int)：切片 → 逐块检测 → 聚合
    """

    # 可用性阈值：低于此值建议丢弃
    USABILITY_THRESHOLD = 0.6
    # 对焦最低合格分
    FOCUS_THRESHOLD = 4
    # 染色最低合格分
    STAIN_THRESHOLD = 4
    # 分块质量热力图缩放尺寸
    HEATMAP_SIZE = 800

    # WSI 专用格式（需要 OpenSlide 读取，不含 TIFF）
    WSI_FORMATS = {'.svs', '.ndpi', '.mrxs', '.vms', '.scn', '.bif'}

    # 普通图像格式（OpenCV 直接读取，含普通 TIFF）
    IMAGE_FORMATS = {'.png', '.jpg', '.jpeg', '.bmp', '.webp', '.tif', '.tiff'}

    def __init__(self, use_lazyslide: bool = True):
        """
        @param use_lazyslide: True 优先使用 lazyslide+PathProfiler 模型，
                             False 回退到 tiatoolbox + 启发式评估
        """
        self._use_lazyslide = use_lazyslide and _LAZYSLIDE_AVAILABLE
        self._use_tiatoolbox = _TIATOOLBOX_AVAILABLE

        if not _TIATOOLBOX_AVAILABLE and not _LAZYSLIDE_AVAILABLE:
            warnings.warn(
                "tiatoolbox 和 lazyslide 均未安装。"
                "将使用 OpenCV 基础质量检测模式。"
                "请执行: pip install tiatoolbox lazyslide"
            )

    # --------------------------------------------------
    # 对外主接口
    # --------------------------------------------------

    @classmethod
    def _is_wsi_format(cls, filepath: str) -> bool:
        """判断是否为 WSI 专用格式（需 OpenSlide）"""
        ext = os.path.splitext(filepath)[1].lower()
        return ext in cls.WSI_FORMATS

    @classmethod
    def _is_image_format(cls, filepath: str) -> bool:
        """判断是否为普通图像格式（OpenCV 可直接读取）"""
        ext = os.path.splitext(filepath)[1].lower()
        return ext in cls.IMAGE_FORMATS

    def check(self, wsi_path: str,
              patch_size: Optional[int] = None,
              stride: Optional[int] = None,
              output_overlay: Optional[str] = None,
              output_heatmap: Optional[str] = None) -> QCRreport:
        """
        对 WSI 切片或普通病理图像进行质量检测

        自动识别文件格式并选择合适的检测引擎：
        - .svs / .ndpi / .tiff 等 WSI 格式 → lazyslide(PathProfiler) / tiatoolbox
        - .png / .jpg / .bmp 等普通图像 → OpenCV 图像质量评估

        @param wsi_path: 图像路径（.svs/.ndpi/.tiff/.png/.jpg 等）
        @param patch_size: 分块尺寸（像素）。None=全局模式，int=分块模式
        @param stride: 分块步长（默认等于 patch_size，即无重叠）
        @param output_overlay: 可选，伪影叠加图输出路径
        @param output_heatmap: 可选，质量热力图输出路径（仅在分块模式有效）
        @return: QCRreport 质量报告对象
        """
        if not os.path.exists(wsi_path):
            raise FileNotFoundError(f"文件不存在: {wsi_path}")

        # 分块模式
        if patch_size and patch_size > 0:
            return self._check_patches(
                wsi_path,
                patch_size=patch_size,
                stride=stride or patch_size,
                output_heatmap=output_heatmap,
            )

        # 全局模式：普通图像格式直接走 OpenCV
        if self._is_image_format(wsi_path):
            report = self._check_fallback(wsi_path)
        elif self._is_wsi_format(wsi_path):
            if self._use_lazyslide:
                report = self._check_lazyslide(wsi_path)
            elif self._use_tiatoolbox:
                report = self._check_tiatoolbox(wsi_path)
            else:
                report = self._check_fallback(wsi_path)
        else:
            report = self._check_fallback(wsi_path)

        return report

    # --------------------------------------------------
    # 分块质量检测（核心新增）
    # --------------------------------------------------

    def _check_patches(self, image_path: str,
                       patch_size: int = 512,
                       stride: int = 512,
                       output_heatmap: Optional[str] = None) -> QCRreport:
        """
        将大图切割为 patch 后逐块质量检测，聚合得出整体评分

        流程：
        1. 加载图像
        2. 按 patch_size 切割（步长 stride）
        3. 每个 patch 独立评估：组织占比 / 对焦 / 染色
        4. 聚合所有 patch 结果：
           - usability_score = 合格patch数 / 总patch数
           - focus_score = 各patch对焦分的加权平均
           - stain_score = 各patch染色分的加权平均
        5. 可选生成质量热力图，直观展示低质量区域

        @param image_path: 图像路径
        @param patch_size: 每个 patch 的边长（像素）
        @param stride: 滑动步长（<=patch_size 则有重叠）
        @param output_heatmap: 可选，保存质量热力图到该路径
        @return: QCRreport（含 patch_results 列表）
        """
        report = QCRreport(
            wsi_path=image_path,
            mode="patch",
            patch_size=patch_size,
        )

        try:
            img = _imread_unicode(image_path)
            if img is None:
                report.warnings.append("无法读取图像文件")
                report.is_usable = False
                return report

            h, w = img.shape[:2]
            if h <= patch_size and w <= patch_size:
                # 图像比 patch 还小，回退到全局模式
                report.mode = "global"
                report.patch_size = 0
                return self._check_fallback(image_path)

            # 计算 grid
            cols = max(1, (w - patch_size) // stride + 1)
            rows = max(1, (h - patch_size) // stride + 1)
            report.total_patch_count = rows * cols

            patch_results: List[PatchResult] = []
            # 用于生成热力图的得分矩阵
            heatmap_data = np.zeros((rows, cols), dtype=np.float32)

            for r in range(rows):
                for c in range(cols):
                    y = r * stride
                    x = c * stride
                    # 处理边界
                    y_end = min(y + patch_size, h)
                    x_end = min(x + patch_size, w)
                    patch = img[y:y_end, x:x_end]

                    pr = self._evaluate_single_patch(
                        patch, row=r, col=c, x=x, y=y,
                        pw=x_end - x, ph=y_end - y,
                    )
                    patch_results.append(pr)
                    heatmap_data[r, c] = self._patch_quality_score(pr)

            report.patch_results = patch_results

            # 聚合统计
            usable_patches = [p for p in patch_results if p.is_usable]
            report.bad_patch_count = len(patch_results) - len(usable_patches)

            if len(patch_results) > 0:
                # 可用性 = 合格 patch 占比
                report.usability_score = round(
                    len(usable_patches) / len(patch_results), 4
                )
                # 对焦/染色 = 所有 patch 的加权平均（按组织占比加权）
                weights = np.array([p.tissue_ratio + 1e-6 for p in patch_results])
                w_sum = weights.sum()
                report.focus_score = round(
                    float(np.average([p.focus_score for p in patch_results],
                                     weights=weights)), 1
                )
                report.stain_score = round(
                    float(np.average([p.stain_score for p in patch_results],
                                     weights=weights)), 1
                )
                report.tissue_ratio = round(
                    float(np.mean([p.tissue_ratio for p in patch_results])), 4
                )

            # 生成警告
            bad_ratio = report.bad_patch_count / max(report.total_patch_count, 1)
            if bad_ratio > 0.5:
                report.warnings.append(
                    f"超过半数 patch 不合格 ({report.bad_patch_count}/{report.total_patch_count})"
                )
            elif bad_ratio > 0.1:
                report.warnings.append(
                    f"{report.bad_patch_count}/{report.total_patch_count} 个 patch 不合格"
                )
            if report.focus_score < self.FOCUS_THRESHOLD:
                report.warnings.append(f"对焦质量不足 ({report.focus_score:.1f}/10)")
            if report.stain_score < self.STAIN_THRESHOLD:
                report.warnings.append(f"染色质量不足 ({report.stain_score:.1f}/10)")

            # 生成热力图
            if output_heatmap:
                self._generate_heatmap(heatmap_data, output_heatmap)

        except Exception as e:
            report.warnings.append(f"分块检测异常: {str(e)}")

        report.is_usable = (
            report.usability_score >= self.USABILITY_THRESHOLD and
            report.focus_score >= self.FOCUS_THRESHOLD and
            report.stain_score >= self.STAIN_THRESHOLD
        )
        return report

    def _evaluate_single_patch(self, patch: np.ndarray,
                               row: int, col: int,
                               x: int, y: int,
                               pw: int, ph: int) -> PatchResult:
        """
        对单个图像块进行质量评估

        @param patch: 图像块 BGR 数组
        @param row: 行索引
        @param col: 列索引
        @param x: 原图 x 坐标
        @param y: 原图 y 坐标
        @param pw: patch 实际宽度
        @param ph: patch 实际高度
        @return: PatchResult
        """
        pr = PatchResult(row=row, col=col, x=x, y=y, width=pw, height=ph)

        try:
            gray = cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY)
            total_px = gray.size

            # --- 组织检测 ---
            # 深色区域 = 组织
            tissue_mask = (gray < np.percentile(gray, 25)).astype(np.uint8) * 255
            kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
            tissue_mask = cv2.morphologyEx(tissue_mask, cv2.MORPH_CLOSE, kernel)
            tissue_px = np.sum(tissue_mask > 0)
            pr.tissue_ratio = tissue_px / total_px if total_px > 0 else 0.0

            # 纯背景 patch 直接标记合格（不参与有效评估）
            if pr.tissue_ratio < 0.01:
                pr.focus_score = 10.0
                pr.stain_score = 10.0
                pr.is_usable = True
                return pr

            # --- 对焦评估 ---
            masked = gray.copy()
            masked[tissue_mask == 0] = 0
            laplacian_var = cv2.Laplacian(masked, cv2.CV_64F).var()
            pr.focus_score = min(10.0, max(0.0, laplacian_var / 50.0))

            # --- 染色评估 ---
            hsv = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV)
            sat = hsv[:, :, 1][tissue_mask > 0]
            pr.stain_score = min(10.0, max(0.0, sat.mean() / 25.5)) if len(sat) > 0 else 0.0

            # --- 单 patch 判定 ---
            if pr.focus_score < self.FOCUS_THRESHOLD:
                pr.warnings.append(f"focus_low({pr.focus_score:.1f})")
            if pr.stain_score < self.STAIN_THRESHOLD:
                pr.warnings.append(f"stain_low({pr.stain_score:.1f})")

            pr.is_usable = (
                pr.focus_score >= self.FOCUS_THRESHOLD and
                pr.stain_score >= self.STAIN_THRESHOLD
            )

        except Exception as e:
            pr.warnings.append(str(e))
            pr.is_usable = False

        return pr

    def _patch_quality_score(self, pr: PatchResult) -> float:
        """
        将 PatchResult 转为 0~1 的综合质量分（用于热力图）
        """
        return (pr.focus_score / 10.0 * 0.5 +
                pr.stain_score / 10.0 * 0.3 +
                min(pr.tissue_ratio / 0.3, 1.0) * 0.2)

    def _generate_heatmap(self, data: np.ndarray, output_path: str):
        """
        生成分块质量热力图

        @param data: rows x cols 的质量分矩阵 (0~1)
        @param output_path: 输出图片路径
        """
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt

        rows, cols = data.shape
        figsize_w = max(6, cols / 4)
        figsize_h = max(4, rows / 4)
        fig, ax = plt.subplots(figsize=(figsize_w, figsize_h))

        im = ax.imshow(data, cmap='RdYlGn', vmin=0, vmax=1, aspect='auto',
                       interpolation='nearest')
        ax.set_title(f"Patch Quality Heatmap ({rows}x{cols} grid)")
        ax.set_xlabel("Column")
        ax.set_ylabel("Row")
        plt.colorbar(im, ax=ax, label="Quality Score (0=bad, 1=good)")
        plt.tight_layout()
        plt.savefig(output_path, dpi=100, bbox_inches='tight')
        plt.close(fig)

    # --------------------------------------------------
    # 方案 A: lazyslide + PathProfiler 模型（推荐）
    # --------------------------------------------------

    def _check_lazyslide(self, wsi_path: str) -> QCRreport:
        """
        使用 lazyslide 调用 PathProfiler 预训练模型进行组织分割与质量评估

        PathProfiler 原论文本身在 5X 放大下做 patch-level 分析（mpp=2.5），
        lazyslide 封装了该模型，自动完成 patch 分割与聚合。
        """
        import wsidata

        report = QCRreport(wsi_path=wsi_path)

        try:
            wsi = wsidata.open_wsi(wsi_path)

            # PathProfiler 内部做 patch-level 组织/伪影分割
            tissue(wsi, model="pathprofiler", mpp=2.5, threshold=0.5)

            shapes = wsi.shapes
            tissue_ann = shapes.get("tissues", None)

            if tissue_ann is not None and len(tissue_ann) > 0:
                geometries = tissue_ann.to_geopandas()
                slide_area = wsi.level_dimensions[0][0] * wsi.level_dimensions[0][1]
                tissue_area = sum(g.area for g in geometries.geometry)
                report.tissue_ratio = tissue_area / slide_area if slide_area > 0 else 0

            report.usability_score = self._estimate_usability(report.tissue_ratio)

            thumb = wsi.get_thumbnail((512, 512))
            thumb_np = np.array(thumb.convert("L"))
            laplacian_var = cv2.Laplacian(thumb_np, cv2.CV_64F).var()
            report.focus_score = min(10.0, max(0.0, laplacian_var / 50.0))

            thumb_rgb = np.array(thumb.convert("RGB"))
            hsv = cv2.cvtColor(thumb_rgb, cv2.COLOR_RGB2HSV)
            mask = hsv[:, :, 2] < 220
            if mask.sum() > 0:
                mean_sat = hsv[:, :, 1][mask].mean()
                report.stain_score = min(10.0, max(0.0, mean_sat / 25.5))
            else:
                report.stain_score = 0

            if report.tissue_ratio < 0.01:
                report.warnings.append("组织占比过低，可能为空玻片")

        except Exception as e:
            report.warnings.append(f"lazyslide 处理异常: {str(e)}")

        report.is_usable = (
            report.usability_score >= self.USABILITY_THRESHOLD and
            report.focus_score >= self.FOCUS_THRESHOLD and
            report.stain_score >= self.STAIN_THRESHOLD
        )
        return report

    # --------------------------------------------------
    # 方案 B: tiatoolbox + 启发式评估
    # --------------------------------------------------

    def _check_tiatoolbox(self, wsi_path: str) -> QCRreport:
        """
        使用 TIAToolbox 进行组织检测 + 图像质量启发式评估（全局缩略图模式）
        """
        report = QCRreport(wsi_path=wsi_path)

        try:
            reader = WSIReader.open(wsi_path)

            # 获取缩略图：优先尝试 MPP 单位，失败则回退到 level
            try:
                thumb = reader.slide_thumbnail(resolution=2.5, units="mpp")
            except (ValueError, KeyError):
                # MPP 不可用（如未标定的 TIFF），回退到低分辨率 level
                info = reader.info.as_dict()
                level = min(info.get("level_count", 1) - 1, 2)  # 用较小的 level
                thumb = reader.slide_thumbnail(resolution=1.0, units="level")
            thumb_np = np.array(thumb.convert("RGB"))
            thumb_gray = cv2.cvtColor(thumb_np, cv2.COLOR_RGB2GRAY)

            # 组织检测
            tissue_mask = (thumb_gray < np.percentile(thumb_gray, 30)).astype(np.uint8) * 255
            kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
            tissue_mask = cv2.morphologyEx(tissue_mask, cv2.MORPH_CLOSE, kernel)
            tissue_mask = cv2.morphologyEx(tissue_mask, cv2.MORPH_OPEN, kernel)

            tissue_pixels = np.sum(tissue_mask > 0)
            report.tissue_ratio = tissue_pixels / tissue_mask.size

            if tissue_pixels > 0:
                masked_gray = thumb_gray.copy()
                masked_gray[tissue_mask == 0] = 0
                laplacian_var = cv2.Laplacian(masked_gray, cv2.CV_64F).var()
                report.focus_score = min(10.0, max(0.0, laplacian_var / 50.0))

                hsv = cv2.cvtColor(thumb_np, cv2.COLOR_RGB2HSV)
                report.stain_score = min(10.0, max(0.0,
                    hsv[:, :, 1][tissue_mask > 0].mean() / 25.5))
            else:
                report.focus_score = 0
                report.stain_score = 0

            report.usability_score = self._estimate_usability(
                tissue_ratio=report.tissue_ratio,
                focus_score=report.focus_score,
                stain_score=report.stain_score,
            )
            report.artifact_regions = self._detect_artifacts(thumb_gray, tissue_mask)

            if report.tissue_ratio < 0.01:
                report.warnings.append("组织占比过低(<1%)，可能为空玻片")
            if report.focus_score < self.FOCUS_THRESHOLD:
                report.warnings.append(f"对焦质量不足 ({report.focus_score:.1f}/10)")
            if report.stain_score < self.STAIN_THRESHOLD:
                report.warnings.append(f"染色质量不足 ({report.stain_score:.1f}/10)")

        except Exception as e:
            report.warnings.append(f"tiatoolbox 处理异常: {str(e)}")

        report.is_usable = (
            report.usability_score >= self.USABILITY_THRESHOLD and
            report.focus_score >= self.FOCUS_THRESHOLD and
            report.stain_score >= self.STAIN_THRESHOLD
        )
        return report

    # --------------------------------------------------
    # 方案 C: OpenCV 纯图像处理回退（全局模式）
    # --------------------------------------------------

    def _check_fallback(self, image_path: str) -> QCRreport:
        """
        OpenCV 回退方案：整图全局质量检测（支持 PNG/JPG/BMP 等）
        """
        report = QCRreport(wsi_path=image_path)

        try:
            img = _imread_unicode(image_path)
            if img is None:
                report.warnings.append("无法读取图像文件")
                report.is_usable = False
                return report

            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

            tissue_mask = (gray < np.percentile(gray, 25)).astype(np.uint8) * 255
            kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
            tissue_mask = cv2.morphologyEx(tissue_mask, cv2.MORPH_CLOSE, kernel)

            tissue_pixels = np.sum(tissue_mask > 0)
            report.tissue_ratio = tissue_pixels / tissue_mask.size

            masked = gray.copy()
            masked[tissue_mask == 0] = 0
            laplacian_var = cv2.Laplacian(masked, cv2.CV_64F).var()
            report.focus_score = min(10.0, max(0.0, laplacian_var / 50.0))

            hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
            if tissue_pixels > 0:
                report.stain_score = min(10.0, max(0.0,
                    hsv[:, :, 1][tissue_mask > 0].mean() / 25.5))
            else:
                report.stain_score = 0

            report.usability_score = self._estimate_usability(
                tissue_ratio=report.tissue_ratio,
                focus_score=report.focus_score,
                stain_score=report.stain_score,
            )
            report.artifact_regions = self._detect_artifacts(gray, tissue_mask)

        except Exception as e:
            report.warnings.append(f"图像处理异常: {str(e)}")

        report.is_usable = (
            report.usability_score >= self.USABILITY_THRESHOLD and
            report.focus_score >= self.FOCUS_THRESHOLD and
            report.stain_score >= self.STAIN_THRESHOLD
        )
        return report

    # --------------------------------------------------
    # 辅助方法
    # --------------------------------------------------

    def _estimate_usability(self, tissue_ratio: float = 0.0,
                            focus_score: float = 10.0,
                            stain_score: float = 10.0) -> float:
        """
        综合 tissue_ratio、focus_score、stain_score 估算可用性分数

        @param tissue_ratio: 有效组织像素占比 (0~1)
        @param focus_score: 对焦评分 (0~10)
        @param stain_score: 染色评分 (0~10)
        @return: 可用性分数 (0~1)
        """
        tissue_norm = min(1.0, tissue_ratio / 0.3)
        focus_norm = focus_score / 10.0
        stain_norm = stain_score / 10.0
        usability = 0.3 * tissue_norm + 0.35 * focus_norm + 0.35 * stain_norm
        return round(float(usability), 4)

    def _detect_artifacts(self, gray_image: np.ndarray,
                          tissue_mask: np.ndarray) -> list:
        """
        快速检测常见伪影：大块空白、深色异物等

        @param gray_image: 灰度图像
        @param tissue_mask: 组织掩码
        @return: 伪影区域列表 [(x, y, w, h, label), ...]
        """
        artifacts = []
        inverted = cv2.bitwise_not(tissue_mask)
        contours, _ = cv2.findContours(inverted, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        img_area = tissue_mask.shape[0] * tissue_mask.shape[1]
        for cnt in contours:
            area = cv2.contourArea(cnt)
            if area > img_area * 0.05:
                x, y, w, h = cv2.boundingRect(cnt)
                artifacts.append((x, y, w, h, "large_void"))

        bright_mask = (gray_image > 240).astype(np.uint8) * 255
        bright_mask = cv2.morphologyEx(bright_mask, cv2.MORPH_OPEN,
                                        kernel=np.ones((3, 3)))
        b_contours, _ = cv2.findContours(bright_mask, cv2.RETR_EXTERNAL,
                                          cv2.CHAIN_APPROX_SIMPLE)
        for cnt in b_contours:
            area = cv2.contourArea(cnt)
            if 0.001 * img_area < area < 0.15 * img_area:
                x, y, w, h = cv2.boundingRect(cnt)
                artifacts.append((x, y, w, h, "bright_region"))
        return artifacts


# ============================================================
# 命令行入口
# ============================================================

def main():
    """
    命令行调用入口

    用法：
        # 全局模式（快速）
        python wsi_qc.py --wsi_path sample.svs

        # 分块模式（精细）
        python wsi_qc.py --wsi_path sample.png --patch_size 512

        # 分块 + 热力图
        python wsi_qc.py --wsi_path sample.png --patch_size 512 --heatmap quality.png

        # 保存 JSON 报告
        python wsi_qc.py --wsi_path sample.png --patch_size 512 --json report.json
    """
    parser = argparse.ArgumentParser(
        description="PathProfilerQC2 WSI 切片质量检测"
    )
    parser.add_argument("--wsi_path", type=str, required=True,
                        help="图像路径 (.svs/.ndpi/.tiff/.png/.jpg 等)")
    parser.add_argument("--threshold", type=float, default=0.6,
                        help="可用性判定阈值 (默认 0.6)")
    parser.add_argument("--method", type=str, default="auto",
                        choices=["auto", "lazyslide", "tiatoolbox", "opencv"],
                        help="检测引擎 (默认 auto=自动选择)")
    parser.add_argument("--patch_size", type=int, default=0,
                        help="分块模式 patch 尺寸（像素），0=全局模式 (默认)")
    parser.add_argument("--stride", type=int, default=0,
                        help="分块步长（默认=patch_size，即无重叠）")
    parser.add_argument("--heatmap", type=str, default=None,
                        help="分块模式热力图输出路径")
    parser.add_argument("--json", type=str, default=None,
                        help="输出 JSON 格式报告路径")
    args = parser.parse_args()

    if args.method == "lazyslide":
        qc = WSISlideQC(use_lazyslide=True)
    elif args.method == "tiatoolbox":
        qc = WSISlideQC(use_lazyslide=False)
    else:
        qc = WSISlideQC()

    qc.USABILITY_THRESHOLD = args.threshold

    stride = args.stride if args.stride > 0 else args.patch_size

    report = qc.check(
        args.wsi_path,
        patch_size=args.patch_size if args.patch_size > 0 else None,
        stride=stride if args.patch_size > 0 else None,
        output_heatmap=args.heatmap,
    )
    print(report)

    if args.json:
        report.save_json(args.json)
        print(f"JSON 报告已保存: {args.json}")

    return 0 if report.is_usable else 1


if __name__ == "__main__":
    exit(main())
