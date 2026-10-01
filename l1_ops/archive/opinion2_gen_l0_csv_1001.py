#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""意见②处置:9 项新指标 L0 原始层 CSV 首装即落
背景:infomana v1 意见② + 事实核查
  - 日更 l1_daily.sh 走 --state-from pg → write_csv=False → CSVI 永不写(infomana 误判)
  - L0 层(14 文件)在 Windows 恢复区;9 新指标缺 5 文件(实际 4 个,treasury 宽表已含 m6/y2)
  - 红线:不直接写 /mnt/c → 生成到 Linux 暂存 /root/l1_ops/l0_staging_1001/ 供用户复制
输出:暂存目录内 CSV,列名与 pit_init value_col 严格一致
"""
import pandas as pd, pathlib, sys

STAGE = pathlib.Path("/root/l1_ops/l0_staging_1001")
STAGE.mkdir(parents=True, exist_ok=True)

# 指标 → (parquet, 输出文件, 保留列)
JOBS = [
    ("neer_cny",      "/tmp/l1_expand/neer_cny.parquet",      "macro_neer_fred_primary.csv",  ["date", "neer"]),
    ("dr007",         "/tmp/l1_expand/dr007.parquet",         "macro_dr007_primary.csv",       ["date", "fdr007"]),
    ("shibor_3m",     "/tmp/l1_expand/shibor_3m.parquet",     "macro_shibor_primary.csv",      ["date", "3M-定价"]),
    ("lpr_1y+lpr_5y", "/tmp/l1_expand/lpr_1y.parquet",        "macro_lpr_primary.csv",         ["date", "lpr1y", "lpr5y"]),
    ("cbond_aaa_10y", "/tmp/l1_expand/cbond_aaa_10y.parquet", "macro_bond_aaa_primary.csv",    ["date", "aaa_10y"]),
]

report = []
for name, src, fname, cols in JOBS:
    df = pd.read_parquet(src)
    assert [c for c in df.columns if c in cols] == cols, f"{name} 列不匹配: {list(df.columns)}"
    out = df[cols].copy()
    out.to_csv(STAGE / fname, index=False, encoding="utf-8")
    # 数值摘要
    val = [c for c in cols if c != "date"][0]
    n = len(out)
    lo, hi = out[val].min(), out[val].max()

    report.append(f"{fname:35s} {n:>6} 行  {val}={lo}~{hi}")

print("\n".join(report))
print(f"---落盘目录: {STAGE}")
for p in sorted(STAGE.iterdir()):
    print(f"  {p.name}  {p.stat().st_size}B")