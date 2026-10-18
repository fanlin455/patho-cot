# -*- coding: utf-8 -*-
"""从 hf-mirror 下载本地报告用的小模型（Qwen2.5-1.5B-Instruct）"""
import os
import time

os.environ['HF_ENDPOINT'] = 'https://hf-mirror.com'
os.environ['HF_HUB_DISABLE_XET'] = '1'
os.environ['HF_HUB_ENABLE_HF_TRANSFER'] = '0'

from huggingface_hub import snapshot_download

REPO = 'Qwen/Qwen2.5-1.5B-Instruct'
DEST = r'C:\Desktop\基础病理\models\qwen2.5-1.5b-instruct'
os.makedirs(DEST, exist_ok=True)

t0 = time.time()
print('开始下载', REPO, '->', DEST, flush=True)
path = snapshot_download(
    repo_id=REPO,
    local_dir=DEST,
    allow_patterns=['*.json', '*.safetensors', '*.txt', '*.model'],
    max_workers=4,
)
print('DONE', path, '用时 %.1f 分钟' % ((time.time() - t0) / 60), flush=True)
total = sum(os.path.getsize(os.path.join(dp, f))
            for dp, _, fs in os.walk(DEST) for f in fs)
print('MODEL_OK %.1f MB' % (total / 1048576), flush=True)
