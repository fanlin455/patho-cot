# -*- coding: utf-8 -*-
"""生成《智析病理》演示视频（1080p / 24fps / H.264，字幕解说版）"""
import math
import os
import shutil
import subprocess

import cv2
import numpy as np
import imageio_ffmpeg
from PIL import Image, ImageDraw, ImageFont

# 路径无关：图片素材取脚本同目录的 demo_assets，产出放到上一级的「答辩材料」
_HERE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(_HERE, 'demo_assets')
OUT_DIR = os.path.join(os.path.dirname(_HERE), '答辩材料')
TMP = os.path.join(os.environ.get('TEMP', _HERE), 'patho_frames')
OUT = os.path.join(OUT_DIR, '智析病理-演示视频.mp4')

W, H, FPS = 1920, 1080, 24
FONT_B = r'C:\Windows\Fonts\msyhbd.ttc'
FONT_R = r'C:\Windows\Fonts\msyh.ttc'
DARK = (0x0B, 0x0F, 0x17)

os.makedirs(OUT_DIR, exist_ok=True)
if os.path.isdir(TMP):
    shutil.rmtree(TMP, ignore_errors=True)
os.makedirs(TMP, exist_ok=True)


# ---------------- 基础工具 ----------------
def font(path, size):
    return ImageFont.truetype(path, size)


def imread_u(path):
    """Unicode 安全读取（路径含中文时必须这样读）"""
    data = np.fromfile(path, dtype=np.uint8)
    img = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if img is None:
        raise FileNotFoundError(path)
    return img


def imwrite_u(path, bgr, quality=92):
    ok, buf = cv2.imencode('.jpg', bgr, [cv2.IMWRITE_JPEG_QUALITY, quality])
    if not ok:
        raise IOError('encode failed: ' + path)
    buf.tofile(path)


def load_rgb(path):
    return cv2.cvtColor(imread_u(path), cv2.COLOR_BGR2RGB)


def crop_resize(img, x0, y0, x1, y1):
    x0, y0 = max(0, int(x0)), max(0, int(y0))
    x1, y1 = min(img.shape[1], int(x1)), min(img.shape[0], int(y1))
    sub = img[y0:y1, x0:x1]
    interp = cv2.INTER_AREA if sub.shape[0] > H else cv2.INTER_CUBIC
    return cv2.resize(sub, (W, H), interpolation=interp)


def make_text_card(lines, bg=(248, 250, 252), accent=DARK, out_name=None):
    """程序生成文字卡（整幅 1920x1080）"""
    im = Image.new('RGB', (W, H), bg)
    d = ImageDraw.Draw(im)
    d.rectangle([0, H - 16, W, H], fill=accent)
    y = 250
    for text, size, color, bold, gap in lines:
        f = font(FONT_B if bold else FONT_R, size)
        d.text((160, y), text, font=f, fill=color)
        y += gap
    arr = np.array(im)
    if out_name:
        imwrite_u(os.path.join(ASSETS, out_name), cv2.cvtColor(arr, cv2.COLOR_RGB2BGR))
    return arr


def overlay(frame, title, sub):
    """在帧上叠加标题（左上）与字幕条（底部）"""
    im = Image.fromarray(frame)
    d = ImageDraw.Draw(im, 'RGBA')
    if sub:
        f = font(FONT_B, 34)
        bbox = d.textbbox((0, 0), sub, font=f)
        tw = bbox[2] - bbox[0]
        pad = 26
        bw = min(W - 160, tw + pad * 2)
        bx = (W - bw) // 2
        by = H - 128
        d.rounded_rectangle([bx, by, bx + bw, by + 74], radius=16, fill=(11, 15, 23, 214))
        d.text((bx + (bw - tw) // 2, by + 15), sub, font=f, fill=(255, 255, 255))
    if title:
        f = font(FONT_B, 30)
        bbox = d.textbbox((0, 0), title, font=f)
        tw = bbox[2] - bbox[0]
        d.rounded_rectangle([56, 46, 56 + tw + 44, 46 + 62], radius=14, fill=(255, 255, 255, 226))
        d.text((78, 58), title, font=f, fill=(15, 23, 42))
    return np.array(im)


# ---------------- 场景构造 ----------------
def scene_kenburns(img, title, sub, dur, z0=1.0, z1=1.12, cx=0.5, cy=0.5):
    """缩放推拉（z 为相对"填满画面"的额外放大倍数）"""
    ih, iw = img.shape[:2]

    def frame_at(t):
        u = min(max(t / dur, 0.0), 1.0)
        e = u * u * (3 - 2 * u)                      # smoothstep
        z = z0 + (z1 - z0) * e
        base = max(W / iw, H / ih)
        s = base * z
        w = W / s
        h = H / s
        x = cx * iw - w / 2
        y = cy * ih - h / 2
        f = crop_resize(img, x, y, x + w, y + h)
        return overlay(f, title, sub)
    return dur, frame_at


def scene_panv(img, title, subs, dur, y_from=0.0, y_to=1.0):
    """长图纵向平移；subs = [(t_end_ratio, 字幕), ...]"""
    ih, iw = img.shape[:2]
    vis_h = W * (H / W) / (W / iw) if iw > W else ih
    win_h = min(ih, int(iw * H / W))

    def sub_at(u):
        for end, s in subs:
            if u <= end:
                return s
        return subs[-1][1]

    def frame_at(t):
        u = min(max(t / dur, 0.0), 1.0)
        y = (y_from + (y_to - y_from) * u) * (ih - win_h)
        f = crop_resize(img, 0, y, iw, y + win_h)
        return overlay(f, title, sub_at(u))
    return dur, frame_at


def scene_static(img, title, sub, dur, zoom=1.06):
    return scene_kenburns(img, title, sub, dur, z0=1.0, z1=zoom, cx=0.5, cy=0.5)


def scene_textcard(img, title, sub, dur):
    ih, iw = img.shape[:2]

    def frame_at(t):
        u = min(max(t / dur, 0.0), 1.0)
        z = 1.0 + 0.03 * u
        w = W / z
        h = H / z
        f = crop_resize(img, (iw - w) / 2, (ih - h) / 2, (iw + w) / 2, (ih + h) / 2)
        return overlay(f, title, sub)
    return dur, frame_at


# ---------------- 生成文字卡 ----------------
card_problem = make_text_card([
    ('为什么做这个作品？', 62, (11, 15, 23), True, 130),
    ('病理诊断存在明显的经验门槛：', 36, (71, 85, 105), False, 74),
    ('· 基层医院与教学场景缺乏病理读片能力', 34, (51, 65, 85), False, 66),
    ('· 病理医生培养周期长，判读高度依赖经验', 34, (51, 65, 85), False, 66),
    ('· 现有 AI 方案多为“黑箱给结论”，医生无法复核推理过程', 34, (51, 65, 85), False, 66),
], out_name='card_problem.png')

card_idea = make_text_card([
    ('我们的思路', 62, (11, 15, 23), True, 130),
    ('把病理诊断的推理链本身可视化', 40, (13, 148, 136), True, 88),
    ('看片 → 定位 → 定性 → 出报告，拆成六个可回看、可单步重试的环节', 33, (51, 65, 85), False, 74),
    ('每一级都给出量化证据（分数 / 计数 / 概率），而不是结论黑箱', 33, (51, 65, 85), False, 74),
    ('定位是“辅助与教学”，不替代医生诊断', 33, (51, 65, 85), False, 74),
], out_name='card_idea.png')

card_end = make_text_card([
    ('智析病理  Patho-COT', 68, (11, 15, 23), True, 130),
    ('把病理诊断的推理链，变成看得见、可复核的六步', 38, (71, 85, 105), False, 92),
    ('感谢观看 · 恳请批评指正', 34, (37, 99, 235), True, 80),
], out_name='card_end.png')

# ---------------- 组场景 ----------------
IMG = {n: load_rgb(os.path.join(ASSETS, n)) for n in [
    'card_title.png', 'diagram_arch.png', '01_home.png', '02_history.png',
    '03_detail.png', 'chart_organ.png', 'chart_nature.png', 'chart_p2.png',
    '05_anomaly_heatmap.png']}

scenes = [
    scene_kenburns(IMG['card_title.png'], '', '智析病理 · 多模态病理图像智能诊断系统', 5.0, z0=1.0, z1=1.05),
    scene_textcard(card_problem, '问题', '病理诊断的经验门槛', 8.5),
    scene_textcard(card_idea, '思路', '把推理链可视化，每步给出量化证据', 8.5),
    scene_kenburns(IMG['diagram_arch.png'], '系统架构', '六级引导式分析流水线', 10.0, z0=1.04, z1=1.0),
    scene_kenburns(IMG['01_home.png'], '操作界面', '上传切片即可分析，也可直接点样例图', 10.0, z0=1.0, z1=1.14, cx=0.62, cy=0.62),
    scene_panv(IMG['03_detail.png'], '实测 · 完整分析链路', [
        (0.16, '真实病例：多 patch 批量分析'),
        (0.32, 'Step 1 质量检测：可用性 0.7547 · 对焦 10.0 · 染色 4.0'),
        (0.48, 'Step 2 器官分类：头颈部（置信度 89.68%）'),
        (0.63, 'Step 3 细胞检测：检出病变细胞 201 个，并给出标注图'),
        (0.79, 'Step 4 病变性质：异常（置信度 99.0%）'),
        (1.01, 'Step 5 组织亚型：肿瘤相关间质（28.82%）'),
    ], 33.0),
]

if os.path.exists(os.path.join(ASSETS, '06_report.png')):
    scenes.append(scene_kenburns(load_rgb(os.path.join(ASSETS, '06_report.png')), 'Step 6 · AI 报告',
                                 '本地 LLM 生成结构化中文报告，病例数据不出本机', 12.0, z0=1.0, z1=1.1))

scenes += [
    scene_static(IMG['chart_organ.png'], '核心结果 ①', '器官分类：99.75%（+5.57pp，零训练）', 9.0),
    scene_static(IMG['chart_nature.png'], '核心结果 ②', '病变性质：AUC 96.2%（+8.8pp）', 9.0),
    scene_static(IMG['chart_p2.png'], '核心结果 ③', '扩散异常检测：AUROC 0.67（实验性，不参与诊断结论）', 10.0),
    scene_kenburns(IMG['02_history.png'], '结果留存', '所有分析自动入库，可回看完整分步结果', 8.0, z0=1.08, z1=1.0),
    scene_textcard(card_end, '', '感谢观看 · 恳请批评指正', 6.0),
]

# ---------------- 写帧 ----------------
XF = 12  # 转场帧数


def write(frame, idx):
    p = os.path.join(TMP, 'f_%06d.jpg' % idx)
    imwrite_u(p, cv2.cvtColor(frame, cv2.COLOR_RGB2BGR))


n = 0
total_dur = sum(d for d, _ in scenes)
print('场景数 %d，总时长 %.1f 秒' % (len(scenes), total_dur), flush=True)

for si, (dur, fn) in enumerate(scenes):
    nf = int(round(dur * FPS))
    nxt = scenes[si + 1][1] if si + 1 < len(scenes) else None
    for i in range(nf):
        t = i / FPS
        f = fn(t)
        if nxt and i >= nf - XF:
            a = (i - (nf - XF)) / float(XF)
            f2 = nxt(a * XF / FPS)
            f = (f * (1 - a) + f2 * a).astype(np.uint8)
        write(f, n)
        n += 1
    print('  场景 %d/%d 完成，累计 %d 帧' % (si + 1, len(scenes), n), flush=True)

# ---------------- 编码 ----------------
exe = imageio_ffmpeg.get_ffmpeg_exe()
cmd = [exe, '-y', '-framerate', str(FPS), '-i', os.path.join(TMP, 'f_%06d.jpg'),
       '-c:v', 'libx264', '-preset', 'medium', '-crf', '20',
       '-pix_fmt', 'yuv420p', '-movflags', '+faststart', OUT]
print('编码中…', flush=True)
log = os.path.join(TMP, 'ff.log')
with open(log, 'wb') as lf:
    rc = subprocess.run(cmd, stdout=lf, stderr=lf).returncode
print('ffmpeg 退出码:', rc)
if rc == 0 and os.path.exists(OUT):
    print('VIDEO_OK', OUT, round(os.path.getsize(OUT) / 1048576, 1), 'MB', flush=True)
    shutil.rmtree(TMP, ignore_errors=True)
else:
    print('VIDEO_FAILED，日志尾部：')
    with open(log, 'r', errors='ignore') as lf:
        print(lf.read()[-800:])
