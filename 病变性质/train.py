"""
@file train.py
@brief GCN 模型训练脚本（v1 二分类）

训练流程:
  1. 加载 processed/ 目录下预处理的图数据
  2. 从 train 划分 20% 作为验证集（分层采样）
  3. 构建 DataLoader + 训练循环
  4. 早停 + Cosine LR 调度
  5. 丰富可视化：Loss/Acc曲线、AUC-ROC、混淆矩阵、LR调度

运行方式:
  python train.py
  python train.py --epochs 100 --lr 0.001 --batch_size 32
"""

import os
import sys
import argparse
import glob
import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import Dataset, DataLoader
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
from sklearn.model_selection import train_test_split
from sklearn.metrics import roc_curve, auc, confusion_matrix
from tqdm import tqdm

# 导入共享模型
from model import PathlogyGCN, NATURE_CLASSES, NATURE_CN


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

# 类别名称（含中文）
CN_LABELS = [NATURE_CN.get(c, c) for c in NATURE_CLASSES]


# ============================================================
# 1. Dataset
# ============================================================

class GraphDataset(Dataset):
    """
    加载预处理后的图数据 (.pt 文件)

    每个 .pt 包含: {x, adj, label, coords}
    """

    def __init__(self, file_paths):
        """
        @param file_paths: .pt 文件路径列表
        """
        self.file_paths = file_paths
        self._labels = []
        for fp in file_paths:
            data = torch.load(fp, map_location="cpu", weights_only=False)
            self._labels.append(data["label"] if isinstance(data["label"], int)
                                else int(data["label"].item()))

    def __len__(self):
        return len(self.file_paths)

    def __getitem__(self, idx):
        data = torch.load(self.file_paths[idx], map_location="cpu", weights_only=False)
        x = data["x"].float()
        adj = data["adj"].float()
        label = data["label"]
        if not isinstance(label, int):
            label = int(label.item())
        return x, adj, label

    @property
    def labels(self):
        return self._labels


def graph_collate_fn(batch):
    """
    图批量整理：每张图节点数不同，返回list

    @param batch: (x, adj, label) 元组列表
    @return: (xs_list, adjs_list, labels_tensor)
    """
    xs, adjs, labels = zip(*batch)
    labels = torch.tensor(labels, dtype=torch.long)
    return list(xs), list(adjs), labels


# ============================================================
# 2. 训练函数
# ============================================================

def train_model(train_loader, val_loader, model, device,
                epochs=100, lr=0.001, patience=15, class_weights=None):
    """
    GCN 训练主循环（含二分类 AUC-ROC）

    @param train_loader: 训练数据加载器
    @param val_loader: 验证数据加载器
    @param model: PathlogyGCN 模型实例
    @param device: torch device
    @param epochs: 最大训练轮数
    @param lr: 初始学习率
    @param patience: 早停耐心值
    @param class_weights: 类别权重tensor（处理不平衡）
    @return: (best_val_acc, history_dict)
        history_dict = {train_loss, train_acc, val_loss, val_acc, val_auc, lrs}
    """
    optimizer = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=1e-4)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=epochs)

    if class_weights is not None:
        class_weights = class_weights.to(device)
    criterion = nn.CrossEntropyLoss(weight=class_weights)

    best_val_acc = 0.0
    patience_counter = 0
    best_model_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   "gcn_nature_model.pth")

    history = {
        "train_loss": [], "train_acc": [],
        "val_loss": [], "val_acc": [], "val_auc": [], "lrs": []
    }

    for epoch in range(epochs):
        # ---- 训练 ----
        model.train()
        running_loss = 0.0
        train_correct = 0
        train_total = 0

        pbar = tqdm(train_loader, desc=f"Epoch {epoch+1}/{epochs}", leave=False)
        for xs, adjs, labels in pbar:
            xs = [x.to(device) for x in xs]
            adjs = [adj.to(device) for adj in adjs]
            labels = labels.to(device)

            optimizer.zero_grad()
            outputs = model(xs, adjs)
            loss = criterion(outputs, labels)
            loss.backward()
            optimizer.step()

            running_loss += loss.item()
            _, predicted = torch.max(outputs, 1)
            train_total += labels.size(0)
            train_correct += (predicted == labels).sum().item()

            pbar.set_postfix({"loss": f"{loss.item():.4f}"})

        train_loss = running_loss / len(train_loader)
        train_acc = train_correct / train_total if train_total > 0 else 0
        history["train_loss"].append(train_loss)
        history["train_acc"].append(train_acc)

        scheduler.step()
        history["lrs"].append(scheduler.get_last_lr()[0])

        # ---- 验证 ----
        model.eval()
        val_loss = 0.0
        val_correct = 0
        val_total = 0
        all_val_probs = []
        all_val_labels = []

        with torch.no_grad():
            for xs, adjs, labels in val_loader:
                xs = [x.to(device) for x in xs]
                adjs = [adj.to(device) for adj in adjs]
                labels = labels.to(device)
                outputs = model(xs, adjs)
                loss = criterion(outputs, labels)
                val_loss += loss.item()

                probs = F.softmax(outputs, dim=1)
                _, predicted = torch.max(outputs, 1)
                val_total += labels.size(0)
                val_correct += (predicted == labels).sum().item()
                all_val_probs.extend(probs[:, 1].cpu().numpy())
                all_val_labels.extend(labels.cpu().numpy())

        val_loss /= len(val_loader)
        val_acc = val_correct / val_total if val_total > 0 else 0

        # AUC-ROC（二分类才有意义）
        all_val_probs = np.array(all_val_probs)
        all_val_labels = np.array(all_val_labels)
        if len(np.unique(all_val_labels)) > 1:
            fpr, tpr, _ = roc_curve(all_val_labels, all_val_probs)
            val_auc = auc(fpr, tpr)
        else:
            val_auc = 0.0

        history["val_loss"].append(val_loss)
        history["val_acc"].append(val_acc)
        history["val_auc"].append(val_auc)

        print(f"Epoch [{epoch+1:3d}/{epochs}] "
              f"Loss: {train_loss:.4f}  Acc: {train_acc:.4f}  "
              f"ValLoss: {val_loss:.4f}  ValAcc: {val_acc:.4f}  "
              f"AUC: {val_auc:.4f}  LR: {optimizer.param_groups[0]['lr']:.6f}")

        # 早停
        if val_acc > best_val_acc:
            best_val_acc = val_acc
            patience_counter = 0
            torch.save(model.state_dict(), best_model_path)
            print(f"  --> Best model saved (ValAcc: {val_acc:.4f}, AUC: {val_auc:.4f})")
        else:
            patience_counter += 1
            if patience_counter >= patience:
                print(f"Early stopping at epoch {epoch+1}")
                break

    return best_val_acc, history


# ============================================================
# 3. 丰富可视化
# ============================================================

def plot_training_curves(history, output_dir, class_dist=None):
    """
    绘制训练过程综合图表（4个子图）

    @param history: 训练历史字典
    @param output_dir: 输出目录
    @param class_dist: 类别分布 {0: count, 1: count}
    """
    epochs = range(1, len(history["train_loss"]) + 1)

    fig, axes = plt.subplots(2, 3, figsize=(18, 10))

    # 1) Loss 曲线
    ax = axes[0, 0]
    ax.plot(epochs, history["train_loss"], '#2563eb', marker='o', markersize=3, label='Train Loss')
    ax.plot(epochs, history["val_loss"], '#ef4444', marker='s', markersize=3, label='Val Loss')
    ax.set_xlabel('Epoch')
    ax.set_ylabel('Loss')
    ax.set_title('Loss 曲线')
    ax.legend()
    ax.grid(True, alpha=0.3)

    # 2) Accuracy 曲线
    ax = axes[0, 1]
    ax.plot(epochs, history["train_acc"], '#2563eb', marker='o', markersize=3, label='Train Acc')
    ax.plot(epochs, history["val_acc"], '#ef4444', marker='s', markersize=3, label='Val Acc')
    ax.set_xlabel('Epoch')
    ax.set_ylabel('Accuracy')
    ax.set_title('准确率曲线')
    ax.legend()
    ax.grid(True, alpha=0.3)
    ax.set_ylim(0, 1.05)

    # 3) AUC-ROC 曲线
    ax = axes[0, 2]
    ax.plot(epochs, history["val_auc"], '#8b5cf6', marker='d', markersize=3)
    ax.set_xlabel('Epoch')
    ax.set_ylabel('AUC')
    ax.set_title('验证集 AUC-ROC')
    ax.grid(True, alpha=0.3)
    ax.set_ylim(0, 1.05)

    # 4) Learning Rate 调度
    ax = axes[1, 0]
    ax.plot(epochs, history["lrs"], '#f59e0b', marker='.', markersize=2)
    ax.set_xlabel('Epoch')
    ax.set_ylabel('Learning Rate')
    ax.set_title('LR 调度 (Cosine)')
    ax.grid(True, alpha=0.3)

    # 5) Loss + ValAcc 双轴图
    ax = axes[1, 1]
    color1 = '#2563eb'
    ax.plot(epochs, history["train_loss"], color1, marker='o', markersize=3, label='Train Loss')
    ax.set_xlabel('Epoch')
    ax.set_ylabel('Loss', color=color1)
    ax.tick_params(axis='y', labelcolor=color1)
    ax2 = ax.twinx()
    color2 = '#ef4444'
    ax2.plot(epochs, history["val_acc"], color2, marker='s', markersize=3, label='Val Acc')
    ax2.set_ylabel('Val Accuracy', color=color2)
    ax2.tick_params(axis='y', labelcolor=color2)
    ax2.set_ylim(0, 1.05)
    ax.set_title('Loss & ValAcc 双轴图')
    ax.grid(True, alpha=0.3)

    # 6) 类别分布 饼图
    ax = axes[1, 2]
    if class_dist:
        labels = [CN_LABELS[i] for i in sorted(class_dist.keys())]
        sizes = [class_dist[i] for i in sorted(class_dist.keys())]
        colors = ['#22c55e', '#ef4444']
        wedges, texts, autotexts = ax.pie(sizes, labels=labels, autopct='%1.1f%%',
                                           colors=colors, startangle=90,
                                           textprops={'fontsize': 10})
        for autotext in autotexts:
            autotext.set_color('white')
            autotext.set_fontweight('bold')
    ax.set_title('训练集类别分布')

    fig.suptitle(f'GCN 二分类训练报告 (best ValAcc={max(history["val_acc"]):.2%})',
                 fontsize=14, fontweight='bold')
    fig.tight_layout(rect=[0, 0, 1, 0.96])
    plt.savefig(os.path.join(output_dir, "gcn_training_report.png"), dpi=150,
                bbox_inches='tight')
    plt.close()
    print(f"Training report saved to: {output_dir}/gcn_training_report.png")


# ============================================================
# 4. 主函数
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="GCN Training for Pathology Nature")
    parser.add_argument("--epochs", type=int, default=100, help="最大训练轮数")
    parser.add_argument("--lr", type=float, default=0.001, help="初始学习率")
    parser.add_argument("--batch_size", type=int, default=32, help="批量大小")
    parser.add_argument("--patience", type=int, default=15, help="早停耐心值")
    parser.add_argument("--hidden_dim", type=int, default=128, help="隐藏层维度")
    parser.add_argument("--dropout", type=float, default=0.3, help="Dropout概率")
    parser.add_argument("--class_weight", action="store_true",
                        help="启用类别权重（处理不平衡）")
    args = parser.parse_args()

    device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
    print(f"Device: {device}")

    current_dir = os.path.dirname(os.path.abspath(__file__))
    processed_dir = os.path.join(current_dir, "processed")

    if not os.path.isdir(processed_dir):
        print(f"ERROR: {processed_dir} not found. Run preprocess.py first!")
        sys.exit(1)

    # 加载训练数据
    train_files = sorted(glob.glob(os.path.join(processed_dir, "train", "*.pt")))
    if not train_files:
        print(f"ERROR: No .pt files found in {processed_dir}/train/")
        sys.exit(1)

    full_dataset = GraphDataset(train_files)
    labels_arr = np.array(full_dataset.labels)

    unique, counts = np.unique(labels_arr, return_counts=True)
    class_dist = dict(zip(unique.tolist(), counts.tolist()))
    print(f"Total train samples: {len(full_dataset)}")
    print(f"Class distribution: {class_dist}")

    # 类别权重
    class_weights = None
    if args.class_weight:
        weight_0 = len(full_dataset) / (2 * counts[0])
        weight_1 = len(full_dataset) / (2 * counts[1])
        class_weights = torch.tensor([weight_0, weight_1], dtype=torch.float32)
        print(f"Class weights: Normal={weight_0:.3f}, Abnormal={weight_1:.3f}")

    # 80/20 分层划分
    indices = np.arange(len(full_dataset))
    train_idx, val_idx = train_test_split(
        indices, test_size=0.2, stratify=labels_arr, random_state=42
    )

    train_dataset = torch.utils.data.Subset(full_dataset, train_idx)
    val_dataset = torch.utils.data.Subset(full_dataset, val_idx)

    print(f"Train: {len(train_dataset)}, Val: {len(val_dataset)} (stratified)")

    train_loader = DataLoader(train_dataset, batch_size=args.batch_size, shuffle=True,
                              collate_fn=graph_collate_fn, num_workers=0)
    val_loader = DataLoader(val_dataset, batch_size=args.batch_size, shuffle=False,
                            collate_fn=graph_collate_fn, num_workers=0)

    # 构建模型
    model = PathlogyGCN(
        node_features=14,
        hidden_dim=args.hidden_dim,
        num_classes=2,
        dropout=args.dropout
    ).to(device)

    total_params = sum(p.numel() for p in model.parameters())
    print(f"Model parameters: {total_params:,}")

    # 训练
    best_val_acc, history = train_model(
        train_loader, val_loader, model, device,
        epochs=args.epochs, lr=args.lr, patience=args.patience,
        class_weights=class_weights
    )

    # 丰富可视化
    plot_training_curves(history, current_dir, class_dist=class_dist)

    print(f"\nTraining finished! Best ValAcc: {best_val_acc:.4f}")
    print(f"Model saved to: {current_dir}/gcn_nature_model.pth")


if __name__ == "__main__":
    main()
