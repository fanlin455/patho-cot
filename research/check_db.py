# -*- coding: utf-8 -*-
import sqlite3

DB = r'C:\Desktop\基础病理\patho_cot_web\history.db'
c = sqlite3.connect(DB)
cur = c.cursor()
cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
print('tables:', [r[0] for r in cur.fetchall()])

cur.execute('PRAGMA table_info(records)')
cols = [r[1] for r in cur.fetchall()]
print('columns:', cols)

cur.execute('SELECT COUNT(*) FROM records')
print('rows:', cur.fetchone()[0])

if 'report' in cols:
    cur.execute("SELECT COUNT(*) FROM records WHERE report IS NOT NULL AND LENGTH(TRIM(report)) > 0")
    print('有报告文本的记录数:', cur.fetchone()[0])

# 看一条最完整的记录
cur.execute('SELECT * FROM records ORDER BY id DESC LIMIT 1')
row = cur.fetchone()
print('\n最新一条:')
for k, v in zip(cols, row):
    sv = str(v)
    print('  %-16s %s' % (k, (sv[:110] + '...') if len(sv) > 110 else sv))
