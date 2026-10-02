#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""意见④校验:staging 5 CSV ↔ PG 实物逐项比对(只读)"""
import pandas as pd, glob, subprocess, os

PG_ARGS = ["-h", "100.76.208.125", "-p", "5432", "-U", "postgres", "-d", "quant"]

def pg_rows(ind):
    q = f"SELECT count(*), min(value), max(value) FROM l1_observation WHERE indicator_id='{ind}'"
    env = dict(os.environ)
    env["PGCONNECT_TIMEOUT"] = "60"
    env["PGPASSWORD"] = os.environ.get("QUANT_PG_PASSWORD", "")
    r = subprocess.run(["psql", *PG_ARGS, "-t", "-A", "-F", "|", "-c", q],
                       capture_output=True, text=True, timeout=180, env=env)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip()[:160])
    c, mn, mx = r.stdout.strip().split("|")
    return (int(c), float(mn), float(mx))

MAP = [
    ("neer_cny",      "/root/l1_ops/l0_staging_1001/macro_neer_fred_primary.csv", "neer"),
    ("dr007",         "/root/l1_ops/l0_staging_1001/macro_dr007_primary.csv",      "fdr007"),
    ("shibor_3m",     "/root/l1_ops/l0_staging_1001/macro_shibor_primary.csv",     "shibor_3m"),
    ("lpr_1y",        "/root/l1_ops/l0_staging_1001/macro_lpr_primary.csv",        "lpr1y"),
    ("lpr_5y",        "/root/l1_ops/l0_staging_1001/macro_lpr_primary.csv",        "lpr5y"),
    ("cbond_aaa_10y", "/root/l1_ops/l0_staging_1001/macro_bond_aaa_primary.csv",   "aaa_10y"),
]

lines = []
for ind, fpath, col in MAP:
    df = pd.read_csv(fpath)
    # 与 PG 比对(6 指标)
    try:
        pgc, pgmn, pgmx = pg_rows(ind)
        csv_n = len(df); csv_min = float(df[col].min()); csv_max = float(df[col].max())
        ok_n = (pgc == csv_n); ok_r = (abs(pgmn - csv_min) < 1e-9 and abs(pgmx - csv_max) < 1e-9)
        lines.append(f"{ind:14s} CSV={csv_n:6d} ({csv_min}~{csv_max}) | PG={pgc:6d} ({pgmn}~{pgmx}) | 行数{'✅' if ok_n else '❌'} 值域{'✅' if ok_r else '❌'}")
    except Exception as e:
        lines.append(f"{ind:14s} PG 查询失败: {e}")

res = "\n".join(lines)
open("/tmp/opinion4_verify.txt", "w").write(res)
print(res)