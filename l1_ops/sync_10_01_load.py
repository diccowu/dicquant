#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""10-01 扩源落库 阶段2: 读 parquet(/tmp/l1_expand/) → UPSERT PG l1_observation
隔离原因: 本进程不 import AmazingData(避免 GIL 崩溃)。"""
import importlib.util
import os
import sys
from pathlib import Path

import psycopg2

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
import l1_update as u

OUT = Path("/tmp/l1_expand")
PG_DSN = os.environ.get("L1_PG_DSN", u.PG_DEFAULT)

NEW_IDS = ["treasury_m6", "treasury_y2", "neer_cny", "dr007", "shibor_3m",
           "lpr_1y", "lpr_5y", "cbond_aaa_10y", "mkt_amount"]

def load_pit():
    spec = importlib.util.spec_from_file_location("pit_init", SCRIPT_DIR / "pit_init.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m

def main():
    pit = load_pit()
    plan = u.build_plan()
    ind_meta = {i[0]: i for i in pit.INDICATORS}
    conn = psycopg2.connect(PG_DSN)
    total = 0
    for iid in NEW_IDS:
        p = OUT / f"{iid}.parquet"
        if not p.exists():
            print(f"  {iid}: parquet 缺失, 跳过")
            continue
        new = __import__("pandas").read_parquet(p)
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
        print(f"  {iid}: 插入 {inserted}/{tot} (vc={vc})")
    # 验证
    with conn.cursor() as cur:
        cur.execute("SELECT indicator_id, count(*) FROM l1_observation "
                    "WHERE indicator_id = ANY(%s) GROUP BY 1 ORDER BY 1", (NEW_IDS,))
        for iid, cnt in cur.fetchall():
            print(f"  PG {iid}: {cnt} 行")
    conn.close()
    print(f"阶段2 完成 ✅ 累计插入 {total}")

if __name__ == "__main__":
    main()