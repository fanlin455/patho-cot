# -*- coding: utf-8 -*-
"""用"暗像素行"定位内容边界，裁出正文长图与 AI 报告卡片"""
import numpy as np
import cv2

A = r'C:\Desktop\基础病理\research\demo_assets'
im = cv2.imdecode(np.fromfile(A + r'\03_detail.png', np.uint8), cv2.IMREAD_COLOR)
H, W = im.shape[:2]
print('原图', W, 'x', H)

x0, x1 = 620, W - 60
gray = cv2.cvtColor(im[:, x0:x1], cv2.COLOR_BGR2GRAY)
dark = (gray < 130).sum(axis=1)          # 每行暗像素数（文字/图形）

rows = np.where(dark > 8)[0]
bottom = int(rows.max()) + 70 if len(rows) else H
print('内容底部 y =', bottom)

# 在内容区里找"最后一段足够长的空白行"作为 AI 报告卡的分界
blank = dark <= 2
seg_start = None
gaps = []
for y in range(bottom):
    if blank[y]:
        if seg_start is None:
            seg_start = y
    else:
        if seg_start is not None and y - seg_start >= 24:
            gaps.append((seg_start, y))
        seg_start = None
lower = [g for g in gaps if g[0] > bottom * 0.55]
card_top = (lower[-1][1] + 8) if lower else int(bottom * 0.8)
print('报告卡片起点 y =', card_top, '（共%d段空白）' % len(lower))

cv2.imencode('.png', im[:bottom, :])[1].tofile(A + r'\03_detail.png')
print('03_detail 裁剪为', im[:bottom, :].shape)

rep = im[max(0, card_top - 8):bottom, :]
cv2.imencode('.png', rep)[1].tofile(A + r'\06_report.png')
print('06_report', rep.shape)

prev = cv2.resize(rep, (rep.shape[1] // 4, max(1, rep.shape[0] // 4)))
cv2.imencode('.jpg', prev, [cv2.IMWRITE_JPEG_QUALITY, 90])[1].tofile(A + r'\prev_report.jpg')
print('预览 -> prev_report.jpg')
