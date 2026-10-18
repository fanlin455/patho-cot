# -*- coding: utf-8 -*-
"""
@file save_organ_head.py
@brief P0 接入：把 Phikon-v2 器官分类头（线性探针 + 标准化参数）保存为轻量 .pt

供 engine.py 加载：Phikon-v2 抽 CLS 特征 -> StandardScaler -> Linear(1024->19) -> softmax
相比 kNN 无需保存 6320 张特征库，只存 scaler(mean/std) + 19x1024 权重，几乎零显存。
"""
import os

import numpy as np
import torch
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

OUT = os.path.dirname(os.path.abspath(__file__))


def main():
    d = np.load(os.path.join(OUT, "features_phikon2.npz"), allow_pickle=True)
    X = d["cls"].astype(np.float32)
    y = d["labels"].astype(np.int64)
    sp = d["splits"]
    organs = [str(o) for o in d["organs"]]

    tr = sp == "train"
    scaler = StandardScaler().fit(X[tr])
    clf = LogisticRegression(C=0.1, max_iter=3000).fit(scaler.transform(X[tr]), y[tr])
    acc = clf.score(scaler.transform(X[sp == "test"]), y[sp == "test"])
    print(f"线性探针测试集准确率 = {acc*100:.2f}%")

    torch.save({
        "scaler_mean": torch.from_numpy(scaler.mean_.astype(np.float32)),
        "scaler_scale": torch.from_numpy(scaler.scale_.astype(np.float32)),
        "weight": torch.from_numpy(clf.coef_.astype(np.float32)),   # (19, 1024)
        "bias": torch.from_numpy(clf.intercept_.astype(np.float32)),  # (19,)
        "organs": organs,
    }, os.path.join(OUT, "organ_phikon_head.pt"))
    print(f"[save] {os.path.join(OUT, 'organ_phikon_head.pt')}")
    print(f"       权重形状 {clf.coef_.shape}，体积 {os.path.getsize(os.path.join(OUT,'organ_phikon_head.pt'))/1024:.0f} KB")


if __name__ == "__main__":
    main()
