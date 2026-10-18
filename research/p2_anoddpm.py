# -*- coding: utf-8 -*-
"""
@file p2_anoddpm.py
@brief P2：扩散模型无监督异常检测（AnoDDPM 基线）

思路（对应调研结论：扩散做"异常检测"而非"实时推理组件"）
1. 只用 GMM 判定为 Normal 的样本训练一个 DDPM（学"正常组织长什么样"）
2. 推理：对图像加噪到时间步 t，让模型一步去噪还原 x0
3. 异常分数 = ||x0 - x0_pred||（重建不出来的地方 = 异常）
4. 用测试集标签算 AUROC，并输出病灶热力图

标签同 P1：lesion_ratio >= 0.49364936493649364 → Abnormal
"""
import argparse
import glob
import json
import os
import time
import warnings

import numpy as np
import torch
import torch.nn.functional as F
from PIL import Image
from torch.utils.data import DataLoader, Dataset
from torchvision import transforms

warnings.filterwarnings("ignore")          # 抑制 loadtxt 空文件等噪音
torch.backends.cudnn.benchmark = True      # 固定输入尺寸下加速卷积

OUT_DIR = os.path.dirname(os.path.abspath(__file__))
DATASET_ROOT = r"C:\Desktop\基础病理\器官分类数据集"
THRESHOLD = 0.49364936493649364


# ---------------- 数据 ----------------
def lesion_ratio(label_path):
    try:
        data = np.loadtxt(label_path, ndmin=2)
        if data.size == 0:
            return 0.0
        cls = data[:, 0].astype(np.int32)
        return float(np.sum(cls == 0)) / len(cls) if len(cls) else 0.0
    except Exception:
        return 0.0


def collect(split):
    """收集某 split 下的 (img_path, ratio)"""
    out = []
    for organ_dir in sorted(os.listdir(DATASET_ROOT)):
        img_dir = os.path.join(DATASET_ROOT, organ_dir, split, "images")
        lbl_dir = os.path.join(DATASET_ROOT, organ_dir, split, "labels")
        if not os.path.isdir(img_dir):
            continue
        for img in sorted(glob.glob(os.path.join(img_dir, "*.png"))):
            name = os.path.splitext(os.path.basename(img))[0]
            out.append((img, lesion_ratio(os.path.join(lbl_dir, name + ".txt"))))
    return out


class Patches(Dataset):
    def __init__(self, items, resolution):
        self.items = items
        self.tf = transforms.Compose([
            transforms.Resize(resolution, interpolation=transforms.InterpolationMode.BICUBIC),
            transforms.CenterCrop(resolution),
            transforms.ToTensor(),
            transforms.Normalize([0.5, 0.5, 0.5], [0.5, 0.5, 0.5]),  # -> [-1,1]
        ])

    def __len__(self):
        return len(self.items)

    def __getitem__(self, i):
        p, _ = self.items[i]
        return self.tf(Image.open(p).convert("RGB"))


# ---------------- 训练 ----------------
def train(args, normal_items, device):
    from diffusers import DDPMScheduler, UNet2DModel

    # ---- 预加载全部正常样本（避免每步解码 PNG，这是之前慢的主因）----
    tf = transforms.Compose([
        transforms.Resize(args.resolution, interpolation=transforms.InterpolationMode.BICUBIC),
        transforms.CenterCrop(args.resolution),
    ])
    t_load = time.time()
    buf = np.zeros((len(normal_items), args.resolution, args.resolution, 3), dtype=np.uint8)
    for i, (p, _) in enumerate(normal_items):
        buf[i] = np.array(tf(Image.open(p).convert("RGB")))
    data_u8 = torch.from_numpy(buf).permute(0, 3, 1, 2).contiguous()   # (N,3,R,R) uint8, 驻留内存
    print(f"[data] preloaded {len(normal_items)} patches in {time.time()-t_load:.1f}s "
          f"({data_u8.nelement()/1024**2:.0f}MB RAM)")

    chans = tuple(int(c) for c in args.channels.split(","))
    if len(chans) == 3:
        down_types = ("DownBlock2D", "AttnDownBlock2D", "DownBlock2D")
        up_types = ("UpBlock2D", "AttnUpBlock2D", "UpBlock2D")
    elif len(chans) == 2:
        down_types = ("DownBlock2D", "AttnDownBlock2D")
        up_types = ("UpBlock2D", "AttnUpBlock2D")
    else:
        raise ValueError("channels 只支持 2 或 3 段，例如 32,64 或 64,128,256")

    model = UNet2DModel(
        sample_size=args.resolution,
        in_channels=3,
        out_channels=3,
        layers_per_block=args.layers_per_block,
        block_out_channels=chans,
        down_block_types=down_types,
        up_block_types=up_types,
    ).to(device)
    n_param = sum(p.numel() for p in model.parameters())
    print(f"[model] UNet2D params={n_param/1e6:.1f}M  resolution={args.resolution}  channels={chans}")

    noise_sched = DDPMScheduler(num_train_timesteps=1000, beta_schedule="squaredcos_cap_v2")
    opt = torch.optim.AdamW(model.parameters(), lr=args.lr)

    N = data_u8.shape[0]
    log_every = max(10, args.steps // 20)
    model.train()
    t0, losses = time.time(), []
    for step in range(1, args.steps + 1):
        idx = torch.randint(0, N, (args.batch_size,))
        x0 = data_u8[idx].to(device).float() / 127.5 - 1.0
        t = torch.randint(0, noise_sched.config.num_train_timesteps, (x0.shape[0],), device=device).long()
        noise = torch.randn_like(x0)
        x_t = noise_sched.add_noise(x0, noise, t)
        pred = model(x_t, t).sample
        loss = F.mse_loss(pred, noise)
        opt.zero_grad(set_to_none=True)
        loss.backward()
        opt.step()
        losses.append(loss.item())
        if step % log_every == 0 or step == 1:
            dt = max(time.time() - t0, 1e-6)
            print(f"  step {step}/{args.steps}  loss={np.mean(losses[-log_every:]):.4f}  "
                  f"{step/dt:.2f} it/s  elapsed={dt/60:.1f}min", flush=True)

    ckpt = os.path.join(OUT_DIR, f"anoddpm_{args.resolution}.pt")
    torch.save({"model": model.state_dict(), "resolution": args.resolution,
                "steps": step, "args": vars(args)}, ckpt)
    print(f"[save] {ckpt}")
    return model, noise_sched


# ---------------- 异常评分 ----------------
@torch.no_grad()
def anomaly_score(model, noise_sched, paths, resolution, device, t_list=(150, 300, 450), batch=16):
    """单步重建误差作为异常分数（多时间步平均）"""
    model.eval()
    tf = Patches([(p, 0.0) for p in paths], resolution)
    scores, maps = [], []
    for i in range(0, len(tf), batch):
        x0 = torch.stack([tf[j] for j in range(i, min(i + batch, len(tf)))]).to(device)
        acc = torch.zeros(x0.shape[0], device=device)
        accmap = torch.zeros_like(x0)
        for t_val in t_list:
            t = torch.full((x0.shape[0],), t_val, device=device, dtype=torch.long)
            noise = torch.randn_like(x0)
            x_t = noise_sched.add_noise(x0, noise, t)
            eps = model(x_t, t).sample
            ab = noise_sched.alphas_cumprod[t_val].to(device)
            x0_pred = (x_t - (1 - ab).sqrt() * eps) / ab.sqrt()
            err = (x0 - x0_pred).abs()
            acc += err.flatten(1).mean(1)
            accmap += err
        scores.append((acc / len(t_list)).cpu().numpy())
        maps.append((accmap / len(t_list)).cpu().numpy())
    return np.concatenate(scores), np.concatenate(maps)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--resolution", type=int, default=64)
    ap.add_argument("--batch-size", type=int, default=16)
    ap.add_argument("--steps", type=int, default=3000)
    ap.add_argument("--lr", type=float, default=2e-4)
    ap.add_argument("--channels", default="32,64,128", help="UNet 各层通道，如 32,64,128")
    ap.add_argument("--layers-per-block", type=int, default=1)
    ap.add_argument("--limit-train", type=int, default=0, help=">0 时限制正常样本数")
    ap.add_argument("--limit-test", type=int, default=0)
    args = ap.parse_args()

    device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
    print(f"[env] device={device}")

    train_items = collect("train")
    test_items = collect("test")
    normal_train = [it for it in train_items if it[1] < THRESHOLD]
    if args.limit_train:
        normal_train = normal_train[:args.limit_train]
    if args.limit_test:
        test_items = test_items[:args.limit_test]
    print(f"[data] train total={len(train_items)}  normal-only={len(normal_train)}  test={len(test_items)}")

    model, sched = train(args, normal_train, device)

    paths = [p for p, _ in test_items]
    y = np.array([1 if r >= THRESHOLD else 0 for _, r in test_items])
    scores, maps = anomaly_score(model, sched, paths, args.resolution, device)

    from sklearn.metrics import roc_auc_score, average_precision_score
    auc = roc_auc_score(y, scores)
    ap_score = average_precision_score(y, scores)
    print("\n" + "=" * 60)
    print(f"[P2 结果] 异常检测 AUROC = {auc:.4f}   AUPR = {ap_score:.4f}")
    print(f"          测试样本 {len(y)}（Normal={int((y==0).sum())}, Abnormal={int((y==1).sum())}）")
    print(f"          对比：GCN 文献值 AUC 0.874（弱监督）")
    print("=" * 60)

    # 热力图：挑一个分数最高的异常样本
    idx = int(np.argmax(np.where(y == 1, scores, -1)))
    heat = maps[idx].mean(0)
    heat = (heat - heat.min()) / (heat.max() - heat.min() + 1e-8)
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        img = np.array(Image.open(paths[idx]).convert("RGB").resize((args.resolution, args.resolution)))
        fig, ax = plt.subplots(1, 3, figsize=(12, 4))
        ax[0].imshow(img); ax[0].set_title("original"); ax[0].axis("off")
        ax[1].imshow(heat, cmap="jet"); ax[1].set_title("anomaly heatmap"); ax[1].axis("off")
        ax[2].imshow(img); ax[2].imshow(heat, cmap="jet", alpha=0.45); ax[2].set_title("overlay"); ax[2].axis("off")
        out_png = os.path.join(OUT_DIR, "p2_anomaly_heatmap.png")
        plt.tight_layout(); plt.savefig(out_png, dpi=120); plt.close()
        print(f"[save] {out_png}")
    except Exception as e:
        print(f"[warn] heatmap failed: {e}")

    with open(os.path.join(OUT_DIR, "results_p2_anoddpm.json"), "w", encoding="utf-8") as f:
        json.dump({"auroc": float(auc), "aupr": float(ap_score),
                   "n_test": int(len(y)), "resolution": args.resolution,
                   "steps": args.steps, "normal_train": len(normal_train),
                   "gcn_reference_auc": 0.874}, f, ensure_ascii=False, indent=2)
    print(f"[save] {os.path.join(OUT_DIR, 'results_p2_anoddpm.json')}")


if __name__ == "__main__":
    main()
