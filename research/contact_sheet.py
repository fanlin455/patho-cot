# -*- coding: utf-8 -*-
"""把 15 页 PPT 拼成联排图，便于一次性检查排版"""
import glob
import os
import numpy as np
from PIL import Image

D = r'C:\Desktop\基础病理\research\ppt_preview'
files = sorted(glob.glob(os.path.join(D, 'page-*.png')))
cols, rows = 3, 5
tw, th = 640, 360
sheet = Image.new('RGB', (cols * tw, rows * th), (230, 234, 240))
for i, f in enumerate(files[:cols * rows]):
    im = Image.open(f).convert('RGB').resize((tw - 6, th - 6), Image.LANCZOS)
    x = (i % cols) * tw + 3
    y = (i // cols) * th + 3
    sheet.paste(im, (x, y))
out = os.path.join(D, 'contact_sheet.png')
sheet.save(out)
print(out, sheet.size)
