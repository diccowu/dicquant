#!/usr/bin/env python3
"""两融完整性护栏 —— 事实核对脚本(只输出事实, 结论由复检人下)

覆盖: A. _margin_need 口径分段  B. margin_complete_prefix 截断行为
      C. guard dup_key 回归(修复前会误报)  D. 实源拉取  E. L0/PG 现状

用法: python verify_margin_fix.py [--no-net]
"""
import argparse, hashlib, importlib.util, os, sys
from pathlib import Path
import pandas as pd

# 凭据: 若环境变量未设, 从 .env_l1 自加载(避免复检方手工 export 出错)
if not os.environ.get("AD_USERNAME"):
    _e = Path("/root/l1_ops/.env_l1")
    if _e.exists():
        for _ln in _e.read_text().splitlines():
            _ln = _ln.strip()
            if _ln.startswith("export ") and "=" in _ln:
                _k, _v = _ln[7:].split("=", 1)
                os.environ.setdefault(_k.strip(), _v.strip().strip('"'))

PY = "/root/l1_ops/l1_update.py"
PRIM = "/mnt/c/new_tdx64/PYPlugins/user/data/raw_data/macro_margin_ad_primary.csv"
DAILY = "/mnt/c/new_tdx64/PYPlugins/user/data/raw_data/macro_margin_ad_daily.csv"
DSN = os.environ.get("L1_PG_DSN") or ("host=100.76.208.125 port=5432 user=postgres "
       "dbname=quant connect_timeout=20")
spec = importlib.util.spec_from_file_location("l1u", PY)
L1 = importlib.util.module_from_spec(spec); spec.loader.exec_module(L1)

FAIL = []
def ck(name, got, exp):
    ok = got == exp
    if not ok:
        FAIL.append(name)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}\n         got={got}\n         exp={exp}")

print("=" * 72)
print("A. _margin_need 口径分段")
print("=" * 72)
ck("2023-02-12 (NEEQ 开通前)", L1._margin_need("2023-02-12"), {"SSE", "SZSE"})
ck("2023-02-13 (NEEQ 开通日)", L1._margin_need("2023-02-13"), {"SSE", "SZSE", "NEEQ"})
ck("2010-03-31 (首日)", L1._margin_need("2010-03-31"), {"SSE", "SZSE"})

print()
print("=" * 72)
print("B. margin_complete_prefix 截断行为")
print("=" * 72)
def mk(rows):
    return pd.DataFrame([{"date": d, "exchange": e} for d, e in rows])

# B1 三所时期 全齐 → 不截断
d = mk([("2026-09-23", "SSE"), ("2026-09-23", "SZSE"), ("2026-09-23", "NEEQ"),
        ("2026-09-24", "SSE"), ("2026-09-24", "SZSE"), ("2026-09-24", "NEEQ")])
p, bad = L1.margin_complete_prefix(d)
ck("B1 全齐 → 无残缺", (len(p), bad), (6, []))

# B2 末日残缺(本次事故形态: 只有 SSE)
d = mk([("2026-09-23", "SSE"), ("2026-09-23", "SZSE"), ("2026-09-23", "NEEQ"),
        ("2026-09-24", "SSE")])
p, bad = L1.margin_complete_prefix(d)
ck("B2 末日残缺 → 截断至 09-23", (sorted(set(p["date"])), bad[0][0], sorted(bad[0][1])),
   (["2026-09-23"], "2026-09-24", ["NEEQ", "SZSE"]))

# B3 中间残缺 + 之后完整 → 必须截断在缺口(防永久空洞)
d = mk([("2026-09-22", "SSE"), ("2026-09-22", "SZSE"), ("2026-09-22", "NEEQ"),
        ("2026-09-23", "SSE"),
        ("2026-09-24", "SSE"), ("2026-09-24", "SZSE"), ("2026-09-24", "NEEQ")])
p, bad = L1.margin_complete_prefix(d)
ck("B3 中间残缺 → 截断至缺口前(不越过)", (sorted(set(p["date"])), bad[0][0]),
   (["2026-09-22"], "2026-09-23"))

# B4 两所时期 全齐 → 不截断(不得误伤历史)
d = mk([("2015-06-01", "SSE"), ("2015-06-01", "SZSE"),
        ("2015-06-02", "SSE"), ("2015-06-02", "SZSE")])
p, bad = L1.margin_complete_prefix(d)
ck("B4 两所时期全齐 → 不截断", (len(p), bad), (4, []))

# B5 两所时期 缺一所 → 截断
d = mk([("2015-06-01", "SSE"), ("2015-06-01", "SZSE"), ("2015-06-02", "SSE")])
p, bad = L1.margin_complete_prefix(d)
ck("B5 两所时期缺一所 → 截断", (sorted(set(p["date"])), bad[0][0]), (["2015-06-01"], "2015-06-02"))

# B6 全残缺 → 空
d = mk([("2026-09-24", "SSE")])
p, bad = L1.margin_complete_prefix(d)
ck("B6 全残缺 → 空集", (len(p), len(bad)), (0, 1))

# B7 空表
p, bad = L1.margin_complete_prefix(pd.DataFrame(columns=["date", "exchange"]))
ck("B7 空表 → 原样/无残缺", (len(p), bad), (0, []))

print()
print("=" * 72)
print("C. guard dup_key 回归(修复前: 同日多行被误报'日期重复')")
print("=" * 72)
prim_like = pd.DataFrame([
    {"date": "2026-09-24", "exchange": "SSE",  "margin_balance": 1.0, "margin_purchase": 1.0},
    {"date": "2026-09-24", "exchange": "SZSE", "margin_balance": 1.0, "margin_purchase": 1.0},
])
rng = {"margin_balance": (0.0, 5e12), "margin_purchase": (0.0, 1e13)}
try:
    L1.guard(prim_like, "prim", ["margin_balance", "margin_purchase"], rng, "date",
             dup_key=["date", "exchange"])
    ck("C1 dup_key=['date','exchange'] → 通过", "PASS", "PASS")
except Exception as e:
    ck("C1 dup_key=['date','exchange'] → 通过", f"RAISED {e}", "PASS")
try:
    L1.guard(prim_like, "prim", ["margin_balance", "margin_purchase"], rng, "date")
    ck("C2 缺省(仅按日期) → 报错(回归证明)", "NO-RAISE", "RAISED")
except ValueError:
    ck("C2 缺省(仅按日期) → 报错(回归证明)", "RAISED", "RAISED")

print()
print("=" * 72)
print("D. 交付物指纹")
print("=" * 72)
for f in [PY, "/root/l1_ops/repair_margin_0924.py", PRIM, DAILY]:
    p = Path(f)
    b = p.read_bytes()
    n = b.count(b"\n") + (0 if b.endswith(b"\n") else 1)
    print(f"  {Path(f).name:32s} sha256[:16]={hashlib.sha256(b).hexdigest()[:16]} "
          f"bytes={len(b)} lines={n}")

print()
print("=" * 72)
print("E. L0 CSV 现状")
print("=" * 72)
pr = pd.read_csv(PRIM, dtype=str); dl = pd.read_csv(DAILY, dtype=str)
T = "2026-09-24"
print(f"  primary {T}: {sorted(pr[pr['date']==T]['exchange'])} "
      f"(全表 {len(pr)} 行, 非齐全日 {sorted(set(pr.groupby('date')['exchange'].apply(len)) - {2,3})})")
print(f"  daily   {T}: {dl[dl['date']==T][['margin_balance','margin_purchase']].to_dict('records')}")
print(f"  daily 全表 {len(dl)} 行, 末日={dl['date'].iloc[-1]}")

if "--no-net" not in sys.argv:
    print()
    print("=" * 72)
    print("G. 源→聚合 数值断言(实源拉取, 自 09-23 起增量)")
    print("=" * 72)
    from datetime import date as _d
    p2, d2 = L1.collect_margin(_d(2026, 9, 23))
    print(f"  prim 行数={len(p2)}: {sorted(p2['exchange']) if len(p2) else []}")
    print(f"  daily 行数={len(d2)}: {d2.to_dict('records')}")
    src_rows = p2[p2["date"] == "2026-09-24"]
    exp_b = int(src_rows["margin_trade_balance"].astype(float).sum()) if len(src_rows) else None
    exp_p = int(src_rows["purchase_amt"].astype(float).sum()) if len(src_rows) else None
    got_b = int(d2[d2["date"] == "2026-09-24"]["margin_balance"].iloc[0]) if len(d2) else None
    got_p = int(d2[d2["date"] == "2026-09-24"]["margin_purchase"].iloc[0]) if len(d2) else None
    ck("G1 daily.margin_balance == 三所SUM", got_b, exp_b)
    ck("G2 daily.margin_purchase == 三所SUM", got_p, exp_p)
    print(f"  (L0 daily CSV 登记值={pd.read_csv(DAILY, dtype=str).query('date==\"2026-09-24\"')['margin_balance'].iloc[0]})")

    print()
    print("=" * 72)
    print("F. PG 现状")
    print("=" * 72)
    import psycopg2
    conn = psycopg2.connect(DSN); cur = conn.cursor()
    cur.execute("""SELECT indicator_id, period_date, announcement_date, vintage_date, value, status
                   FROM l1_observation WHERE indicator_id IN ('margin_balance','margin_purchase')
                     AND period_date >= '2026-09-23' ORDER BY indicator_id, period_date, vintage_date""")
    for r in cur.fetchall():
        print(f"  {r[0]:16s} {r[1]} ann={r[2]} vin={r[3]} value={float(r[4]):>18,.0f} {r[5]}")
    cur.execute("SELECT status, count(*) FROM l1_observation GROUP BY status")
    print("  status 分布:", dict(cur.fetchall()))
    cur.execute("SELECT count(*) FROM l1_observation")
    print("  总行数:", cur.fetchone()[0])
    conn.close()

print()
print("=" * 72)
print(f"汇总: 断言失败 {len(FAIL)} 项" + (f" → {FAIL}" if FAIL else " (全部通过)"))
print("=" * 72)
