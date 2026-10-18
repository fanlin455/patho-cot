"""
@file visualize.py
@brief GCN 图结构可视化脚本（v1 二分类）

功能:
  1. 加载预处理后的图数据 + 原图
  2. 用 NetworkX 绘制细胞节点和空间关系
  3. 运行 GCN 推理，展示预测结果
  4. 中文字体支持

运行方式:
  python visualize.py
  python visualize.py --index 0
"""

import os
import sys
import glob
import argparse
import numpy as np
import torch
import torch.nn.functional as F
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import networkx as nx
from PIL import Image

from model import PathlogyGCN, NATURE_CLASSES, NATURE_CN


# ============================================================
# 0. 中文字体配置
# ============================================================

def _setup_cn_font():
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
    all_fonts = [f.name for f in fm.fontManager.ttflist]
    for pat in ['YaHei', 'SimHei', 'SimSun', 'KaiTi', 'Noto Sans CJK', 'Source Han Sans']:
        found = [f for f in all_fonts if pat in f]
        if found:
            plt.rcParams['font.sans-serif'] = [found[0]] + plt.rcParams['font.sans-serif']
            plt.rcParams['axes.unicode_minus'] = False
            return found[0]
    return 'sans-serif'

_ = _setup_cn_font()


def find_image_for_pt(pt_path):
    """
    根据 pt 文件路径反查原始图像

    @param pt_path: processed/xxx.pt 文件路径
    @return: 图像路径或None
    """
    base_name = os.path.splitext(os.path.basename(pt_path))[0]
    data_root = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                             "器官分类数据集")
    for organ in os.listdir(data_root):
        for split in ("train", "val", "test"):
            for ext in (".png", ".jpg", ".jpeg"):
                candidate = os.path.join(data_root, organ, split, "images", base_name + ext)
                if os.path.exists(candidate):
                    return candidate
    return None


def visualize_sample(pt_path, img_path=None, model=None, device="cpu", output_path=None):
    """
    可视化单个图样本

    @param pt_path: .pt 文件路径
    @param img_path: 原始图像路径
    @param model: GCN模型
    @param device: torch device
    @param output_path: 输出图片路径
    """
    data = torch.load(pt_path, map_location="cpu", weights_only=False)
    x = data["x"].numpy()
    adj = data["adj"].numpy()
    label = data["label"]
    if not isinstance(label, int):
        label = int(label.item())
    coords = data["coords"].numpy()

    N = len(x)
    if N == 0:
        print("Empty graph, skip visualization")
        return

    if img_path is None:
        img_path = find_image_for_pt(pt_path)

    # 构建 NetworkX 图
    G = nx.Graph()
    pos = {}
    colors = []

    for i in range(N):
        G.add_node(i)
        pos[i] = (coords[i, 0], coords[i, 1])
        contrast = x[i, 11] * 100 if N > 0 and x.shape[1] > 11 else 0.5
        colors.append(plt.cm.RdYlGn_r(min(contrast / 50.0, 1.0)))

    for i in range(N):
        for j in range(i + 1, N):
            if adj[i, j] > 0:
                G.add_edge(i, j)

    cn_labels = [NATURE_CN.get(c, c) for c in NATURE_CLASSES]

    # GCN 预测
    pred_text = ""
    true_text = f"真实: {cn_labels[label]} ({NATURE_CLASSES[label]})"
    if model is not None:
        model.eval()
        with torch.no_grad():
            x_t = torch.tensor(x, dtype=torch.float32).to(device)
            adj_t = torch.tensor(adj, dtype=torch.float32).to(device)
            out = model([x_t], [adj_t])
            probs = F.softmax(out[0], dim=0).cpu().numpy()
            pred_idx = int(np.argmax(probs))
            pred_text = f"预测: {cn_labels[pred_idx]} ({NATURE_CLASSES[pred_idx]}, {probs[pred_idx]:.1%})"

    # 绘制
    fig, ax = plt.subplots(1, 1, figsize=(10, 10))

    if img_path and os.path.exists(img_path):
        img = Image.open(img_path).convert("RGB")
        w, h = img.size
        ax.imshow(img)
        pixel_pos = {i: (coords[i, 0] * w, coords[i, 1] * h) for i in range(N)}
    else:
        pixel_pos = pos

    nx.draw_networkx_nodes(G, pixel_pos, node_color=colors,
                           node_size=60, ax=ax, alpha=0.85, edgecolors='white',
                           linewidths=0.5)
    nx.draw_networkx_edges(G, pixel_pos, edge_color='cyan',
                           width=1.0, ax=ax, alpha=0.4)

    title = "GCN 病理图结构"
    if pred_text:
        title += f"\n{pred_text}  |  {true_text}"
    else:
        title += f"\n{true_text}"
    plt.title(title, fontsize=14)
    plt.axis('off')

    if output_path is None:
        output_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   "gcn_graph_visualization.png")

    plt.tight_layout()
    plt.savefig(output_path, bbox_inches='tight', dpi=150)
    plt.close()
    print(f"可视化已保存: {output_path}")


def main():
    parser = argparse.ArgumentParser(description="GCN graph visualization")
    parser.add_argument("--index", type=int, default=0, help="样本索引")
    parser.add_argument("--output", type=str, default=None, help="输出图片路径")
    args = parser.parse_args()

    device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")

    current_dir = os.path.dirname(os.path.abspath(__file__))
    processed_dir = os.path.join(current_dir, "processed", "test")
    if not os.path.isdir(processed_dir):
        processed_dir = os.path.join(current_dir, "processed", "train")
    if not os.path.isdir(processed_dir):
        print("ERROR: No processed data found. Run preprocess.py first!")
        return

    files = sorted(glob.glob(os.path.join(processed_dir, "*.pt")))
    if not files:
        print("ERROR: No .pt files found.")
        return

    idx = min(args.index, len(files) - 1)
    pt_path = files[idx]
    print(f"可视化样本 {idx}: {os.path.basename(pt_path)}")

    model_path = os.path.join(current_dir, "gcn_nature_model.pth")
    model = None
    if os.path.exists(model_path):
        model = PathlogyGCN(node_features=14, hidden_dim=128, num_classes=2).to(device)
        model.load_state_dict(torch.load(model_path, map_location=device, weights_only=False))
        print("已加载模型用于预测。")

    visualize_sample(pt_path, model=model, device=device, output_path=args.output)


if __name__ == "__main__":
    main()
