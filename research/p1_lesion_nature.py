# -*- coding: utf-8 -*-
"""
@file p1_lesion_nature.py
@brief P1：用冻结 PFM 特征做「病变性质」二分类，与现有 GCN 的 78.4% 对比

标签定义（严格复现 病变性质/preprocess.py）：
    lesion_ratio = (类别0=lesion 的细胞数) / 总细胞数
    threshold    = GMM 分界 = 0.49364936493649364
    label        = 1 (Abnormal) if ratio >= threshold else 0 (Normal)

同时暴露一个关键问题：该标签是「检测结果 ratio」的确定性函数，
而部署管线本身就能直接算出 ratio → 因此会额外报告「ratio 规则」基线。
"""
import glob
import json
import os

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, roc_auc_score
from sklearn.neighbors import KNeighborsClassifier
from sklearn.preprocessing import StandardScaler

OUT_DIR = os.path.dirname(os.path.abspath(__file__))
DATASET_ROOT = r"C:\Desktop\基础病理\器官分类数据集"
THRESHOLD = 0.49364936493649364
GCN_BASELINE = 0.784  # 设计文档记载：Acc 78.4%, AUC 87.4%


def lesion_ratio_of(label_path):
    """复现 _compute_lesion_ratio：类别0(lesion) 占比"""
    try:
        data = np.loadtxt(label_path, ndmin=2)
        if data.size == 0:
            return 0.0, 0
        cls_ids = data[:, 0].astype(np.int32)
        total = len(cls_ids)
        return (float(np.sum(cls_ids == 0)) / total if total else 0.0), total
    except Exception:
        return 0.0, 0


def main():
    d = np.load(os.path.join(OUT_DIR, "features_phikon2.npz"), allow_pickle=True)
    paths = [str(p) for p in d["paths"]]
    splits = d["splits"]
    organs = [str(o) for o in d["organs"]]

    ratios, ncells, y = [], [], []
    for p in paths:
        lp = p.replace(os.sep + "images" + os.sep, os.sep + "labels" + os.sep)
        lp = os.path.splitext(lp)[0] + ".txt"
        r, n = lesion_ratio_of(lp)
        ratios.append(r)
        ncells.append(n)
        y.append(1 if r >= THRESHOLD else 0)
    ratios = np.array(ratios)
    ncells = np.array(ncells)
    y = np.array(y)

    print("[data] 样本=%d | 细胞数中位数=%.0f | ratio 均值=%.4f"
          % (len(y), np.median(ncells), ratios.mean()))
    tr, va, te = splits == "train", splits == "val", splits == "test"
    for sp, m in [("train", tr), ("val", va), ("test", te)]:
        n1 = int(y[m].sum())
        print(f"   {sp}: n={m.sum():>5}  Normal={m.sum()-n1:>5}  Abnormal={n1:>5}  异常占比={n1/max(m.sum(),1):.1%}")

    # ---------- 基线 ----------
    maj = max(np.bincount(y[tr])) / tr.sum()
    maj_pred = np.full(te.sum(), int(np.argmax(np.bincount(y[tr]))))
    acc_majority = accuracy_score(y[te], maj_pred)
    # ratio 规则（注意：标签就是由它定义的，所以必然 100%）
    acc_rule = accuracy_score(y[te], (ratios[te] >= THRESHOLD).astype(int))
    print("\n" + "=" * 72)
    print(f"{'方法':<34}{'测试集准确率':>14}{'说明':>22}")
    print("-" * 72)
    print(f"{'多数类基线':<34}{acc_majority*100:>13.2f}%{'':>22}")
    print(f"{'ratio 规则（部署管线可直接算）':<34}{acc_rule*100:>13.2f}%{'与标签同源':>22}")
    print(f"{'GCN（现有系统, 设计文档）':<34}{GCN_BASELINE*100:>13.2f}%{'AUC 87.4%':>22}")

    # ---------- PFM 探针 ----------
    results = []
    for pool in ["cls", "mean"]:
        X = d[pool]
        sc = StandardScaler().fit(X[tr])
        Xtr, Xva, Xte = sc.transform(X[tr]), sc.transform(X[va]), sc.transform(X[te])

        best = None
        for C in [0.01, 0.1, 1.0, 10.0]:
            clf = LogisticRegression(C=C, max_iter=3000).fit(Xtr, y[tr])
            a = accuracy_score(y[va], clf.predict(Xva))
            if best is None or a > best[0]:
                best = (a, C, clf)
        _, C, clf = best
        pred = clf.predict(Xte)
        prob = clf.predict_proba(Xte)[:, 1]
        acc = accuracy_score(y[te], pred)
        auc = roc_auc_score(y[te], prob)
        results.append({"name": f"LogReg-{pool}", "acc": acc, "auc": auc, "C": C})
        print(f"{'PFM 线性探针 (' + pool + ')':<34}{acc*100:>13.2f}%{f'AUC {auc*100:.1f}%':>22}")

        for k in [5, 20]:
            knn = KNeighborsClassifier(n_neighbors=k).fit(Xtr, y[tr])
            p2 = knn.predict(Xte)
            a2 = accuracy_score(y[te], p2)
            try:
                auc2 = roc_auc_score(y[te], knn.predict_proba(Xte)[:, 1])
            except Exception:
                auc2 = float("nan")
            results.append({"name": f"kNN{k}-{pool}", "acc": a2, "auc": auc2, "k": k})
            print(f"{'PFM kNN k=' + str(k) + ' (' + pool + ')':<34}{a2*100:>13.2f}%{f'AUC {auc2*100:.1f}%':>22}")
    print("=" * 72)

    best_res = max(results, key=lambda r: r["auc"])
    print(f"\n[结论] 最佳 PFM 方法: {best_res['name']}  Acc={best_res['acc']*100:.2f}%  AUC={best_res['auc']*100:.1f}%")
    print(f"       相对 GCN(78.4%): {(best_res['acc']-GCN_BASELINE)*100:+.2f}pp")

    summary = {
        "threshold": THRESHOLD,
        "label_source": "lesion_ratio >= threshold (GMM boundary)",
        "n_test": int(te.sum()),
        "baselines": {
            "majority": float(acc_majority),
            "ratio_rule": float(acc_rule),
            "gcn_documented": GCN_BASELINE,
        },
        "pfm_results": results,
        "best": best_res,
    }
    with open(os.path.join(OUT_DIR, "results_p1_nature.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2, default=float)
    print(f"[save] {os.path.join(OUT_DIR, 'results_p1_nature.json')}")


if __name__ == "__main__":
    main()
