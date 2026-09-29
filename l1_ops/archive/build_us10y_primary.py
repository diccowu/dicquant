#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""第8项 us10y 重建脚本 (macro_us10y_primary.csv)
口径: 美国10Y国债收益率(%), 单数据列 {date, us10y}; 起点 2010-01-04 与中债 treasury_y10 对齐(中美利差唯一消费方);
源 = akshare bond_zh_us_rate(东财中美国债收益率宽表), 取"美国国债收益率10年"列, 值域(0,10), 值保留2位小数。
可得时点: T日盘后(美国), lag=0自洽, 消费端恒T+1起usable(前视审查同 treasury_y10)。
重建动机: 2026-09-21 目录被QClaw卸载误删, 原数据不再信任, 直接拉新。
"""
import warnings

warnings.filterwarnings("ignore")
import os
import sys
import akshare as ak
import pandas as pd

SRC_START = "20100104"          # akshare 源参数, 后滤到 2010-01-04
ALIGN_START = "2010-01-04"      # 与 treasury_y10 对齐
VALUE_RANGE = (0.0, 10.0)       # 台账登记值域(us10y 实际 0.52~5.01)
OUT = "/mnt/c/new_tdx64/PYPlugins/user/data/raw_data/macro_us10y_primary.csv"

VAL_COL = "美国国债收益率10年"


def main():
    df = ak.bond_zh_us_rate(start_date=SRC_START)
    dcol = "日期" if "日期" in df.columns else df.columns[0]
    df = df[[dcol, VAL_COL]].copy()
    df.columns = ["date", "us10y"]
    df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    df["us10y"] = pd.to_numeric(df["us10y"], errors="coerce")
    df = df[df["date"] >= ALIGN_START]
    df = df.dropna(subset=["us10y"])
    df = df.drop_duplicates(subset=["date"], keep="last")
    df = df.sort_values("date").reset_index(drop=True)

    # —— 自检 ——
    n = len(df)
    mn, mx = df["us10y"].min(), df["us10y"].max()
    ok_val = (mn >= VALUE_RANGE[0]) and (mx <= VALUE_RANGE[1])
    ok_mono = df["date"].is_monotonic_increasing
    dup = df["date"].duplicated().sum()
    nan = df["us10y"].isna().sum()
    d0, d1 = df["date"].iloc[0], df["date"].iloc[-1]
    print(f"[自检] 行数={n} 区间={d0}~{d1}")
    print(f"[自检] min/max = {mn:.4f}/{mx:.4f}  值域({VALUE_RANGE[0]}, {VALUE_RANGE[1]}) 通过={ok_val}")
    print(f"[自检] 单调={ok_mono}  重复日期={dup}  NaN={nan}")
    if not (ok_val and ok_mono and dup == 0 and nan == 0):
        print("!! 自检未通过, 不落盘"); sys.exit(2)

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    df.to_csv(OUT, index=False)
    print(f"[落盘] {OUT}  ({n} 行)")
    import hashlib
    h = hashlib.sha256(open(OUT, "rb").read()).hexdigest()
    print(f"[sha256] {h}")


if __name__ == "__main__":
    main()