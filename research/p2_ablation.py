# -*- coding: utf-8 -*-
"""P2 消融：时间步 t / 分辨率 对 AUROC 的影响 + 对比表。复用 anoddpm_64.pt 已训模型。"""
import os, json, time, warnings
import numpy as np, torch
warnings.filterwarnings("ignore")
torch.backends.cudnn.benchmark = True
from p2_anoddpm import collect, THRESHOLD, anomaly_score, Patches
from sklearn.metrics import roc_auc_score, average_precision_score

OUT = os.path.dirname(os.path.abspath(__file__))
DEV = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
print(f"[env] {DEV}")


def build_unet(resolution, channels):
    from diffusers import UNet2DModel, DDPMScheduler
    chans = tuple(int(c) for c in channels.split(","))
    if len(chans) == 3:
        dt, ut = ("DownBlock2D", "AttnDownBlock2D", "DownBlock2D"), ("UpBlock2D", "AttnUpBlock2D", "UpBlock2D")
    else:
        dt, ut = ("DownBlock2D", "AttnDownBlock2D"), ("UpBlock2D", "AttnUpBlock2D")
    m = UNet2DModel(sample_size=resolution, in_channels=3, out_channels=3, layers_per_block=1,
                    block_out_channels=chans, down_block_types=dt, up_block_types=ut).to(DEV)
    s = DDPMScheduler(num_train_timesteps=1000, beta_schedule="squaredcos_cap_v2")
    return m, s


def load_ckpt(path):
    ck = torch.load(path, map_location=DEV)
    a = ck["args"]
    m, s = build_unet(a["resolution"], a["channels"])
    m.load_state_dict(ck["model"]); m.eval()
    return m, s


def score_auc(y, scores):
    return roc_auc_score(y, scores), average_precision_score(y, scores)


def main():
    test_items = collect("test")
    paths = [p for p, _ in test_items]
    y = np.array([1 if r >= THRESHOLD else 0 for _, r in test_items])
    print(f"[data] test={len(y)} (Abnormal={int(y.sum())})")

    table = []

    # ---- 时间步消融（推理，复用 64px 模型）----
    model64, sched = load_ckpt(os.path.join(OUT, "anoddpm_64.pt"))
    for t_val in [50, 150, 300, 450, 600, 800]:
        s, _ = anomaly_score(model64, sched, paths, 64, DEV, t_list=(t_val,))
        auc, ap = score_auc(y, s)
        table.append({"axis": "timestep", "value": t_val, "resolution": 64, "auroc": round(auc, 4), "aupr": round(ap, 4)})
        print(f"[ablate] t={t_val}  AUROC={auc:.4f} AUPR={ap:.4f}", flush=True)

    # ---- 分辨率消融（32px 快速训练）----
    from p2_anoddpm import train as train_fn
    import argparse
    train_items = collect("train")
    normal_train = [it for it in train_items if it[1] < THRESHOLD]
    args = argparse.Namespace(resolution=32, batch_size=32, steps=800, lr=2e-4,
                              channels="32,64", layers_per_block=1)
    t0 = time.time()
    model32, sched32 = train_fn(args, normal_train, DEV)
    s32, _ = anomaly_score(model32, sched32, paths, 32, DEV)
    auc32, ap32 = score_auc(y, s32)
    table.append({"axis": "resolution", "value": 32, "resolution": 32, "auroc": round(auc32, 4), "aupr": round(ap32, 4)})
    print(f"[ablate] res=32  AUROC={auc32:.4f} AUPR={ap32:.4f}  train={time.time()-t0:.0f}s", flush=True)

    # 64px 主结果（多时间步平均）引用
    m64, s64 = load_ckpt(os.path.join(OUT, "anoddpm_64.pt"))
    sm, _ = anomaly_score(m64, s64, paths, 64, DEV, t_list=(150, 300, 450))
    am, apm = score_auc(y, sm)
    table.append({"axis": "main", "value": "150/300/450-avg", "resolution": 64, "auroc": round(am, 4), "aupr": round(apm, 4)})

    json.dump({"rows": table}, open(os.path.join(OUT, "results_p2_ablation.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    print("[save] results_p2_ablation.json")


if __name__ == "__main__":
    main()
