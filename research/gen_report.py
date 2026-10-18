# -*- coding: utf-8 -*-
"""对已有历史记录重新生成 AI 报告（走真实 /api/report 接口）"""
import json
import sqlite3
import sys

import requests

BASE = 'http://127.0.0.1:8001'
DB = r'C:\Desktop\基础病理\patho_cot_web\history.db'
RECORD_ID = int(sys.argv[1]) if len(sys.argv) > 1 else 22


def fetch_record(rid):
    con = sqlite3.connect(DB)
    cur = con.cursor()
    cur.execute('SELECT events, description, report FROM records WHERE id=?', (rid,))
    row = cur.fetchone()
    con.close()
    if not row:
        raise SystemExit('记录 %d 不存在' % rid)
    events = json.loads(row[0]) if row[0] else []
    return events, (row[1] or ''), row[2]


events, description, old_report = fetch_record(RECORD_ID)
print('记录 #%d: %d 个步骤事件, 旧报告长度=%s' % (RECORD_ID, len(events), len(old_report) if old_report else 0))

payload = {'description': description, 'results': events, 'record_id': RECORD_ID}
print('提交 /api/report …（LLM 生成可能需 1-3 分钟）', flush=True)

report = None
with requests.post(BASE + '/api/report', json=payload, stream=True, timeout=900) as r:
    r.raise_for_status()
    for raw in r.iter_lines(decode_unicode=True):
        if not raw:
            continue
        line = raw[5:].strip() if raw.startswith('data:') else raw.strip()
        if not line or not line.startswith('{'):
            continue
        try:
            ev = json.loads(line)
        except Exception:
            continue
        st = ev.get('status')
        print('  [SSE] %s  %s' % (st, (ev.get('message') or '')[:80]), flush=True)
        if st == 'done' and ev.get('data', {}).get('report'):
            report = ev['data']['report']
        elif st == 'error':
            print('  错误:', ev.get('message'))
            print('  详情:', json.dumps(ev.get('data', {}), ensure_ascii=False)[:400])
            sys.exit(2)

if not report:
    print('REPORT_FAILED')
    sys.exit(3)

# 校验是否已入库
events2, desc2, saved = fetch_record(RECORD_ID)
print('\n数据库中的报告长度:', len(saved) if saved else 0)
print('--- 报告前 600 字 ---')
print(report[:600])
print('\nREPORT_OK' if saved else 'REPORT_NOT_SAVED')
