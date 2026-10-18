# -*- coding: utf-8 -*-
"""检查 Ollama 下载与模型标签可用性"""
import json
import requests

def head(url, timeout=25):
    try:
        r = requests.head(url, timeout=timeout, allow_redirects=True)
        cl = r.headers.get('Content-Length')
        return '%s  %s  %s MB' % (r.status_code, r.headers.get('Content-Type', ''), round(int(cl)/1048576, 1) if cl else '?')
    except Exception as e:
        return 'ERR %s: %s' % (type(e).__name__, e)

print('1) ollama.com            ->', head('https://ollama.com'))
print('2) OllamaSetup.exe       ->', head('https://ollama.com/download/OllamaSetup.exe'))
print('3) ollama-windows-amd64  ->', head('https://github.com/ollama/ollama/releases/latest/download/ollama-windows-amd64.zip'))

print('\n4) 模型标签检查（registry.ollama.ai）')
for tag in ['qwen3.5:4b', 'qwen3:4b', 'qwen2.5:3b', 'qwen2.5:7b']:
    name, _, t = tag.partition(':')
    url = 'https://registry.ollama.ai/v2/library/%s/manifests/%s' % (name, t)
    try:
        r = requests.get(url, timeout=25, headers={'Accept': 'application/vnd.docker.distribution.manifest.v2+json'})
        print('   %-14s -> %s' % (tag, r.status_code))
    except Exception as e:
        print('   %-14s -> ERR %s' % (tag, e))
