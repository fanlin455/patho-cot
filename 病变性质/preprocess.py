"""
@file preprocess.py
@brief 数据预处理：从YOLO标签 + 原始图像提取图特征并保存为 .pt 文件

处理流程:
  1. 扫描 原始数据+器官分类的/{organ}/{split}/labels/*.txt
  2. 对应读取 {split}/images/*.png
  3. 对每个细胞边界框裁剪patch → 提取几何+纹理特征（14维）
  4. 构建自适应距离阈值的邻接矩阵
  5. GMM 对 train 集的 lesion_ratio 聚类确定二分类边界
  6. 保存到 processed/{split}/ 目录

节点特征（14维，不含 cls_id，消除特征→标签泄漏）:
  [0~1]  中心坐标 (x, y)，归一化
  [2]    面积 w*h，归一化
  [3]    长宽比 max(w,h)/min(w,h)，裁剪到 [1,5]
  [4]    local_density: 1/(距最近5个邻居的平均距离+eps)
  [5~7]  RGB均值（patch染色深浅）
  [8~10] RGB标准差（染色质纹理粗糙度）
  [11]   GLCM对比度 / 100
  [12]   GLCM同质性
  [13]   GLCM能量（ASM）

运行方式:
  python preprocess.py
  python preprocess.py --split train   # 仅处理指定子集
"""

import os
import sys
import argparse
import glob
import json
import numpy as np
import torch
import cv2
from PIL import Image
from tqdm import tqdm
from sklearn.mixture import GaussianMixture
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm

# ============================================================
# 0. 中文字体配置（全局）
# ============================================================

def _setup_cn_font():
    """配置 matplotlib 中文字体，确保图表正常显示中文"""
    cn_fonts = ['Microsoft YaHei', 'SimHei', 'WenQuanYi Micro Hei',
                'Noto Sans CJK SC', 'Source Han Sans CN', 'sans-serif']
    for fn in cn_fonts:
        try:
            matches = [f for f in fm.findSystemFonts() if fn.lower() in f.lower()]
            if matches:
                plt.rcParams['font.sans-serif'] = [fn] + plt.rcParams['font.sans-serif']
                plt.rcParams['axes.unicode_minus'] = False
                return fn
        except Exception:
            continue
    # fallback: 尝试任意 CJK 字体
    all_fonts = [f.name for f in fm.fontManager.ttflist]
    for pat in ['YaHei', 'SimHei', 'SimSun', 'KaiTi', 'Noto Sans CJK', 'Source Han Sans']:
        found = [f for f in all_fonts if pat in f]
        if found:
            plt.rcParams['font.sans-serif'] = [found[0]] + plt.rcParams['font.sans-serif']
            plt.rcParams['axes.unicode_minus'] = False
            return found[0]
    return 'sans-serif'

CN_FONT = _setup_cn_font()
print(f"Matplotlib font: {CN_FONT}")


# ============================================================
# 0. GLCM 纹理特征（纯 numpy，无额外依赖）
# ============================================================

def _compute_glcm_features(gray_patch, distances=(1,), angles=(0,), levels=32):
    """
    灰度共生矩阵统计量

    @param gray_patch: 灰度图 (H, W)，uint8
    @param distances: 像素距离元组
    @param angles: 方向角元组，弧度
    @param levels: 灰度级数
    @return: (contrast, homogeneity, energy)
    """
    h, w = gray_patch.shape
    if h < 2 or w < 2:
        return 0.0, 1.0, 1.0

    gray = (gray_patch.astype(np.float32) / 255.0 * (levels - 1)).astype(np.int32)
    gray = np.clip(gray, 0, levels - 1)

    contrasts, homogeneities, energies = [], [], []

    for d in distances:
        for angle in angles:
            dx = int(round(d * np.cos(angle)))
            dy = int(round(d * np.sin(angle)))
            x1 = 0 if dx >= 0 else -dx
            x2 = w - dx if dx >= 0 else w
            y1 = 0 if dy >= 0 else -dy
            y2 = h - dy if dy >= 0 else h
            if x2 <= x1 or y2 <= y1:
                continue

            src = gray[y1:y2, x1:x2]
            dst = gray[y1 + dy:y2 + dy, x1 + dx:x2 + dx]
            glcm = np.zeros((levels, levels), dtype=np.float64)
            np.add.at(glcm, (src.ravel(), dst.ravel()), 1)

            total = glcm.sum()
            if total == 0:
                continue
            glcm /= total

            i_idx = np.arange(levels)
            j_idx = np.arange(levels)
            diff_sq = (i_idx[:, None] - j_idx[None, :]) ** 2

            contrasts.append(np.sum(glcm * diff_sq))
            homogeneities.append(np.sum(glcm / (1.0 + diff_sq)))
            energies.append(np.sum(glcm ** 2))

    if not contrasts:
        return 0.0, 1.0, 1.0
    return float(np.mean(contrasts)), float(np.mean(homogeneities)), float(np.mean(energies))


# ============================================================
# 1. 特征提取
# ============================================================

def extract_node_features(cls_ids, coords, sizes, img, k_neighbors=5):
    """
    提取每个细胞节点的14维特征

    @param cls_ids: 类别ID (N,)
    @param coords: 归一化中心坐标 (N, 2)
    @param sizes: 归一化宽高 (N, 2)
    @param img: RGB图像 (H, W, 3)
    @param k_neighbors: 密度计算邻居数
    @return: 特征数组 (N, 14)，float32
    """
    N = len(cls_ids)
    if N == 0:
        return np.zeros((0, 14), dtype=np.float32)

    img_h, img_w = img.shape[:2]
    features = np.zeros((N, 14), dtype=np.float32)

    # --- 几何特征 [0~4] ---
    features[:, 0] = coords[:, 0]
    features[:, 1] = coords[:, 1]
    features[:, 2] = sizes[:, 0] * sizes[:, 1]
    raw_ratio = np.maximum(sizes[:, 0], sizes[:, 1]) / (np.minimum(sizes[:, 0], sizes[:, 1]) + 1e-6)
    features[:, 3] = np.clip(raw_ratio, 1.0, 5.0)

    if N >= 2:
        diff = coords[:, np.newaxis, :] - coords[np.newaxis, :, :]
        dist = np.sqrt(np.sum(diff ** 2, axis=-1))
        np.fill_diagonal(dist, np.inf)
        k = min(k_neighbors, N - 1)
        nearest = np.sort(dist, axis=1)[:, :k]
        mean_dist = np.mean(nearest, axis=1)
        features[:, 4] = 1.0 / (mean_dist + 1e-6)
    else:
        features[:, 4] = 1e6

    # --- 纹理特征 [5~13] ---
    for i in range(N):
        cx = int(coords[i, 0] * img_w)
        cy = int(coords[i, 1] * img_h)
        pw = max(1, int(sizes[i, 0] * img_w))
        ph = max(1, int(sizes[i, 1] * img_h))

        x1 = max(0, cx - pw // 2)
        y1 = max(0, cy - ph // 2)
        x2 = min(img_w, x1 + pw)
        y2 = min(img_h, y1 + ph)

        patch = img[y1:y2, x1:x2]
        if patch.size == 0:
            continue

        patch_f = patch.astype(np.float32)
        features[i, 5:8] = patch_f.mean(axis=(0, 1)) / 255.0
        features[i, 8:11] = patch_f.std(axis=(0, 1)) / 255.0

        gray = cv2.cvtColor(patch, cv2.COLOR_RGB2GRAY)
        contrast, homogeneity, energy = _compute_glcm_features(gray)
        features[i, 11] = contrast / 100.0
        features[i, 12] = homogeneity
        features[i, 13] = energy

    features = np.nan_to_num(features, nan=0.0, posinf=0.0, neginf=0.0)
    return features.astype(np.float32)


# ============================================================
# 2. 图构建
# ============================================================

def build_adjacency(coords, k_adaptive=True, fixed_threshold=0.1):
    """
    构建对称归一化邻接矩阵 (D^-0.5 * (A+I) * D^-0.5)

    @param coords: 归一化坐标 (N, 2)，float32
    @param k_adaptive: True=自适应阈值(上三角距离30%分位数)
    @param fixed_threshold: k_adaptive=False时的固定阈值
    @return: 归一化邻接矩阵 (N, N)
    """
    N = len(coords)
    if N <= 1:
        adj_t = torch.ones((N, N), dtype=torch.float32)
        deg = torch.sum(adj_t, dim=1)
        deg_inv_sqrt = torch.pow(deg, -0.5)
        deg_inv_sqrt[torch.isinf(deg_inv_sqrt)] = 0.0
        return torch.matmul(torch.matmul(torch.diag(deg_inv_sqrt), adj_t), torch.diag(deg_inv_sqrt))

    diff = coords[:, np.newaxis, :] - coords[np.newaxis, :, :]
    dist = np.sqrt(np.sum(diff ** 2, axis=-1))

    if k_adaptive:
        upper = dist[np.triu_indices(N, k=1)]
        threshold = np.percentile(upper, 30) if len(upper) > 0 else 0.1
    else:
        threshold = fixed_threshold

    adj = (dist <= threshold).astype(np.float32)
    adj_t = torch.tensor(adj, dtype=torch.float32)
    adj_t = adj_t + torch.eye(N)
    deg = torch.sum(adj_t, dim=1)
    deg_inv_sqrt = torch.pow(deg, -0.5)
    deg_inv_sqrt[torch.isinf(deg_inv_sqrt)] = 0.0
    return torch.matmul(torch.matmul(torch.diag(deg_inv_sqrt), adj_t), torch.diag(deg_inv_sqrt))


# ============================================================
# 3. GMM 聚类确定二分类边界
# ============================================================

def _compute_lesion_ratio(cls_ids):
    """计算病灶细胞占比"""
    total = len(cls_ids)
    if total == 0:
        return 0.0
    return float(np.sum(cls_ids == 0)) / total


def fit_gmm_boundary(data_dir, output_dir):
    """
    对 train 集的 lesion_ratio 分布用 GMM 聚类，找到 Normal/Abnormal 的分界点

    原理:
      - 正常组织和恶性肿瘤在病灶细胞占比上应当呈现双峰分布
      - GMM 拟合两个高斯分量，取等概率点作为分类阈值
      - 低 ratio 分量为"正常"，高 ratio 分量为"异常"

    @param data_dir: 原始数据目录
    @param output_dir: 输出目录（用于保存可视化结果）
    @return: (threshold, means, variances, weights) 阈值及GMM参数
    """
    print("\n" + "=" * 60)
    print("GMM clustering on lesion_ratio (train set)")
    print("=" * 60)

    ratios = []
    for organ_dir in sorted(os.listdir(data_dir)):
        labels_dir = os.path.join(data_dir, organ_dir, "train", "labels")
        if not os.path.isdir(labels_dir):
            continue
        for txt_file in glob.glob(os.path.join(labels_dir, "*.txt")):
            try:
                data = np.loadtxt(txt_file, ndmin=2)
                if data.size == 0:
                    continue
                cls_ids = data[:, 0].astype(np.int32)
                ratios.append(_compute_lesion_ratio(cls_ids))
            except Exception:
                continue

    ratios = np.array(ratios).reshape(-1, 1)
    print(f"Total train samples for GMM: {len(ratios)}")
    print(f"Ratio range: [{ratios.min():.4f}, {ratios.max():.4f}]")
    print(f"Ratio mean: {ratios.mean():.4f}, std: {ratios.std():.4f}")

    # 拟合 GMM（2 分量）
    gmm = GaussianMixture(n_components=2, random_state=42, n_init=10)
    gmm.fit(ratios)
    means = gmm.means_.ravel()
    weights = gmm.weights_

    # 确保 mean[0] < mean[1]（低分量 = Normal）
    if means[0] > means[1]:
        means = means[::-1]
        weights = weights[::-1]
        gmm.means_ = gmm.means_[::-1]
        gmm.weights_ = gmm.weights_[::-1]

    variances = gmm.covariances_.ravel()

    # 求解等概率边界：在高斯分量的交点上
    from numpy.linalg import det
    x_range = np.linspace(max(0.0, ratios.min() - 0.05), min(1.0, ratios.max() + 0.05), 10000).reshape(-1, 1)
    log_prob = gmm.score_samples(x_range)
    prob = np.exp(log_prob)

    # 每个分量的后验概率
    resp = gmm.predict_proba(x_range)
    diff = np.abs(resp[:, 0] - resp[:, 1])
    boundary_idx = np.argmin(diff)
    threshold = float(x_range[boundary_idx, 0])

    print(f"GMM means:     {means}")
    print(f"GMM variances: {variances}")
    print(f"GMM weights:   {weights}")
    print(f"Boundary (Normal/Abnormal): ratio = {threshold:.4f}")

    # ---- 可视化 GMM 聚类 ----
    fig, axes = plt.subplots(1, 2, figsize=(14, 5))

    # 左图：直方图 + GMM 分量
    ax = axes[0]
    ax.hist(ratios.ravel(), bins=60, density=True, alpha=0.5, color='#94a3b8',
            edgecolor='white', label='lesion_ratio 分布')
    # 分别绘制两个高斯分量
    x_plot = np.linspace(0, 1, 500).reshape(-1, 1)
    for i in range(2):
        from scipy.stats import norm
        y_i = weights[i] * norm.pdf(x_plot.ravel(), means[i], np.sqrt(variances[i]))
        label = '正常分量' if i == 0 else '异常分量'
        ax.plot(x_plot, y_i, linewidth=2,
                color=['#22c55e', '#ef4444'][i], label=label)
    ax.axvline(threshold, color='black', linestyle='--', linewidth=2,
               label=f'GMM 分界 = {threshold:.3f}')
    ax.set_xlabel('病灶细胞占比 (lesion_ratio)')
    ax.set_ylabel('概率密度')
    ax.set_title('GMM 双分量聚类 - lesion_ratio 分布')
    ax.legend(fontsize=9)

    # 右图：每个样本的后验概率
    ax = axes[1]
    sorted_idx = np.argsort(ratios.ravel())
    sorted_ratios = ratios.ravel()[sorted_idx]
    sorted_resp = gmm.predict_proba(ratios)[sorted_idx]
    ax.fill_between(sorted_ratios, 0, sorted_resp[:, 0], alpha=0.6,
                     color='#22c55e', label='属于"正常"的概率')
    ax.fill_between(sorted_ratios, sorted_resp[:, 0], 1, alpha=0.6,
                     color='#ef4444', label='属于"异常"的概率')
    ax.axvline(threshold, color='black', linestyle='--', linewidth=2)
    ax.set_xlabel('病灶细胞占比 (lesion_ratio)')
    ax.set_ylabel('后验概率')
    ax.set_title('GMM 分类置信度（按 ratio 排序）')
    ax.legend(fontsize=9)

    fig.tight_layout()
    vis_path = os.path.join(output_dir, "gmm_boundary_analysis.png")
    plt.savefig(vis_path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"GMM visualization saved to: {vis_path}")

    # 保存 GMM 参数供参考
    gmm_info = {
        "threshold": threshold,
        "means": means.tolist(),
        "variances": variances.tolist(),
        "weights": weights.tolist(),
    }
    with open(os.path.join(output_dir, "gmm_boundary.json"), "w", encoding="utf-8") as f:
        json.dump(gmm_info, f, indent=2, ensure_ascii=False)

    return threshold


# ============================================================
# 4. 标签生成（二分类，基于 GMM 边界）
# ============================================================

def ratio_to_label_binary(cls_ids, threshold):
    """
    根据病灶细胞占比和 GMM 阈值生成二分类标签

    @param cls_ids: class_id 数组（0=lesion, 1=non_lesion）
    @param threshold: GMM 聚类确定的边界
    @return: 0=Normal, 1=Abnormal
    """
    ratio = _compute_lesion_ratio(cls_ids)
    return 1 if ratio >= threshold else 0


# ============================================================
# 5. 主流程
# ============================================================

def preprocess_data(data_dir, output_dir, threshold, splits=None):
    """
    遍历数据目录，提取图特征并保存

    @param data_dir: 原始数据目录（含各器官子目录）
    @param output_dir: 输出目录（processed/）
    @param threshold: GMM 分类阈值
    @param splits: 要处理的子集列表，默认全部
    """
    if splits is None:
        splits = ["train", "val", "test"]

    for split in splits:
        split_dir = os.path.join(output_dir, split)
        os.makedirs(split_dir, exist_ok=True)

    total_processed = 0
    class_counts = {0: 0, 1: 0}

    for split in splits:
        print(f"\n{'='*60}")
        print(f"Processing: {split}")
        print(f"{'='*60}")

        all_files = []
        for organ_dir in sorted(os.listdir(data_dir)):
            labels_dir = os.path.join(data_dir, organ_dir, split, "labels")
            if not os.path.isdir(labels_dir):
                continue
            txt_files = sorted(glob.glob(os.path.join(labels_dir, "*.txt")))
            all_files.extend(txt_files)

        print(f"Found {len(all_files)} label files for {split}")

        for label_path in tqdm(all_files, desc=f"  {split}"):
            try:
                base_name = os.path.splitext(os.path.basename(label_path))[0]
                img_dir = os.path.join(os.path.dirname(os.path.dirname(label_path)), "images")
                img_path = None
                for ext in (".png", ".jpg", ".jpeg", ".PNG", ".JPG"):
                    candidate = os.path.join(img_dir, base_name + ext)
                    if os.path.exists(candidate):
                        img_path = candidate
                        break
                if img_path is None:
                    continue

                try:
                    data = np.loadtxt(label_path, ndmin=2)
                    if data.size == 0:
                        data = np.zeros((0, 5))
                except Exception:
                    data = np.zeros((0, 5))

                if len(data) == 0:
                    node_features = np.zeros((1, 14), dtype=np.float32)
                    adj = torch.ones((1, 1), dtype=torch.float32)
                    label = 0
                    coords = np.zeros((1, 2), dtype=np.float32)
                else:
                    cls_ids = data[:, 0].astype(np.int32)
                    coords = data[:, 1:3].astype(np.float32)
                    sizes = data[:, 3:5].astype(np.float32)
                    label = ratio_to_label_binary(cls_ids, threshold)

                    img = np.array(Image.open(img_path).convert("RGB"))
                    node_features = extract_node_features(cls_ids, coords, sizes, img)
                    adj = build_adjacency(coords)

                out_name = base_name + ".pt"
                out_path = os.path.join(output_dir, split, out_name)
                torch.save({
                    "x": torch.tensor(node_features),
                    "adj": adj,
                    "label": label,
                    "coords": torch.tensor(coords),
                }, out_path)

                total_processed += 1
                class_counts[label] += 1

            except Exception as e:
                print(f"  [!] Error processing {label_path}: {e}")
                continue

    print(f"\n{'='*60}")
    print(f"Preprocessing complete!")
    print(f"Total processed: {total_processed}")
    print(f"Class distribution: Normal={class_counts[0]}, Abnormal={class_counts[1]}")
    print(f"GMM boundary: {threshold:.4f}")
    print(f"Output: {output_dir}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Pathology graph data preprocessing")
    parser.add_argument("--split", type=str, default=None,
                        help="Process specific split only (train/val/test)")
    args = parser.parse_args()

    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    data_dir = os.path.join(base_dir, "器官分类数据集")
    output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "processed")

    # Step 1: GMM 聚类确定边界（仅使用 train 集）
    threshold = fit_gmm_boundary(data_dir, output_dir)

    # Step 2: 用 GMM 边界生成标签并处理数据
    splits = [args.split] if args.split else ["train", "val", "test"]
    preprocess_data(data_dir, output_dir, threshold, splits)
