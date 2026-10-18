# -*- coding: utf-8 -*-
"""
@file nctcrc_probe.py
@brief P0 泄漏复测（第二部分）：NCT-CRC-HE-100K 独立队列探针

NCT-CRC-HE-100K 来自 Radboud 队列（非 TCGA），9 类结直肠组织亚型。
用它验证 Phikon-v2 特征是否"跨域泛化"，排除"只对 PanNuke/TCGA 有效"的疑虑。
从 10.89GB zip 中只读抽取子集（每类 200 张），不整包解压。
"""
import io
import os
import time
import zipfile

import numpy as np
import torch
from PIL import Image
from sklearn.metrics import accuracy_score
from sklearn.neighbors import KNeighborsClassifier
from sklearn.preprocessing import normalize
from torchvision import transforms

OUT = os.path.dirname(os.path.abspath(__file__))
ZIP = r"C:\Desktop\基础病理\结直肠癌组织亚型数据集\NCT-CRC-HE-100K.zip"
MODEL_DIR = r"C:\Desktop\基础病理\models\phikon-v2"
CLASSES = ["ADI", "BACK", "DEB", "LYM", "MUC", "MUS", "NORM", "STR", "TUM"]
PER_CLASS = 200
TRAIN_PER = 150
TEST_PER = 50


def main():
    device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
    from transformers import AutoModel
    model = AutoModel.from_pretrained(MODEL_DIR).eval().to(device)
    tf = transforms.Compose([
        transforms.Resize(224, interpolation=transforms.InterpolationMode.BICUBIC),
        transforms.CenterCrop(224),
        transforms.ToTensor(),
        transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
    ])

    feats, labels = [], []
    with zipfile.ZipFile(ZIP) as z:
        names = z.namelist()
        for ci, cls in enumerate(CLASSES):
            prefix = f"NCT-CRC-HE-100K/{cls}/"
            files = sorted([n for n in names if n.startswith(prefix) and n.endswith(".tif")])[:PER_CLASS]
            print(f"[{cls}] 抽取 {len(files)} 张", flush=True)
            for fn in files:
                img = Image.open(io.BytesIO(z.read(fn))).convert("RGB")
                feats.append(tf(img))
                labels.append(ci)

    X = torch.stack(feats)
    B = 64
    emb = []
    with torch.no_grad():
        for i in range(0, len(X), B):
            xb = X[i:i + B].to(device)
            with torch.autocast(device_type="cuda", dtype=torch.float16):
                out = model(xb)
            emb.append(out.last_hidden_state.float()[:, 0].cpu().numpy())
    F = np.concatenate(emb)
    y = np.array(labels)
    print(f"[feat] {F.shape}")

    # 每类前 TRAIN_PER 训练，后 TEST_PER 测试
    tr_idx, te_idx = [], []
    for ci in range(len(CLASSES)):
        base = ci * PER_CLASS
        tr_idx.extend(range(base, base + TRAIN_PER))
        te_idx.extend(range(base + TRAIN_PER, base + PER_CLASS))
    F = normalize(F, norm="l2")
    Ftr, Fte = F[tr_idx], F[te_idx]
    ytr, yte = y[tr_idx], y[te_idx]

    for k in [1, 5, 20]:
        knn = KNeighborsClassifier(n_neighbors=k).fit(Ftr, ytr)
        acc = accuracy_score(yte, knn.predict(Fte))
        print(f"kNN k={k}: 测试集准确率 = {acc*100:.2f}%")

    print("\n[结论] NCT-CRC(非TCGA) 9 类亚型：Phikon-v2 特征 + kNN 准确率见上。")
    print("       若 >90%，说明特征跨域泛化，PanNuke 的 99.75% 并非仅靠同域记忆。")


if __name__ == "__main__":
    main()
