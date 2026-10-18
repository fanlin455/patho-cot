"""
@file evaluate.py
@brief GCN 模型评估脚本（v1 二分类）

评估内容:
  1. 混淆矩阵 + classification_report
  2. AUC-ROC 曲线
  3. Per-class Precision/Recall/F1
  4. 预测概率分布直方图

运行方式:
  python evaluate.py
"""

import os
import sys
import glob
import numpy as np
import torch
import torch.nn.functional as F
from torch.utils.data import DataLoader
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import seaborn as sns
from sklearn.metrics import (confusion_matrix, classification_report,
                              roc_curve, auc, precision_recall_curve)

from model import PathlogyGCN, NATURE_CLASSES, NATURE_CN
from train import GraphDataset, graph_collate_fn


# ============================================================
# 0. 中文字体配置
# ============================================================

def _setup_cn_font():
    """配置 matplotlib 中文字体"""
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

CN_FONT = _setup_cn_font()
print(f"Matplotlib font: {CN_FONT}")


def evaluate():
    """
    评估 GCN 二分类模型在测试集上的性能
    """
    device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
    print(f"Evaluating on {device}...")

    current_dir = os.path.dirname(os.path.abspath(__file__))
    processed_dir = os.path.join(current_dir, "processed", "test")
    model_path = os.path.join(current_dir, "gcn_nature_model.pth")

    if not os.path.isdir(processed_dir):
        print(f"ERROR: {processed_dir} not found. Run preprocess.py first!")
        return
    if not os.path.exists(model_path):
        print(f"ERROR: {model_path} not found. Run train.py first!")
        return

    # 1. 加载测试数据
    test_files = sorted(glob.glob(os.path.join(processed_dir, "*.pt")))
    if not test_files:
        print(f"ERROR: No .pt files in {processed_dir}")
        return

    test_dataset = GraphDataset(test_files)
    print(f"Test samples: {len(test_dataset)}")

    labels_arr = np.array(test_dataset.labels)
    unique, counts = np.unique(labels_arr, return_counts=True)
    class_dist = dict(zip(unique.tolist(), counts.tolist()))
    print(f"Class distribution: {class_dist}")

    test_loader = DataLoader(test_dataset, batch_size=32, shuffle=False,
                             collate_fn=graph_collate_fn, num_workers=0)

    # 2. 加载模型
    model = PathlogyGCN(node_features=14, hidden_dim=128, num_classes=2).to(device)
    model.load_state_dict(torch.load(model_path, map_location=device, weights_only=False))
    model.eval()
    print("Model loaded.")

    # 3. 推理
    all_preds, all_labels, all_probs_abnormal = [], [], []
    with torch.no_grad():
        for xs, adjs, labels in test_loader:
            xs = [x.to(device) for x in xs]
            adjs = [adj.to(device) for adj in adjs]
            outputs = model(xs, adjs)
            probs = F.softmax(outputs, dim=1)
            _, predicted = torch.max(outputs, 1)
            all_preds.extend(predicted.cpu().numpy())
            all_labels.extend(labels.numpy())
            all_probs_abnormal.extend(probs[:, 1].cpu().numpy())

    all_preds = np.array(all_preds)
    all_labels = np.array(all_labels)
    all_probs_abnormal = np.array(all_probs_abnormal)

    # 4. 文本报告
    cn_labels = [NATURE_CN.get(c, c) for c in NATURE_CLASSES]
    print("\n" + "=" * 60)
    print("GCN 二分类模型 - 测试集评估报告")
    print("=" * 60)
    print(classification_report(all_labels, all_preds,
                                target_names=cn_labels, digits=4))

    # 5. 综合可视化（2x2 子图）
    fig, axes = plt.subplots(2, 2, figsize=(14, 12))

    # 5a) 混淆矩阵
    cm = confusion_matrix(all_labels, all_preds)
    sns.heatmap(cm, annot=True, fmt='d', cmap='Blues',
                xticklabels=cn_labels, yticklabels=cn_labels,
                annot_kws={"fontsize": 16}, ax=axes[0, 0])
    axes[0, 0].set_title('混淆矩阵', fontsize=13)
    axes[0, 0].set_ylabel('真实标签')
    axes[0, 0].set_xlabel('预测标签')

    # 5b) AUC-ROC 曲线
    if len(np.unique(all_labels)) > 1:
        fpr, tpr, _ = roc_curve(all_labels, all_probs_abnormal)
        roc_auc = auc(fpr, tpr)
        axes[0, 1].plot(fpr, tpr, color='#2563eb', linewidth=2,
                        label=f'AUC = {roc_auc:.4f}')
        axes[0, 1].plot([0, 1], [0, 1], 'k--', alpha=0.3)
        axes[0, 1].set_xlim([0.0, 1.0])
        axes[0, 1].set_ylim([0.0, 1.05])
        axes[0, 1].set_xlabel('False Positive Rate')
        axes[0, 1].set_ylabel('True Positive Rate')
        axes[0, 1].set_title(f'ROC 曲线 (AUC={roc_auc:.4f})')
        axes[0, 1].legend(loc='lower right')
        axes[0, 1].grid(True, alpha=0.3)

    # 5c) 预测概率分布
    normal_mask = all_labels == 0
    abnormal_mask = all_labels == 1
    axes[1, 0].hist(all_probs_abnormal[normal_mask], bins=30, alpha=0.6,
                    color='#22c55e', label=f'{cn_labels[0]} (真实)', density=True)
    axes[1, 0].hist(all_probs_abnormal[abnormal_mask], bins=30, alpha=0.6,
                    color='#ef4444', label=f'{cn_labels[1]} (真实)', density=True)
    axes[1, 0].set_xlabel('预测为"异常"的概率')
    axes[1, 0].set_ylabel('密度')
    axes[1, 0].set_title('预测概率分布')
    axes[1, 0].legend()
    axes[1, 0].grid(True, alpha=0.3)

    # 5d) 类别分布 + 指标汇总
    ax = axes[1, 1]
    ax.axis('off')

    # 计算详细指标
    from sklearn.metrics import precision_recall_fscore_support
    p, r, f1, s = precision_recall_fscore_support(all_labels, all_preds, zero_division=0)
    overall_acc = (all_preds == all_labels).mean()

    summary_lines = [
        f"Overall Accuracy: {overall_acc:.2%}",
        f"AUC: {roc_auc:.4f}" if 'roc_auc' in locals() else "",
        f"Total Test Samples: {len(all_labels)}",
        "",
        "Per-Class Metrics:",
    ]
    for i, name in enumerate(cn_labels):
        summary_lines.append(
            f"  {name:6s}  P={p[i]:.3f}  R={r[i]:.3f}  F1={f1[i]:.3f}  N={s[i]}"
        )

    summary_text = "\n".join([l for l in summary_lines if l])
    ax.text(0.5, 0.5, summary_text, transform=ax.transAxes,
            fontsize=11, verticalalignment='center', horizontalalignment='center',
            fontfamily='sans-serif',
            bbox=dict(boxstyle='round', facecolor='#f8fafc', alpha=0.9, edgecolor='#cbd5e1'))

    fig.suptitle('GCN 二分类模型 - 测试集综合评估', fontsize=15, fontweight='bold')
    fig.tight_layout(rect=[0, 0, 1, 0.95])

    cm_path = os.path.join(current_dir, "gcn_evaluation_report.png")
    plt.savefig(cm_path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"\nEvaluation report saved to: {cm_path}")


if __name__ == "__main__":
    evaluate()
