#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""10-01 扩源落库自检: 9 新指标 PG 行数/值域/日期/发布日口径 vs pit_init 注册"""
import os, sys
from datetime import date, timedelta
sys.path.insert(0, "/root/l1_ops")
import l1_update as u
import psycopg2
import importlib.util

spec = importlib.util.spec_from_file_location("pit_init", "/root/l1_ops/pit_init.py")
pit = importlib.util.module_from_spec(spec); spec.loader.exec_module(pit)

NEW = {"treasury_m6":"m6","treasury_y2":"y2","neer_cny":"neer","dr007":"fdr007",
       "shibor_3m":"3M-定价","lpr_1y":"lpr1y","lpr_5y":"lpr5y",
       "cbond_aaa_10y":"aaa_10y","mkt_amount":"amount"}
# 期望: (起点, 终点, 值域上下界参考)  — 实测采集器输出
EXPECT = {
 "treasury_m6": (date(2010,1,4), date(2026,9,30), (0.0, 10.0)),
 "treasury_y2": (date(2010,1,4), date(2026,9,30), (0.0, 10.0)),
 "neer_cny":    (date(1994,1,1), date(2026,7,1),  (50.0, 160.0)),
 "dr007":       (date(2017,5,31), date(2026,9,30), (0.0, 8.0)),
 "shibor_3m":   (date(2015,5,8), date(2026,9,30), (0.0, 10.0)),
 "lpr_1y":      (date(2019,8,20), date(2026,9,20), (2.0, 6.0)),
 "lpr_5y":      (date(2019,8,20), date(2026,9,20), (2.0, 7.0)),
 "cbond_aaa_10y":(date(2011,1,4), date(2026,9,30), (1.0, 8.0)),
 "mkt_amount":  (date(2011,10,19), date(2026,9,30), (4.0e10, 5.0e13)),
}
# 发布日抽查: 各指标 (period_date → 期望 announcement_date)
ANN = {
 "treasury_m6": ("2026-09-30", "2026-09-30"),  # D lag=0 → 当日
 "neer_cny":    ("2026-07-01", "2026-08-30"),  # M lag=30 → 月末+30
 "lpr_1y":      ("2026-09-20", "2026-09-30"),  # M lag=0 → 期末(9-30)
 "dr007":       ("2026-09-30", "2026-09-30"),  # D lag=0
 "mkt_amount":  ("2026-09-30", "2026-09-30"),  # D lag=0
}

conn = psycopg2.connect(os.environ.get("L1_PG_DSN", u.PG_DEFAULT))
cur = conn.cursor()
all_ok = True
print(f"{'指标':<16}{'PG行数':>7}  {'起点':<11} {'终点':<11} {'min':>12} {'max':>12}  {'值域':<16}  {'结果':<6}")
for iid, vc in NEW.items():
    cur.execute("SELECT min(period_date), max(period_date), min(value), max(value), count(*) "
                "FROM l1_observation WHERE indicator_id=%s", (iid,))
    mn, mx, vmin, vmax, n = cur.fetchone()
    s, e, (lo, hi) = EXPECT[iid]
    # 值域用注册的 value_range (pit_init INDICATORS 末尾)
    vr = {i[0]: i[8] for i in pit.INDICATORS}.get(iid, (None, None))
    vlo, vhi = vr if vr else (lo, hi)
    ok = (n > 0 and mn == s and mx == e and vmin >= vlo - 1e-6 and vmax <= vhi + 1e-6)
    all_ok &= ok
    print(f"{iid:<16}{n:>7}  {str(mn):<11} {str(mx):<11} {vmin:>12.4g} {vmax:>12.4g}  "
          f"{str((vlo,vhi)):<16}  {'OK' if ok else 'FAIL'}")

print()
print("=== 发布日口径抽查 (period → announcement) ===")
for iid, (p, a) in ANN.items():
    cur.execute("SELECT period_date::text, announcement_date::text FROM l1_observation "
                "WHERE indicator_id=%s AND period_date::text=%s", (iid, p))
    r = cur.fetchone()
    ok = r and r[1] == a
    all_ok &= bool(ok)
    print(f"  {iid:<14} {p} → {r[1] if r else 'MISSING'} [期望 {a}] {'OK' if ok else 'FAIL'}")

cur.execute("SELECT count(*) FROM l1_indicator_meta")
n_meta = cur.fetchone()[0]
ok = n_meta == 27
all_ok &= ok
print(f"\nmeta 总数: {n_meta} (18+9=27 expect) {'OK' if ok else 'FAIL'}")
cur.execute("SELECT count(*) FROM l1_observation")
n_obs = cur.fetchone()[0]
print(f"observation 总数: {n_obs} (47,108 + 新增)")
conn.close()
print("\n结论:", "ALL PASS ✅" if all_ok else "FAIL ❌")
sys.exit(0 if all_ok else 2)
