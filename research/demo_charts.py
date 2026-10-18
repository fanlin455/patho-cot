# -*- coding: utf-8 -*-
"""生成 PPT/视频用的图表与示意图"""
import os
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch

plt.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei']
plt.rcParams['axes.unicode_minus'] = False

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'demo_assets')
os.makedirs(OUT, exist_ok=True)

DARK = '#0b0f17'
BLUE = '#2563eb'
INDIGO = '#4f46e5'
TEAL = '#0d9488'
RED = '#dc2626'
AMBER = '#d97706'
GREY = '#cbd5e1'


def save(fig, name):
    p = os.path.join(OUT, name)
    fig.savefig(p, dpi=160, bbox_inches='tight', facecolor='white')
    plt.close(fig)
    print('saved', name)


# ---------- 1. 器官分类对比 ----------
def chart_organ():
    labels = ['ViT-B/16\n(原方案·微调)', '逻辑回归\n(均值特征)', 'kNN k=5\n(均值特征)',
              '逻辑回归\n(CLS特征)', 'Phikon-v2\nkNN k=5 (CLS)']
    vals = [94.18, 97.85, 97.72, 98.99, 99.75]
    colors = [GREY, '#93c5fd', '#93c5fd', '#3b82f6', DARK]
    fig, ax = plt.subplots(figsize=(9, 4.6))
    bars = ax.bar(labels, vals, color=colors, width=0.62)
    for b, v in zip(bars, vals):
        ax.text(b.get_x() + b.get_width() / 2, v + 0.25, '%.2f%%' % v,
                ha='center', fontsize=11, fontweight='bold',
                color=DARK if v == max(vals) else '#475569')
    ax.set_ylim(88, 101.5)
    ax.set_ylabel('测试集准确率（791 张）', fontsize=11)
    ax.set_title('器官分类：冻结病理基础模型 vs 自训练小模型', fontsize=13, fontweight='bold', pad=12)
    ax.axhline(94.18, color=GREY, ls='--', lw=1.2)
    ax.text(4.45, 94.6, '原方案基线', fontsize=9, color='#94a3b8', ha='right')
    ax.spines[['top', 'right']].set_visible(False)
    ax.grid(axis='y', alpha=0.25)
    ax.annotate('', xy=(4, 99.75), xytext=(0, 94.18),
                arrowprops=dict(arrowstyle='->', color=TEAL, lw=2, connectionstyle='arc3,rad=-0.25'))
    ax.text(2.0, 98.6, '+5.57pp，且零训练', fontsize=11, color=TEAL, fontweight='bold', ha='center')
    save(fig, 'chart_organ.png')


# ---------- 2. 病变性质对比 ----------
def chart_nature():
    groups = ['GCN\n(原方案)', 'PFM 线性探针', 'PFM kNN k=5\n(均值特征)']
    acc = [78.40, 89.89, 91.66]
    auc = [87.4, 96.2, 95.6]
    x = np.arange(len(groups))
    w = 0.34
    fig, ax = plt.subplots(figsize=(8.4, 4.4))
    b1 = ax.bar(x - w / 2, acc, w, label='准确率', color='#93c5fd')
    b2 = ax.bar(x + w / 2, auc, w, label='AUC', color=INDIGO)
    for bs in (b1, b2):
        for b in bs:
            ax.text(b.get_x() + b.get_width() / 2, b.get_height() + 1,
                    '%.2f' % b.get_height(), ha='center', fontsize=10, color='#475569')
    ax.set_xticks(x)
    ax.set_xticklabels(groups, fontsize=10)
    ax.set_ylim(70, 103)
    ax.set_ylabel('百分比 (%)', fontsize=11)
    ax.set_title('病变性质：图像证据判读 vs 细胞图卷积', fontsize=13, fontweight='bold', pad=12)
    ax.legend(frameon=False, fontsize=10)
    ax.spines[['top', 'right']].set_visible(False)
    ax.grid(axis='y', alpha=0.25)
    save(fig, 'chart_nature.png')


# ---------- 3. P2 消融 ----------
def chart_p2():
    ts = [50, 150, 300, 450, 600, 800]
    auc = [0.6327, 0.6668, 0.6738, 0.6586, 0.6446, 0.6135]
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(11.5, 4.2))

    a1.plot(ts, auc, 'o-', color=INDIGO, lw=2.2, ms=7)
    best = ts[int(np.argmax(auc))]
    a1.axvline(best, color=TEAL, ls='--', lw=1.4)
    a1.annotate('最优 t=%d\nAUROC %.4f' % (best, max(auc)),
                xy=(best, max(auc)), xytext=(best + 90, max(auc) - 0.022),
                fontsize=10, color=TEAL, fontweight='bold',
                arrowprops=dict(arrowstyle='->', color=TEAL))
    a1.axhline(0.5, color=GREY, ls=':', lw=1.2)
    a1.text(800, 0.503, '随机基线 0.50', fontsize=9, color='#94a3b8', ha='right')
    a1.set_xlabel('重建时间步 t', fontsize=11)
    a1.set_ylabel('AUROC', fontsize=11)
    a1.set_title('时间步消融', fontsize=12, fontweight='bold')
    a1.set_ylim(0.48, 0.72)
    a1.spines[['top', 'right']].set_visible(False)
    a1.grid(alpha=0.25)

    res = ['32 × 32', '64 × 64']
    v = [0.6283, 0.6710]
    bars = a2.bar(res, v, width=0.5, color=['#93c5fd', DARK])
    for b, x in zip(bars, v):
        a2.text(b.get_x() + b.get_width() / 2, x + 0.004, '%.4f' % x,
                ha='center', fontsize=11, fontweight='bold', color='#475569')
    a2.axhline(0.5, color=GREY, ls=':', lw=1.2)
    a2.set_ylim(0.48, 0.72)
    a2.set_ylabel('AUROC', fontsize=11)
    a2.set_title('分辨率消融', fontsize=12, fontweight='bold')
    a2.spines[['top', 'right']].set_visible(False)
    a2.grid(axis='y', alpha=0.25)

    fig.suptitle('扩散异常检测（AnoDDPM）消融实验 · 诚实结论：AUROC 0.67 不足以进入诊断流程',
                 fontsize=12.5, fontweight='bold', y=1.03)
    save(fig, 'chart_p2.png')


# ---------- 4. 架构流程图 ----------
def diagram_arch():
    fig, ax = plt.subplots(figsize=(12.4, 5.0))
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 44)
    ax.axis('off')

    def box(x, y, w, h, title, sub, color, tc='white'):
        ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle='round,pad=0.6,rounding_size=1.2',
                                    linewidth=0, facecolor=color))
        ax.text(x + w / 2, y + h * 0.62, title, ha='center', va='center',
                fontsize=11, fontweight='bold', color=tc)
        ax.text(x + w / 2, y + h * 0.26, sub, ha='center', va='center',
                fontsize=8.4, color=tc, alpha=0.92)

    def arrow(x1, y1, x2, y2):
        ax.add_patch(FancyArrowPatch((x1, y1), (x2, y2), arrowstyle='-|>',
                                     mutation_scale=14, color='#94a3b8', lw=1.8))

    steps = [
        ('① 切片质量检测', 'PathProfilerQC2', TEAL),
        ('② 器官分类', 'Phikon-v2 + 线性头', BLUE),
        ('③ 细胞检测与分割', 'YOLOv8m-P2 (+SAM)', RED),
        ('④ 病变性质判定', 'ratio 规则 + Phikon\n+ 扩散异常检测', '#9333ea'),
        ('⑤ 组织亚型分类', 'MobileNetV3', AMBER),
        ('⑥ AI 综合分析报告', '本地 LLM (Ollama)', '#4f46e5'),
    ]
    w, h = 14.6, 15.0
    gap = (100 - 2 - len(steps) * w) / (len(steps) - 1)
    for i, (t, s, c) in enumerate(steps):
        x = 1 + i * (w + gap)
        box(x, 20, w, h, t, s, c)
        if i < len(steps) - 1:
            arrow(x + w, 27.5, x + w + gap, 27.5)

    ax.text(50, 8.2, '统一推理引擎：模型懒加载 · 显存单模型驻留 · 步骤级容错与重试 · 配置驱动（config.yaml）· 路径无关',
            ha='center', fontsize=10.5, color='#475569')
    ax.add_patch(FancyBboxPatch((1, 2.2), 98, 8.4, boxstyle='round,pad=0.6,rounding_size=1.2',
                                linewidth=0, facecolor='#f1f5f9'))
    ax.text(50, 6.4, '统一推理引擎  |  模型懒加载 · 显存单模型驻留与释放 · 步骤级容错重试 · 配置驱动 · 路径无关 · 结果入库可回看',
            ha='center', fontsize=10.2, color='#334155', fontweight='bold')
    ax.text(50, 39.5, '智析病理 —— 六级引导式病理图像分析流水线', ha='center',
            fontsize=15, fontweight='bold', color=DARK)
    save(fig, 'diagram_arch.png')


# ---------- 5. 标题卡 ----------
def card_title():
    fig, ax = plt.subplots(figsize=(12.8, 7.2))
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 56)
    ax.axis('off')
    ax.add_patch(plt.Rectangle((0, 0), 100, 56, color='#f8fafc'))
    ax.add_patch(plt.Rectangle((0, 0), 100, 3.2, color=DARK))
    ax.add_patch(FancyBboxPatch((7, 34), 8.4, 8.4, boxstyle='round,pad=0.2,rounding_size=2',
                                linewidth=0, facecolor=BLUE))
    ax.text(11.2, 38.2, 'P', ha='center', va='center', fontsize=26, fontweight='bold', color='white')
    ax.text(18.5, 38.4, 'Patho-COT', ha='left', va='center', fontsize=20, fontweight='bold', color=DARK)
    ax.text(8, 27.5, '智析病理', ha='left', fontsize=42, fontweight='bold', color=DARK)
    ax.text(8, 21.5, '多模态病理图像智能诊断系统', ha='left', fontsize=17, color='#475569')
    ax.text(8, 14.5, '六级引导式分析：质量检测 → 器官分类 → 细胞检测 → 病变性质 → 亚型分类 → AI 报告',
            ha='left', fontsize=11.5, color='#64748b')
    ax.text(8, 9.0, '冻结病理基础模型 + 可解释判读规则 + 生成式异常检测', ha='left',
            fontsize=11, color=TEAL, fontweight='bold')
    save(fig, 'card_title.png')


if __name__ == '__main__':
    chart_organ()
    chart_nature()
    chart_p2()
    diagram_arch()
    card_title()
    print('ALL_CHARTS_DONE')
