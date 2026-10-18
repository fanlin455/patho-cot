# -*- coding: utf-8 -*-
"""并发测速：各 GitHub 代理下载 Ollama 安装包的前若干 MB"""
import concurrent.futures
import time

import requests

GH = 'https://github.com/ollama/ollama/releases/latest/download/OllamaSetup.exe'
CANDIDATES = [
    'https://gh-proxy.com/' + GH,
    'https://ghproxy.cc/' + GH,
    'https://hub.gitmirror.com/' + GH,
    'https://gh.llkk.cc/' + GH,
    'https://ghproxy.net/' + GH,
    'https://ghfast.top/' + GH,
    'https://github.moeyy.xyz/' + GH,
    'https://ghps.cc/' + GH,
    'https://gh.xxooo.cf/' + GH,
]
PROBE = 8 * 1024 * 1024  # 8 MB


def speed(url):
    name = url.split('/')[2]
    try:
        t0 = time.time()
        got = 0
        with requests.get(url, stream=True, timeout=25,
                          headers={'User-Agent': 'Mozilla/5.0'}) as r:
            if r.status_code != 200:
                return name, None, 'HTTP %s' % r.status_code
            for chunk in r.iter_content(262144):
                got += len(chunk)
                if got >= PROBE or time.time() - t0 > 20:
                    break
        dt = max(time.time() - t0, 1e-6)
        return name, got / 1048576 / dt, '%.1f MB in %.1fs' % (got / 1048576, dt)
    except Exception as e:
        return name, None, type(e).__name__


with concurrent.futures.ThreadPoolExecutor(max_workers=9) as ex:
    for name, sp, note in ex.map(speed, CANDIDATES):
        print('%-24s %s  %s' % (name, ('%5.2f MB/s' % sp) if sp else '   --   ', note))
