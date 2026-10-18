# -*- coding: utf-8 -*-
"""测试：Python 能否通过管道把原始帧喂给 ffmpeg"""
import subprocess
import numpy as np
import imageio_ffmpeg

exe = imageio_ffmpeg.get_ffmpeg_exe()
out = r'C:\Users\Lenovo\AppData\Local\Temp\_pipetest.mp4'
cmd = [exe, '-y', '-f', 'rawvideo', '-pix_fmt', 'bgr24',
       '-s', '640x360', '-r', '24', '-i', 'pipe:0',
       '-an', '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '23',
       '-pix_fmt', 'yuv420p', out]

try:
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                         stderr=subprocess.PIPE)
    for i in range(48):
        f = np.full((360, 640, 3), 40, np.uint8)
        f[:, :, 0] = (i * 5) % 255
        p.stdin.write(f.tobytes())
    p.stdin.close()
    rc = p.wait(timeout=60)
    print('ffmpeg 退出码:', rc)
    err = p.stderr.read().decode('utf-8', 'ignore')[-400:]
    print('stderr 尾部:', err if rc else '(无)')
    import os
    print('输出文件:', os.path.exists(out), os.path.getsize(out) if os.path.exists(out) else 0, 'bytes')
except Exception as e:
    print('PIPE_FAILED:', type(e).__name__, e)
