#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""10-01 扩源落库 阶段1: 采集 9 指标 → parquet(/tmp/l1_expand/)
阶段2 (sync_10_01_expand_load.py) 单独进程读 parquet 落 PG。
隔离原因: AmazingData SDK 与 psycopg2 同进程触发 GIL 崩溃(PyEval_SaveThread)。"""
import importlib.util
import os
import sys
from datetime import date
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
import l1_update as u

OUT = Path("/tmp/l1_expand")
OUT.mkdir(parents=True, exist_ok=True)

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
    for iid in NEW_IDS:
        engine = plan[iid]["engine"]
        since = None
        try:
            new = u.run_collector(engine, since)
        except Exception as e:
            print(f"  {iid}: 采集失败 {type(e).__name__}: {e}")
            continue
        if new is None or len(new) == 0:
            print(f"  {iid}: 空, 跳过")
            continue
        dcol = plan[iid].get("date_col", "date")
        vc = ind_meta[iid][7]
        if vc is None:
            cand = [c for c in new.columns if c != dcol]
            vc = cand[0] if len(cand) == 1 else None
        p = OUT / f"{iid}.parquet"
        new.to_parquet(p, index=False)
        print(f"  {iid}: {len(new)} 行 → {p} (dcol={dcol}, vc={vc})")
    print("阶段1 完成 ✅ (parquet 于 /tmp/l1_expand/)")

if __name__ == "__main__":
    main()