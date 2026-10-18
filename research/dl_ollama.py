# -*- coding: utf-8 -*-
"""断点续传下载 Ollama 安装包（经 gh-proxy.com）"""
import os
import sys
import time

import requests

URL = 'https://gh-proxy.com/https://github.com/ollama/ollama/releases/latest/download/OllamaSetup.exe'
OUT_DIR = r'C:\Users\Lenovo\AppData\Local\Temp\ollama_setup'
OUT = os.path.join(OUT_DIR, 'OllamaSetup.exe')
os.makedirs(OUT_DIR, exist_ok=True)

s = requests.Session()
s.headers.update({'User-Agent': 'Mozilla/5.0'})

total = None
for attempt in range(1, 21):
    done = os.path.getsize(OUT) if os.path.exists(OUT) else 0
    headers = {'Range': 'bytes=%d-' % done} if done else {}
    try:
        r = s.get(URL, headers=headers, timeout=30, stream=True)
        if r.status_code == 200 and done:
            # 服务器不支持断点，重头来
            done = 0
            os.remove(OUT)
        cr = r.headers.get('Content-Range')
        if cr and '/' in cr:
            total = int(cr.split('/')[-1])
        elif r.headers.get('Content-Length'):
            total = done + int(r.headers['Content-Length'])

        mode = 'ab' if done else 'wb'
        t0 = time.time()
        last = 0
        with open(OUT, mode) as f:
            for chunk in r.iter_content(1024 * 512):
                if not chunk:
                    continue
                f.write(chunk)
                done += len(chunk)
                if time.time() - last > 15:
                    last = time.time()
                    sp = done / 1048576 / max(time.time() - t0, 1e-6)
                    pct = (done / total * 100) if total else 0
                    print('[dl] %.1f/%.1f MB  %.2f%%  %.1f MB/s' % (
                        done / 1048576, (total or 0) / 1048576, pct, sp), flush=True)
        r.close()
        if total and done >= total:
            print('[dl] 完成: %.1f MB' % (done / 1048576), flush=True)
            print('DOWNLOAD_OK', flush=True)
            sys.exit(0)
    except Exception as e:
        print('[dl] 第 %d 次中断: %s: %s' % (attempt, type(e).__name__, e), flush=True)
        time.sleep(3)

print('DOWNLOAD_FAILED', flush=True)
sys.exit(1)
