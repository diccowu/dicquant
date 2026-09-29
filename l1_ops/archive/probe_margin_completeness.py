#!/usr/bin/env python3
"""验证: (1) 历史各日期交易所数量分布 (2) 残缺行的 announcement_date"""
import os
from pathlib import Path
import pandas as pd, psycopg2

P = "/mnt/c/new_tdx64/PYPlugins/user/data/raw_data/macro_margin_ad_primary.csv"
df = pd.read_csv(P)
df["date"] = df["date"].astype(str)
n = df.groupby("date")["exchange"].apply(lambda s: len(set(s)))

print("=== 1. 按交易所数量的日期分布(全历史) ===")
print(n.value_counts().sort_index().to_string())
print()
print("=== 2. 仅 2 所的日期区间 ===")
two = n[n == 2].index
print(f"  {min(two)} ~ {max(two)}  共 {len(two)} 天")
print()
print("=== 3. 仅 1 所的日期(残缺嫌疑) ===")
one = n[n == 1].index
print("  " + (", ".join(one) if len(one) else "无"))
print()
print("=== 4. 2023-02-13 后 非3所 日期 ===")
recent = n[n.index >= "2023-02-13"]
odd = recent[recent != 3]
print("  " + (", ".join(f"{d}({c}所)" for d, c in odd.items()) if len(odd) else "无(全部3所齐全)"))
print()
print("=== 5. 各时期应含交易所(用于护栏基准) ===")
print("  2010-03-31 ~ 2023-02-10 -> SSE+SZSE")
print("  2023-02-13 ~ 至今       -> SSE+SZSE+NEEQ")
print("  实测 2 所区间:", f"{min(two)} ~ {max(two)}")

print()
print("=== 6. PG 中 09-24 残缺行的 announcement_date ===")
# 凭据自加载(.env_l1), 2026-09-29 灾备清理: 去明文密码
if not os.environ.get("L1_PG_DSN"):
    _e = Path("/root/l1_ops/.env_l1")
    if _e.exists():
        for _ln in _e.read_text().splitlines():
            _ln = _ln.strip()
            if _ln.startswith("export ") and "=" in _ln:
                _k, _v = _ln[7:].split("=", 1)
                os.environ.setdefault(_k.strip(), _v.strip().strip('"'))
conn = psycopg2.connect(os.environ["L1_PG_DSN"])
cur = conn.cursor()
cur.execute("""
  SELECT indicator_id, period_date, announcement_date, vintage_date, value
  FROM l1_observation
  WHERE indicator_id IN ('margin_balance','margin_purchase') AND period_date='2026-09-24'
""")
for r in cur.fetchall():
    print(f"  {r[0]:16s} period={r[1]} ann={r[2]} vin={r[3]} value={float(r[4]):,.0f}")
conn.close()
