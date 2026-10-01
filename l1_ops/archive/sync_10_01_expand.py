#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""10-01 扩源落库: 同步 9 个新指标到 PG l1_indicator_meta + l1_observation

只做一次性迁移(新指标此前不在 PG); 之后日常更新走 l1_update.py --all --state-from pg。
幂等: meta INSERT ON CONFLICT DO UPDATE; observation 走 upsert_pg(主键防重)。
"""
import importlib.util
import os
import sys
from datetime import date
from pathlib import Path

import pandas as pd
import psycopg2

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
import l1_update as u

PG_DSN = os.environ.get("L1_PG_DSN", u.PG_DEFAULT)
NEW_IDS = ["treasury_m6", "treasury_y2", "neer_cny", "dr007", "shibor_3m",
           "lpr_1y", "lpr_5y", "cbond_aaa_10y", "mkt_amount"]

# 1. meta 同步 (从 pit_init 单一事实源)
def load_pit():
    spec = importlib.util.spec_from_file_location("pit_init", SCRIPT_DIR / "pit_init.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m

def sync_meta(conn, pit, new_ids):
    n = 0
    with conn.cursor() as cur:
        for ind in pit.INDICATORS:
            iid, raw_file, freq, sa, meth, lag, src, _vcol, _vrange = ind
            if iid not in new_ids:
                continue
            cur.execute(
                "INSERT INTO l1_indicator_meta "
                "(indicator_id, raw_file, freq, sa_flag, methodology, release_lag_days, source, description) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT (indicator_id) DO UPDATE SET "
                "raw_file=EXCLUDED.raw_file, freq=EXCLUDED.freq, sa_flag=EXCLUDED.sa_flag, "
                "methodology=EXCLUDED.methodology, release_lag_days=EXCLUDED.release_lag_days, "
                "source=EXCLUDED.source, description=EXCLUDED.description",
                [iid, raw_file, freq, sa, meth, lag, src, meth])
            n += 1
    conn.commit()
    return n

def main():
    pit = load_pit()
    conn = psycopg2.connect(PG_DSN)
    # 1) meta
    n = sync_meta(conn, pit, NEW_IDS)
    print(f"[1/3] meta 同步: {n} 指标 (ON CONFLICT 幂等)")
    # 2) 采集 9 指标 (复用 l1_update 的采集器)
    plan = u.build_plan()
    ind_meta = {i[0]: i for i in pit.INDICATORS}
    total = 0
    for iid in NEW_IDS:
        engine = plan[iid]["engine"]
        since = None  # 新指标: 全量
        new = u.run_collector(engine, since)
        if new is None or len(new) == 0:
            print(f"  {iid}: 空, 跳过")
            continue
        dcol = plan[iid].get("date_col", "date")
        vc = ind_meta[iid][7]
        if vc is None:
            cand = [c for c in new.columns if c != dcol]
            vc = cand[0] if len(cand) == 1 else None
        if vc is None or vc not in new.columns:
            print(f"  {iid}: value_col={vc} 不可用, 跳过")
            continue
        inserted, tot = u.upsert_pg(conn, iid, new, pit, vc, dcol, dry_run=False)
        total += inserted
        print(f"  {iid}: 插入 {inserted}/{tot} 行 (value_col={vc})")
    print(f"[2/3] 数据落库完成: 累计插入 {total} 行")
    # 3) 验证
    with conn.cursor() as cur:
        cur.execute("SELECT indicator_id, count(*) FROM l1_observation "
                    "WHERE indicator_id = ANY(%s) GROUP BY 1 ORDER BY 1", (NEW_IDS,))
        for iid, cnt in cur.fetchall():
            print(f"  PG 现况 {iid}: {cnt} 行")
        cur.execute("SELECT count(*) FROM l1_indicator_meta")
        print(f"[3/3] meta 总数: {cur.fetchone()[0]}")
    conn.close()
    print("完成 ✅")

if __name__ == "__main__":
    main()
