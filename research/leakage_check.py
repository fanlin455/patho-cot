# -*- coding: utf-8 -*-
"""
@file leakage_check.py
@brief P0 泄漏复测：近邻距离分析

判断 kNN=99.75% 是"真泛化"还是"死记硬背"的三种证据：
1. 测试样本到最近训练样本的余弦距离分布（若大量 ≈0，说明训练/测试有近重复图）
2. 最近同类 vs 最近异类的距离差（margin）：泛化好的模型，同类最近邻应显著更近
3. 各器官的最近邻是否都属于同器官（跨器官混淆程度）
"""
import json
import os

import numpy as np
from sklearn.preprocessing import normalize

OUT = os.path.dirname(os.path.abspath(__file__))


def main():
    d = np.load(os.path.join(OUT, "features_phikon2.npz"), allow_pickle=True)
    X = d["cls"].astype(np.float32)
    y = d["labels"].astype(np.int64)
    sp = d["splits"]
    organs = [str(o) for o in d["organs"]]

    X = normalize(X, norm="l2")  # 余弦距离 = 1 - 内积
    tr, te = sp == "train", sp == "test"
    Xtr, ytr = X[tr], y[tr]
    Xte, yte = X[te], y[te]

    # 测试 × 训练 余弦相似度（分块避免显存/内存爆）
    sims = []
    B = 256
    for i in range(0, len(Xte), B):
        sims.append(Xte[i:i + B] @ Xtr.T)
    sim = np.concatenate(sims)          # (791, 6320) 余弦相似度
    dist = 1.0 - sim                    # 余弦距离 [0, 2]

    order = np.argsort(dist, axis=1)    # 每行按距离升序
    nn_idx = order[:, 0]                # 最近邻
    nn_dist = dist[np.arange(len(Xte)), nn_idx]
    nn_label = ytr[nn_idx]
    same = nn_label == yte              # 最近邻是否同类

    # 最近同类 / 最近异类
    d_same = np.full(len(Xte), np.inf)
    d_diff = np.full(len(Xte), np.inf)
    for i in range(len(Xte)):
        same_mask = ytr == yte[i]
        if same_mask.any():
            d_same[i] = dist[i][same_mask].min()
        if (~same_mask).any():
            d_diff[i] = dist[i][~same_mask].min()
    margin = d_diff - d_same            # >0 表示同类更近

    print("=" * 70)
    print("泄漏复测 —— 近邻距离分析（余弦距离，越小越近）")
    print("=" * 70)
    print(f"测试样本 {len(Xte)}，训练样本 {len(Xtr)}")
    print(f"\n[1] 最近邻距离分布（含 0 则为近重复/死记硬背信号）")
    for p in [0, 1, 5, 25, 50, 75, 95, 99, 100]:
        print(f"    {p:>3} 分位 = {np.percentile(nn_dist, p):.4f}")
    near_dup = (nn_dist < 0.02).sum()
    print(f"    距离 < 0.02 的测试样本数（疑似近重复）: {near_dup} / {len(Xte)}")

    print(f"\n[2] kNN=1 准确率 = {same.mean()*100:.2f}%（最近邻即同类）")

    print(f"\n[3] 同类/异类距离差 margin（应 > 0 且较大）")
    m_valid = margin[np.isfinite(margin)]
    print(f"    margin 中位数 = {np.median(m_valid):.4f}  均值 = {m_valid.mean():.4f}")
    print(f"    margin < 0 的样本数（最近邻是异类）: {(m_valid < 0).sum()} / {len(m_valid)}")

    print(f"\n[4] 各器官测试样本的平均最近邻距离（越小越可能被'记住'）")
    for oi, organ in enumerate(organs):
        m = yte == oi
        if m.sum():
            print(f"    {organ:<16} n={m.sum():>3}  平均距离={nn_dist[m].mean():.4f}  最近邻同类率={same[m].mean()*100:.1f}%")

    result = {
        "nn_dist_percentiles": {str(p): float(np.percentile(nn_dist, p)) for p in [0, 1, 5, 50, 95, 100]},
        "near_dup_count": int(near_dup),
        "knn1_acc": float(same.mean()),
        "margin_median": float(np.median(m_valid)),
        "margin_mean": float(m_valid.mean()),
        "margin_negative": int((m_valid < 0).sum()),
    }
    with open(os.path.join(OUT, "results_leakage.json"), "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"\n[save] {os.path.join(OUT, 'results_leakage.json')}")


if __name__ == "__main__":
    main()
