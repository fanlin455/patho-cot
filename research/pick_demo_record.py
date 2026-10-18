# -*- coding: utf-8 -*-
"""挑选用于演示的历史记录：步骤最全、有 AI 报告"""
import re
import requests

B = 'http://127.0.0.1:8001'
t = requests.get(B + '/history', timeout=20).text
ids = sorted(set(int(x) for x in re.findall(r'/history/(\d+)', t)))

rows = []
for i in ids:
    h = requests.get(B + '/history/%d' % i, timeout=20).text
    steps = len(re.findall(r'Step \d+ ·', h))
    has_report = 'AI 诊断报告' in h
    organ = re.search(r'\u8bc6\u522b\u5668\u5b98\uff1a<span[^>]*>([^<]+)</span>', h)
    nature = re.search(r'\u75c5\u53d8\u6027\u8d28\uff1a<span[^>]*>([^<]+)</span>', h)
    subtype = re.search(r'\u7ec4\u7ec7\u4e9a\u578b\uff1a<span[^>]*>([^<]+)</span>', h)
    lesion = re.search(r'>(\d+)</div><div class="text-xs text-gray-500">\u75c5\u53d8\u7ec6\u80de', h)
    rows.append({
        'id': i, 'steps': steps, 'report': has_report,
        'organ': organ.group(1) if organ else '-',
        'nature': nature.group(1) if nature else '-',
        'subtype': subtype.group(1) if subtype else '-',
        'lesion': lesion.group(1) if lesion else '-',
    })

rows.sort(key=lambda r: (-r['steps'], -int(r['report'])))
print('id  steps report organ      nature   subtype      lesion')
for r in rows:
    print('%3d   %d    %-6s %-10s %-8s %-12s %s' % (
        r['id'], r['steps'], r['report'], r['organ'], r['nature'], r['subtype'], r['lesion']))

best = rows[0]
print('\n推荐使用 id =', best['id'])
