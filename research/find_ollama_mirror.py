# -*- coding: utf-8 -*-
"""寻找可用的 Ollama 安装包下载通道"""
import requests

s = requests.Session()
s.headers.update({'User-Agent': 'Mozilla/5.0'})

print('--- 1) 解析 ollama.com 的真实跳转目标 ---')
try:
    r = s.get('https://ollama.com/download/OllamaSetup.exe', timeout=25, stream=True, allow_redirects=True)
    print('最终 URL :', r.url)
    print('状态码   :', r.status_code)
    cl = r.headers.get('Content-Length')
    print('大小     :', round(int(cl)/1048576, 1), 'MB' if cl else '?')
    r.close()
except Exception as e:
    print('ERR', type(e).__name__, e)

GH = 'https://github.com/ollama/ollama/releases/latest/download/OllamaSetup.exe'
proxies = [
    'https://ghfast.top/' + GH,
    'https://gh-proxy.com/' + GH,
    'https://ghproxy.net/' + GH,
    'https://mirror.ghproxy.com/' + GH,
    'https://gh.llkk.cc/' + GH,
]
print('\n--- 2) 逐个测试 GitHub 代理 ---')
for u in proxies:
    try:
        r = s.get(u, timeout=20, stream=True)
        cl = r.headers.get('Content-Length')
        print('%-28s -> %s  %s MB' % (u.split('/')[2], r.status_code, round(int(cl)/1048576, 1) if cl else '?'))
        r.close()
    except Exception as e:
        print('%-28s -> ERR %s' % (u.split('/')[2], type(e).__name__))

print('\n--- 3) 其他可能通道 ---')
others = {
    'hf-mirror.com': 'https://hf-mirror.com',
    'modelscope.cn': 'https://www.modelscope.cn',
    'pypi(清华)': 'https://pypi.tuna.tsinghua.edu.cn/simple/',
    'objects.githubusercontent.com': 'https://objects.githubusercontent.com',
}
for k, u in others.items():
    try:
        r = s.head(u, timeout=15, allow_redirects=True)
        print('%-32s -> %s' % (k, r.status_code))
    except Exception as e:
        print('%-32s -> ERR %s' % (k, type(e).__name__))
