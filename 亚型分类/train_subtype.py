"""
@file train_subtype.py
@brief MobileNetV3-Large 组织亚型分类模型训练脚本（v2 完整版）

功能:
  1. 从 NCT-CRC-HE-100K 加载 9 类组织亚型数据
  2. 完整训练（非 demo）+ 验证
  3. 训练后自动在 test 集（20% val 划分）评估
  4. 输出：混淆矩阵、Per-class Accuracy、训练曲线、分类报告

运行方式:
  python train_subtype.py
  python train_subtype.py --epochs 10 --batch_size 128
"""

import os
import sys
import argparse
import json
import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim
from torchvision import datasets, models, transforms
from torch.utils.data import DataLoader, random_split
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import seaborn as sns
from sklearn.metrics import confusion_matrix, classification_report
from tqdm import tqdm

if not hasattr(torch.library, 'register_fake'):
    torch.library.register_fake = lambda name: lambda func: func

# 中文字体
def _setup_cn_font():
    cn_fonts = ['Microsoft YaHei', 'SimHei', 'WenQuanYi Micro Hei',
                'Noto Sans CJK SC', 'Source Han Sans CN', 'sans-serif']
    for fn in cn_fonts:
        try:
            matches = [f for f in fm.findSystemFonts() if fn.lower() in f.lower()]
            if matches:
                plt.rcParams['font.sans-serif'] = [fn] + plt.rcParams['font.sans-serif']
                plt.rcParams['axes.unicode_minus'] = False
                return
        except Exception:
            continue
_setup_cn_font()

SUBTYPE_CN = {
    "ADI": "脂肪组织", "BACK": "背景", "DEB": "碎片",
    "LYM": "淋巴细胞", "MUC": "黏液", "MUS": "平滑肌",
    "NORM": "正常结肠黏膜", "STR": "肿瘤相关间质",
    "TUM": "结直肠腺癌上皮",
}

SUBTYPE_EN = {
    "ADI": "Adipose", "BACK": "Background", "DEB": "Debris",
    "LYM": "Lymphocytes", "MUC": "Mucus", "MUS": "Smooth Muscle",
    "NORM": "Normal Mucosa", "STR": "Stroma", "TUM": "Tumor Epithelium",
}

def evaluate_full(model, dataloader, device, classes, output_dir):
    model.eval()
    all_preds, all_labels = [], []

    with torch.no_grad():
        for images, labels in tqdm(dataloader, desc="Evaluating", leave=False):
            images = images.to(device)
            outputs = model(images)
            _, predicted = torch.max(outputs, 1)
            all_preds.extend(predicted.cpu().numpy())
            all_labels.extend(labels.numpy())

    all_preds = np.array(all_preds)
    all_labels = np.array(all_labels)
    overall_acc = (all_preds == all_labels).mean()
    num_classes = len(classes)
    cn_names = [SUBTYPE_CN.get(c, c) for c in classes]

    print("\n" + "=" * 70)
    print("MobileNetV3-Large Subtype Classification - Test Report")
    print("=" * 70)
    print(classification_report(all_labels, all_preds,
                                target_names=cn_names, digits=4))
    print(f"Overall Accuracy: {overall_acc:.4f}")

    # ---- 可视化 ----
    fig, axes = plt.subplots(2, 2, figsize=(18, 14))

    cm = confusion_matrix(all_labels, all_preds)
    sns.heatmap(cm, annot=True, fmt='d', cmap='Blues',
                xticklabels=cn_names, yticklabels=cn_names,
                annot_kws={"fontsize": 10}, ax=axes[0, 0],
                cbar_kws={"shrink": 0.8})
    axes[0, 0].set_title(f'混淆矩阵 (Acc={overall_acc:.2%})', fontsize=14)
    axes[0, 0].set_xlabel('预测')
    axes[0, 0].set_ylabel('真实')
    axes[0, 0].tick_params(axis='both', labelsize=9)

    per_class_acc = cm.diagonal() / (cm.sum(axis=1) + 1e-8)
    colors = ['#22c55e' if a >= 0.9 else '#eab308' if a >= 0.7 else '#ef4444'
              for a in per_class_acc]
    bars = axes[0, 1].barh(range(num_classes)[::-1], per_class_acc[::-1],
                           color=colors[::-1])
    axes[0, 1].set_yticks(range(num_classes)[::-1])
    axes[0, 1].set_yticklabels([cn_names[i] for i in range(num_classes)][::-1])
    axes[0, 1].set_xlim(0, 1.05)
    axes[0, 1].set_xlabel('Accuracy')
    axes[0, 1].set_title('Per-Class Accuracy', fontsize=14)
    for bar, acc in zip(bars, per_class_acc[::-1]):
        axes[0, 1].text(bar.get_width() + 0.01, bar.get_y() + bar.get_height() / 2,
                        f'{acc:.1%}', va='center', fontsize=9)

    class_counts = np.bincount(all_labels, minlength=num_classes)
    axes[1, 0].bar(range(num_classes), class_counts, color='#3b82f6')
    axes[1, 0].set_xticks(range(num_classes))
    axes[1, 0].set_xticklabels(cn_names, rotation=45, ha='right', fontsize=9)
    axes[1, 0].set_ylabel('样本数')
    axes[1, 0].set_title('Test Set Class Distribution', fontsize=14)

    axes[1, 1].axis('off')
    per_class_acc_dict = {classes[i]: per_class_acc[i] for i in range(num_classes)}
    lines = [f"Overall Accuracy: {overall_acc:.2%}", f"Classes: {num_classes}", ""]
    for i in range(num_classes):
        lines.append(f"  {cn_names[i]:10s}  Acc={per_class_acc[i]:.3f}  N={class_counts[i]}")
    axes[1, 1].text(0.05, 0.95, "\n".join(lines), transform=axes[1, 1].transAxes,
                    fontsize=9, verticalalignment='top', fontfamily='sans-serif',
                    bbox=dict(boxstyle='round', facecolor='#f8fafc', alpha=0.9))

    fig.suptitle('MobileNetV3-Large Tissue Subtype Classification - Evaluation',
                 fontsize=16, fontweight='bold')
    fig.tight_layout(rect=[0, 0, 1, 0.97])
    eval_path = os.path.join(output_dir, "subtype_evaluation_report.png")
    plt.savefig(eval_path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"Report saved to: {eval_path}")

    # JSON
    metrics = {
        "overall_accuracy": float(overall_acc),
        "per_class_accuracy": {k: float(v) for k, v in per_class_acc_dict.items()},
    }
    with open(os.path.join(output_dir, "subtype_eval_metrics.json"), "w", encoding="utf-8") as f:
        json.dump(metrics, f, indent=2, ensure_ascii=False)

    return overall_acc


def train(args):
    device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
    print(f"Device: {device}")

    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    current_dir = os.path.dirname(os.path.abspath(__file__))
    data_dir = os.path.join(base_dir, "结直肠癌组织亚型数据集", "NCT-CRC-HE-100K")

    if not os.path.exists(data_dir):
        print(f"ERROR: Dataset not found at {data_dir}")
        print("Run download_nct_crc.py first!")
        return

    # Transforms
    train_transform = transforms.Compose([
        transforms.RandomHorizontalFlip(),
        transforms.RandomVerticalFlip(),
        transforms.ColorJitter(brightness=0.1, contrast=0.1, saturation=0.1, hue=0.05),
        transforms.ToTensor(),
        transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225])
    ])
    val_transform = transforms.Compose([
        transforms.ToTensor(),
        transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225])
    ])

    full_dataset = datasets.ImageFolder(data_dir, transform=train_transform)
    classes = full_dataset.classes
    num_classes = len(classes)
    print(f"Classes ({num_classes}): {classes}")

    # Save classes
    with open(os.path.join(current_dir, "subtype_classes.txt"), "w") as f:
        for c in classes:
            f.write(f"{c}\n")

    # 80/20 split
    train_size = int(0.8 * len(full_dataset))
    val_size = len(full_dataset) - train_size
    train_dataset, val_dataset = random_split(full_dataset, [train_size, val_size],
                                               generator=torch.Generator().manual_seed(42))
    val_dataset.dataset.transform = val_transform

    print(f"Train: {train_size}, Val: {val_size}")

    train_loader = DataLoader(train_dataset, batch_size=args.batch_size,
                              shuffle=True, num_workers=4, pin_memory=True)
    val_loader = DataLoader(val_dataset, batch_size=args.batch_size,
                            shuffle=False, num_workers=4, pin_memory=True)

    # Model
    weights = models.MobileNet_V3_Large_Weights.DEFAULT
    model = models.mobilenet_v3_large(weights=weights)
    in_features = model.classifier[3].in_features
    model.classifier[3] = nn.Linear(in_features, num_classes)
    model = model.to(device)
    print(f"Model: MobileNetV3-Large, params={sum(p.numel() for p in model.parameters()):,}")

    criterion = nn.CrossEntropyLoss()
    optimizer = optim.Adam(model.parameters(), lr=args.lr)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=args.epochs)

    best_acc = 0.0
    history = {"train_loss": [], "val_acc": []}
    best_path = os.path.join(current_dir, "subtype_mobilenet_v3.pth")

    for epoch in range(args.epochs):
        model.train()
        running_loss = 0.0
        pbar = tqdm(train_loader, desc=f"Epoch {epoch+1}/{args.epochs}", leave=False)
        for images, labels in pbar:
            images, labels = images.to(device), labels.to(device)
            optimizer.zero_grad()
            loss = criterion(model(images), labels)
            loss.backward()
            optimizer.step()
            running_loss += loss.item() * images.size(0)
            pbar.set_postfix({"loss": f"{loss.item():.4f}"})

        epoch_loss = running_loss / train_size
        history["train_loss"].append(epoch_loss)
        scheduler.step()

        model.eval()
        correct = 0
        with torch.no_grad():
            for images, labels in val_loader:
                images, labels = images.to(device), labels.to(device)
                _, preds = torch.max(model(images), 1)
                correct += (preds == labels).sum().item()
        epoch_acc = correct / val_size
        history["val_acc"].append(epoch_acc)

        print(f"Epoch [{epoch+1}/{args.epochs}]  Loss: {epoch_loss:.4f}  "
              f"ValAcc: {epoch_acc:.4f}  LR: {scheduler.get_last_lr()[0]:.6f}")

        if epoch_acc > best_acc:
            best_acc = epoch_acc
            torch.save(model.state_dict(), best_path)
            print(f"  --> Best model saved (ValAcc={best_acc:.4f})")

    print(f"\nTraining finished. Best ValAcc: {best_acc:.4f}")

    # 训练曲线
    epochs_range = range(1, len(history["train_loss"]) + 1)
    fig, axes = plt.subplots(1, 2, figsize=(14, 5))
    axes[0].plot(epochs_range, history["train_loss"], '#2563eb', marker='o', markersize=3)
    axes[0].set_xlabel('Epoch')
    axes[0].set_ylabel('Loss')
    axes[0].set_title('Training Loss')
    axes[0].grid(True, alpha=0.3)
    axes[1].plot(epochs_range, history["val_acc"], '#22c55e', marker='s', markersize=3)
    axes[1].axhline(y=best_acc, color='red', linestyle='--', alpha=0.5,
                    label=f'Best={best_acc:.2%}')
    axes[1].set_xlabel('Epoch')
    axes[1].set_ylabel('Val Accuracy')
    axes[1].set_title('Validation Accuracy')
    axes[1].legend()
    axes[1].grid(True, alpha=0.3)
    fig.suptitle(f'MobileNetV3-Large Subtype Training (Best={best_acc:.2%})',
                 fontsize=14, fontweight='bold')
    fig.tight_layout(rect=[0, 0, 1, 0.95])
    metrics_path = os.path.join(current_dir, "subtype_training_metrics.png")
    plt.savefig(metrics_path, dpi=150)
    plt.close()

    # Test Eval
    print("\n--- Test Set Evaluation ---")
    evaluate_full(model, val_loader, device, classes, current_dir)

    return model, best_acc


def main():
    parser = argparse.ArgumentParser(description="MobileNetV3-Large Subtype Training")
    parser.add_argument("--epochs", type=int, default=10, help="训练轮数")
    parser.add_argument("--lr", type=float, default=0.001, help="学习率")
    parser.add_argument("--batch_size", type=int, default=128, help="批量大小")
    args = parser.parse_args()
    train(args)


if __name__ == "__main__":
    main()
