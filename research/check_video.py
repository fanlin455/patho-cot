# -*- coding: utf-8 -*-
"""从生成的视频里抽帧检查"""
import os
import subprocess
import imageio_ffmpeg
import numpy as np
import cv2

VID = r'C:\Desktop\数媒比赛-上交源文件\比赛材料\智析病理-演示视频.mp4'
OUT = r'C:\Desktop\基础病理\research\demo_assets'
exe = imageio_ffmpeg.get_ffmpeg_exe()

for sec in [2, 12, 22, 44, 62, 80, 100, 113]:
    p = os.path.join(OUT, '_chk_%03d.jpg' % sec)
    subprocess.run([exe, '-y', '-ss', str(sec), '-i', VID, '-frames:v', '1', p],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    data = np.fromfile(p, dtype=np.uint8)
    img = cv2.imdecode(data, cv2.IMREAD_COLOR)
    print('t=%3ds  ->  %s  %s' % (sec, img.shape if img is not None else 'FAIL', os.path.basename(p)))
