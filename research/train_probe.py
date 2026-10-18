# -*- coding: utf-8 -*-
"""
@file train_probe.py
@brief P0：在冻结 PFM 特征上训线性探针，做 19 类器官分类，与现有 ViT-B/16 的 94.18% 对比

对应调研结论：PFM 的正确用法是"冻结特征 + 线性探针"，不微调。
输出：控制台报告 + results_probe.json + results_probe.md
"""
import argparse
import json
import os

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix
from sklearn.neighbors import KNeighborsClassifier
from sklearn.preprocessing import StandardScaler

OUT_DIR = os.path.dirname(os.path.abspath(__file__))
BASELINE = {"name": "ViT-B/16 (现有系统, 微调)", "test_acc": 0.9418, "note": "设计文档记载，791 张测试集"}


def evaluate(name, y_true, y_pred, labels_idx, organs):
    acc = accuracy_score(y_true, y_pred)
    cm = confusion_matrix(y_true, y_pred, labels=labels_idx)
    per_class = {}
    for i, organ in enumerate(organs):
        total = cm[i].sum()
        correct = cm[i, i]
        per_class[organ] = {
            "n": int(total),
            "acc": float(correct / total) if total else None,
        }
    return {"name": name, "acc": float(acc), "per_class": per_class}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--features", default=os.path.join(OUT_DIR, "features_phikon2.npz"))
    ap.add_argument("--baseline", type=float, default=0.9418)
    args = ap.parse_args()

    d = np.load(args.features, allow_pickle=True)
    organs = [str(x) for x in d["organs"]]
    labels = d["labels"]
    splits = d["splits"]
    n_cls = len(organs)
    print(f"[data] 类别={n_cls}, 样本={len(labels)}")
    for sp in ["train", "val", "test"]:
        print(f"   {sp}: {(splits == sp).sum()}")

    tr, va, te = splits == "train", splits == "val", splits == "test"
    ytr, yva, yte = labels[tr], labels[va], labels[te]
    labels_idx = list(range(n_cls))

    results = []
    for pool in ["cls", "mean"]:
        if pool not in d:
            continue
        X = d[pool]
        Xtr_raw, Xva_raw, Xte_raw = X[tr], X[va], X[te]
        scaler = StandardScaler().fit(Xtr_raw)
        Xtr, Xva, Xte = scaler.transform(Xtr_raw), scaler.transform(Xva_raw), scaler.transform(Xte_raw)

        # --- 逻辑回归：用 val 选 C ---
        best = None
        for C in [0.01, 0.1, 1.0, 10.0, 100.0]:
            clf = LogisticRegression(C=C, max_iter=3000, n_jobs=-1)
            clf.fit(Xtr, ytr)
            va_acc = accuracy_score(yva, clf.predict(Xva))
            if best is None or va_acc > best[0]:
                best = (va_acc, C, clf)
        va_acc, C, clf = best
        te_pred = clf.predict(Xte)
        te_acc = accuracy_score(yte, te_pred)
        print(f"\n[LogReg/{pool}] best C={C}  val={va_acc:.4f}  TEST={te_acc:.4f}")
        results.append(evaluate(f"LogReg-{pool}", yte, te_pred, labels_idx, organs))
        results[-1]["C"] = C
        results[-1]["val_acc"] = float(va_acc)
        results[-1]["pool"] = pool
        results[-1]["model_type"] = "logreg"

        # --- kNN 参考 ---
        for k in [5, 20]:
            knn = KNeighborsClassifier(n_neighbors=k, n_jobs=-1)
            knn.fit(Xtr, ytr)
            knn_acc = accuracy_score(yte, knn.predict(Xte))
            print(f"[kNN/{pool}] k={k}  TEST={knn_acc:.4f}")
            results.append(evaluate(f"kNN{k}-{pool}", yte, knn.predict(Xte), labels_idx, organs))
            results[-1]["model_type"] = "knn"
            results[-1]["k"] = k
            results[-1]["pool"] = pool

    # ---- 汇总 ----
    print("\n" + "=" * 66)
    print(f"{'方法':<20}{'测试集准确率':>14}{'对比基线':>14}")
    print("-" * 66)
    print(f"{BASELINE['name']:<20}{BASELINE['test_acc']*100:>13.2f}%{'—':>14}")
    best_res = max(results, key=lambda r: r["acc"])
    for r in sorted(results, key=lambda r: -r["acc"]):
        delta = (r["acc"] - args.baseline) * 100
        print(f"{r['name']:<20}{r['acc']*100:>13.2f}%{delta:>+13.2f}pp")
    print("=" * 66)

    # 长尾类别表现
    print("\n[长尾类别表现 - 最佳方法]")
    pc = best_res["per_class"]
    for organ in sorted(pc, key=lambda o: (pc[o]["acc"] if pc[o]["acc"] is not None else 0)):
        a = pc[organ]["acc"]
        print(f"  {organ:<16} n={pc[organ]['n']:>4}  acc={a*100:>6.2f}%" if a is not None else f"  {organ}: n/a")

    summary = {
        "baseline": BASELINE,
        "results": results,
        "best": {"name": best_res["name"], "acc": best_res["acc"],
                 "delta_pp": (best_res["acc"] - args.baseline) * 100},
    }
    out_json = os.path.join(OUT_DIR, "results_probe.json")
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(f"\n[save] {out_json}")

    # markdown 报告
    lines = ["# P0 结果：冻结 Phikon-v2 + 线性探针 vs 现有 ViT-B/16", "",
             f"- 基线：{BASELINE['name']} = **{BASELINE['test_acc']*100:.2f}%**（{BASELINE['note']}）",
             f"- 最佳方法：**{best_res['name']}** = **{best_res['acc']*100:.2f}%**（{(best_res['acc']-args.baseline)*100:+.2f}pp）", "",
             "| 方法 | 池化 | 测试集准确率 | 对比基线 |", "|---|---|---|---|"]
    for r in sorted(results, key=lambda r: -r["acc"]):
        lines.append(f"| {r['name']} | {r.get('pool','-')} | {r['acc']*100:.2f}% | {(r['acc']-args.baseline)*100:+.2f}pp |")
    lines += ["", "## 各类别准确率（最佳方法）", "", "| 器官 | 测试样本数 | 准确率 |", "|---|---|---|"]
    for organ in sorted(pc, key=lambda o: (pc[o]["acc"] if pc[o]["acc"] is not None else 0)):
        a = pc[organ]["acc"]
        lines.append(f"| {organ} | {pc[organ]['n']} | {a*100:.2f}% |" if a is not None else f"| {organ} | {pc[organ]['n']} | n/a |")
    out_md = os.path.join(OUT_DIR, "results_probe.md")
    with open(out_md, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"[save] {out_md}")


if __name__ == "__main__":
    main()
