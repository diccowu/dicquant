#!/bin/bash
# 核实: SZSE 两字段(repayment_amt/sec_sale_vol) 当前是否仍有 NaN
cd /mnt/c/new_tdx64/PYPlugins/user/data/raw_data || exit 1
PY=/root/amazingdata/venv/bin/python3

echo "=== ① 全表空值分布 ==="
$PY -c "
import pandas as pd
p = pd.read_csv('macro_margin_ad_primary.csv')
print(p.isnull().sum()[p.isnull().sum()>0].to_string() or '(无空值)')
print()
print('总行数:', len(p), '| 空值行数:', int(p.isnull().any(axis=1).sum()))
print()
print('=== ② 空值行明细 ===')
na = p[p.isnull().any(axis=1)]
print(na.to_string() if len(na) else '(无)')
print()
print('=== ③ SZSE 全部行中两字段空值数 ===')
sz = p[p.exchange=='SZSE']
print(f'SZSE 行数={len(sz)} | repayment_amt 空={int(sz.repayment_amt.isnull().sum())} | sec_sale_vol 空={int(sz.sec_sale_vol.isnull().sum())}')
print()
print('=== ④ 08-17 SZSE 该行逐字段 ===')
r = p[(p.date=='2026-08-17') & (p.exchange=='SZSE')]
for c in p.columns:
    v = r[c].iloc[0]
    print(f'  {c:24s} = {v}' + ('   ← NaN' if pd.isna(v) else ''))
"
echo ""
echo "=== ⑤ CSV 原始文本行(不经 pandas) ==="
grep "^2026-08-17,SZSE" macro_margin_ad_primary.csv
echo ""
echo "=== ⑥ 该行在 PG 是否入库(两字段不入 PIT, 应无影响) ==="
$PY -c "
import psycopg2
c = psycopg2.connect(os.environ["L1_PG_DSN"])
cur = c.cursor()
cur.execute(\"SELECT indicator_id, period_date, value, status FROM l1_observation WHERE period_date='2026-08-17' AND indicator_id IN ('margin_balance','margin_purchase') ORDER BY indicator_id\")
for r in cur.fetchall(): print(f'  {r[0]:16s} {r[1]} value={float(r[2]):>18,.0f} {r[3]}')
c.close()
" 2>&1 | tail -4
