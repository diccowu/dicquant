#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""第14项 usdcny 重建脚本 (macro_usdcny_primary.csv)
口径: USD/CNY 人民币兑美元中间价(元, 即 1 美元 = X 人民币), 单数据列 {date, usdcny};
源 = akshare currency_boc_safe() (SAFE 外汇管理局官方人民币中间价, 1994-01-01 至今 8054 行)。
单位: 源"美元"列以【100 外币兑人民币】计 (示例 870.0 = 8.70 元), 须 ÷100 恒等还原为 元/美元。
重建动机: 2026-09-21 目录被QClaw卸载误删, 原数据不再信任, 直接拉新。
已知源特性: 1994-06 并轨期历史有 14 天空洞(±0.15 元区间, 官方历史早期数据缺失), 属源固有缺口, 不填充(PIT 红线禁 bfill)。
"""
import os
import sys
import hashlib
import warnings
warnings.filterwarnings("ignore")

import akshare as ak
import pandas as pd

OUT = "/mnt/c/new_tdx64/PYPlugins/user/data/raw_data/macro_usdcny_primary.csv"
SCALE = 100.0          # 源单位 100外币兑人民币 → 元/美元 的恒等还原系数
VAL_COL = "美元"
VALUE_RANGE = (6.0, 9.0)   # 元/美元 台账登记值域(实际 6.093~8.71)


def main():
    df = ak.currency_boc_safe()
    dcol = "日期" if "日期" in df.columns else df.columns[0]
    df = df[[dcol, VAL_COL]].copy()
    df.columns = ["date", "usdcny"]
    df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    df["usdcny"] = pd.to_numeric(df["usdcny"], errors="coerce") / SCALE
    df = df.dropna(subset=["usdcny"])
    df = df.drop_duplicates(subset=["date"], keep="last")
    df = df.sort_values("date").reset_index(drop=True)

    # —— 自检 ——
    n = len(df)
    mn, mx = df["usdcny"].min(), df["usdcny"].max()
    ok_val = (mn >= VALUE_RANGE[0]) and (mx <= VALUE_RANGE[1])
    ok_mono = df["date"].is_monotonic_increasing
    dup = df["date"].duplicated().sum()
    nan = df["usdcny"].isna().sum()
    d0, d1 = df["date"].iloc[0], df["date"].iloc[-1]
    print(f"[自检] 行数={n} 区间={d0}~{d1}")
    print(f"[自检] min/max = {mn:.4f}/{mx:.4f}  值域({VALUE_RANGE[0]}, {VALUE_RANGE[1]}) 通过={ok_val}")
    print(f"[自检] 单调={ok_mono}  重复日期={dup}  NaN={nan}")
    if not (ok_val and ok_mono and dup == 0 and nan == 0):
        print("!! 自检未通过, 不落盘"); sys.exit(2)

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    df.to_csv(OUT, index=False)
    print(f"[落盘] {OUT}  ({n} 行)")
    h = hashlib.sha256(open(OUT, "rb").read()).hexdigest()
    print(f"[sha256] {h}")


if __name__ == "__main__":
    main()