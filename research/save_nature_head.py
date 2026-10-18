# -*- coding: utf-8 -*-
"""
@file save_nature_head.py
@brief P1 接入：把"病变性质"的 Phikon 线性头保存为轻量 .pt

标签：lesion_ratio >= 0.49364936493649364 -> Abnormal（与现有 GMM 弱标签一致）
特征：Phikon-v2 CLS（features_phikon2.npz 已含）
结果：线性探针 Acc 89.89% / AUC 96.2%（对比 GCN 78.4% / 87.4%）
"""
import os

import numpy as np
import torch
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

OUT = os.path.dirname(os.path.abspath(__file__))
DATASET_ROOT = r"C:\Desktop\基础病理\器官分类数据集"
THRESHOLD = 0.49364936493649364


def lesion_ratio(label_path):
    try:
        data = np.loadtxt(label_path, ndmin=2)
        if data.size == 0:
            return 0.0
        cls = data[:, 0].astype(np.int32)
        return float(np.sum(cls == 0)) / len(cls) if len(cls) else 0.0
    except Exception:
        return 0.0


def main():
    d = np.load(os.path.join(OUT, "features_phikon2.npz"), allow_pickle=True)
    X = d["cls"].astype(np.float32)
    paths = [str(p) for p in d["paths"]]
    sp = d["splits"]

    y = []
    for p in paths:
        lp = p.replace(os.sep + "images" + os.sep, os.sep + "labels" + os.sep)
        lp = os.path.splitext(lp)[0] + ".txt"
        y.append(1 if lesion_ratio(lp) >= THRESHOLD else 0)
    y = np.array(y)

    tr = sp == "train"
    scaler = StandardScaler().fit(X[tr])
    clf = LogisticRegression(C=1.0, max_iter=3000).fit(scaler.transform(X[tr]), y[tr])
    te = sp == "test"
    acc = clf.score(scaler.transform(X[te]), y[te])
    print(f"病变性质线性探针测试集准确率 = {acc*100:.2f}%")

    torch.save({
        "scaler_mean": torch.from_numpy(scaler.mean_.astype(np.float32)),
        "scaler_scale": torch.from_numpy(scaler.scale_.astype(np.float32)),
        "weight": torch.from_numpy(clf.coef_.astype(np.float32)),   # (1, 1024)
        "bias": torch.from_numpy(clf.intercept_.astype(np.float32)),  # (1,)
        "threshold": THRESHOLD,
    }, os.path.join(OUT, "nature_phikon_head.pt"))
    print(f"[save] {os.path.join(OUT, 'nature_phikon_head.pt')}")


if __name__ == "__main__":
    main()
