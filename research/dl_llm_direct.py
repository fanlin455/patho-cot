# -*- coding: utf-8 -*-
"""直接经 hf-mirror 断点续传下载 Qwen2.5-1.5B-Instruct 权重（绕过 xet）"""
import os
import sys
import time

import requests

REPO = 'Qwen/Qwen2.5-1.5B-Instruct'
FILES = ['model.safetensors']
DEST = r'C:\Desktop\基础病理\models\qwen2.5-1.5b-instruct'
os.makedirs(DEST, exist_ok=True)

s = requests.Session()
s.headers.update({'User-Agent': 'Mozilla/5.0'})

for fn in FILES:
    url = 'https://hf-mirror.com/%s/resolve/main/%s' % (REPO, fn)
    out = os.path.join(DEST, fn)
    for attempt in range(1, 41):
        done = os.path.getsize(out) if os.path.exists(out) else 0
        headers = {'Range': 'bytes=%d-' % done} if done else {}
        try:
            r = s.get(url, headers=headers, timeout=30, stream=True, allow_redirects=True)
            if r.status_code == 200 and done:
                done = 0
                if os.path.exists(out):
                    os.remove(out)
            elif r.status_code not in (200, 206):
                print('[dl] HTTP %s，重试' % r.status_code, flush=True)
                time.sleep(3)
                continue

            cr = r.headers.get('Content-Range')
            if cr and '/' in cr:
                total = int(cr.split('/')[-1])
            elif r.headers.get('Content-Length'):
                total = done + int(r.headers['Content-Length'])
            else:
                total = 0

            mode = 'ab' if done else 'wb'
            t0, last = time.time(), 0
            with open(out, mode) as f:
                for chunk in r.iter_content(1024 * 512):
                    if not chunk:
                        continue
                    f.write(chunk)
                    done += len(chunk)
                    if time.time() - last > 15:
                        last = time.time()
                        sp = done / 1048576 / max(time.time() - t0, 1e-6)
                        print('[dl] %s  %.1f/%.1f MB  %.2f MB/s' % (
                            fn, done / 1048576, total / 1048576, sp), flush=True)
            r.close()
            if total and done >= total:
                print('[dl] %s 下载完成 %.1f MB' % (fn, done / 1048576), flush=True)
                break
        except Exception as e:
            print('[dl] 第 %d 次中断: %s: %s' % (attempt, type(e).__name__, e), flush=True)
            time.sleep(3)
    else:
        print('DOWNLOAD_FAILED', flush=True)
        sys.exit(1)

tot = sum(os.path.getsize(os.path.join(dp, f))
          for dp, _, fs in os.walk(DEST) for f in fs)
print('MODEL_OK %.1f MB' % (tot / 1048576), flush=True)
