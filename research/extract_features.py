# -*- coding: utf-8 -*-
"""
@file extract_features.py
@brief P0：用冻结的病理基础模型（Phikon-v2）抽取 patch 特征并落盘

设计要点
- 冻结 encoder，纯推理，不训练（对应调研结论：PFM 的核心用法是"冻结特征 + 线性探针"）
- 特征落盘（.npz）后，后续训线性探针/MLP 都复用，不必重复跑 GPU
- 独立目录输出，不触碰正在运行的主系统

用法：
    python extract_features.py --model phikon-v2 --out features_phikon2.npz
"""
import argparse
import glob
import os
import sys
import time

import numpy as np
import torch
from PIL import Image
from torchvision import transforms

DATASET_ROOT = r"C:\Desktop\基础病理\器官分类数据集"
MODEL_DIR = r"C:\Desktop\基础病理\models\phikon-v2"
OUT_DIR = os.path.dirname(os.path.abspath(__file__))

SPLITS = ["train", "val", "test"]


def list_samples(root):
    """返回 [(path, organ, split), ...]"""
    organs = sorted([d for d in os.listdir(root)
                     if os.path.isdir(os.path.join(root, d))])
    samples = []
    for organ in organs:
        for split in SPLITS:
            for p in sorted(glob.glob(os.path.join(root, organ, split, "images", "*.png"))):
                samples.append((p, organ, split))
    return organs, samples


def build_transform(size=224):
    """PFM 标准预处理：resize + center crop + ImageNet 归一化"""
    return transforms.Compose([
        transforms.Resize(size, interpolation=transforms.InterpolationMode.BICUBIC),
        transforms.CenterCrop(size),
        transforms.ToTensor(),
        transforms.Normalize(mean=[0.485, 0.456, 0.406],
                             std=[0.229, 0.224, 0.225]),
    ])


def load_model(model_dir, device):
    """优先用 transformers 加载 Phikon-v2（ViT-L/16, DINOv2 预训练）"""
    from transformers import AutoModel
    model = AutoModel.from_pretrained(model_dir)
    model.eval().to(device)
    return model


def extract(model, paths, tf, device, batch_size=32):
    """批量抽特征：同时返回 CLS token 与 patch token 均值（两种池化都留下，便于对比）"""
    feats_cls, feats_mean = [], []
    with torch.no_grad():
        for i in range(0, len(paths), batch_size):
            batch_paths = paths[i:i + batch_size]
            imgs = []
            for p in batch_paths:
                img = Image.open(p).convert("RGB")
                imgs.append(tf(img))
            x = torch.stack(imgs).to(device)
            if device.type == "cuda":
                with torch.autocast(device_type="cuda", dtype=torch.float16):
                    out = model(x)
            else:
                out = model(x)
            last = out.last_hidden_state.float()          # (B, 1+N, C)
            feats_cls.append(last[:, 0].cpu().numpy())     # CLS
            feats_mean.append(last[:, 1:].mean(dim=1).cpu().numpy())  # patch 均值
    return np.concatenate(feats_cls), np.concatenate(feats_mean)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="phikon-v2")
    ap.add_argument("--model-dir", default=MODEL_DIR)
    ap.add_argument("--dataset", default=DATASET_ROOT)
    ap.add_argument("--out", default=os.path.join(OUT_DIR, "features_phikon2.npz"))
    ap.add_argument("--batch-size", type=int, default=32)
    ap.add_argument("--limit", type=int, default=0, help=">0 时只跑前 N 张（调试用）")
    args = ap.parse_args()

    device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
    print(f"[env] device={device}, model_dir={args.model_dir}")

    organs, samples = list_samples(args.dataset)
    if args.limit:
        samples = samples[:args.limit]
    print(f"[data] organs={len(organs)}, samples={len(samples)}")

    t0 = time.time()
    model = load_model(args.model_dir, device)
    print(f"[model] loaded in {time.time()-t0:.1f}s on {device}")

    tf = build_transform(224)
    paths = [s[0] for s in samples]
    labels = np.array([organs.index(s[1]) for s in samples])
    splits = np.array([s[2] for s in samples])

    t0 = time.time()
    f_cls, f_mean = extract(model, paths, tf, device, args.batch_size)
    dt = time.time() - t0
    print(f"[extract] {len(paths)} images in {dt:.1f}s -> {len(paths)/max(dt,1e-6):.1f} img/s")
    print(f"[shape] cls={f_cls.shape}, mean={f_mean.shape}")

    np.savez_compressed(
        args.out,
        cls=f_cls.astype(np.float32),
        mean=f_mean.astype(np.float32),
        labels=labels,
        splits=splits,
        organs=np.array(organs),
        paths=np.array(paths),
    )
    print(f"[save] {args.out}")
    print(f"[size] {os.path.getsize(args.out)/1024**2:.1f} MB")


if __name__ == "__main__":
    main()
