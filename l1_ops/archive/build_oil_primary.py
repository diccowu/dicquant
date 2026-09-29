#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""oil 布伦特原油建源 (2026-09-24, 第19项; 用户指示: 重拉覆盖 + 机构口径)
源: FRED DCOILBRENTEU (EIA官方布伦特即期现货, 日收盘, 美元/桶, 1987-05-20~今)
产出:
  data/raw_data/brent_fred_daily.csv      {date, brent}  日频 (FRED原始, 零加工)
  data/raw_data/macro_oil_monthly.csv     {date, oil_month_avg, oil_yoy}  月频(交易日均值) + 同比
口径(用户 2026-09-24 确认, 机构调研带出处):
  - 月度均值 = 自然月内交易日收盘均值 (CF40"价格中枢", 华创"结算价月同比")
  - 同比 = 月均值 yoy (申万 PPI回归用, R²≈94%)
用途: PPI先行预测列, 领先1~2期 (华创领先1期/北理工≈2期), 不进独立百分位打分
编码: UTF-8 无 BOM (日频惯例)
"""
import urllib.request, csv, io, hashlib, sys
import pandas as pd
from pathlib import Path

RAW = Path('/mnt/c/new_tdx64/PYPlugins/user/data/raw_data')
RAW.mkdir(parents=True, exist_ok=True)

# ---- 1. FRED 全量拉取 DCOILBRENTEU (1960-01-01 ~ 2026-12-31 覆盖全长) ----
url = ("https://fred.stlouisfed.org/graph/fredgraph.csv?id=DCOILBRENTEU"
       "&cosd=1987-01-01&coed=2026-12-31")
raw = urllib.request.urlopen(url, timeout=90).read().decode()
rows = []
for ln in raw.splitlines()[1:]:
    if not ln.strip():
        continue
    d, v = ln.split(",")
    if v and v != ".":
        rows.append((d.strip(), float(v.strip())))
print(f"FRED 原始行数: {len(rows)}  {rows[0][0]} ~ {rows[-1][0]}")

df = pd.DataFrame(rows, columns=["date", "brent"])
df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
assert df["date"].is_unique, "日期不唯一!"
assert pd.to_datetime(df["date"]).is_monotonic_increasing, "日期不递增!"
assert df["brent"].notna().all(), "有NaN!"

# ---- 2. 写日频源文件 (零加工) ----
df.to_csv(RAW / "brent_fred_daily.csv", index=False)

# ---- 3. 月度均值 = 自然月内交易日收盘均值 ----
m = df.copy()
m["ym"] = pd.to_datetime(m["date"]).dt.strftime("%Y-%m")
monthly_avg = m.groupby("ym")["brent"].mean().reset_index()
print(f"\n月频(交易日均值): {len(monthly_avg)}个月  {monthly_avg['ym'].iloc[0]} ~ {monthly_avg['ym'].iloc[-1]}")

# ---- 4. 同比 = 月均值 yoy (12个月前同月均值) ----
monthly_avg["ym_dt"] = pd.to_datetime(monthly_avg["ym"])
monthly_avg = monthly_avg.sort_values("ym_dt").reset_index(drop=True)
monthly_avg["oil_yoy"] = monthly_avg["brent"].pct_change(12) * 100
monthly_avg = monthly_avg.rename(columns={"brent": "oil_month_avg"})
monthly_avg = monthly_avg[["ym", "oil_month_avg", "oil_yoy"]]
yoys = monthly_avg["oil_yoy"].dropna()
print(f"同比可用: {len(yoys)}个月 (首个有同比: {monthly_avg.loc[monthly_avg['oil_yoy'].notna(), 'ym'].iloc[0]})")
print(f"同比区间: min={yoys.min():.1f}% max={yoys.max():.1f}%")
print(f"本月均值: {monthly_avg.iloc[-1]['ym']} = {monthly_avg.iloc[-1]['oil_month_avg']:.2f} 同比={monthly_avg.iloc[-1]['oil_yoy']:.2f}%")

# ---- 5. 写月频文件 (用户策略"从无空值起点开始": 截断至首个有同比月) ----
mo = monthly_avg[["ym", "oil_month_avg", "oil_yoy"]].dropna(subset=["oil_yoy"]).reset_index(drop=True)
assert mo["oil_yoy"].notna().all(), "截断后仍有空值!"
assert mo["oil_month_avg"].notna().all(), "月均值有空值!"
print(f"月频截断: {len(monthly_avg)}月 → {len(mo)}月 (首个有同比: {mo['ym'].iloc[0]})")
mo.to_csv(RAW / "macro_oil_monthly.csv", index=False)

# ---- 6. 指纹 ----
for f in ["brent_fred_daily.csv", "macro_oil_monthly.csv"]:
    h = hashlib.sha256((RAW / f).read_bytes()).hexdigest()
    print(f"SHA256({f}) = {h[:16]}...")

# ---- 7. 锚点(数据驱动: 序列极值 + 近月, 不预设期望值) ----
print("\n锚点(实测极值):")
imax = df["brent"].idxmax(); imin = df["brent"].idxmin()
print(f"  历史最高: {df.loc[imax,'date']} = {df.loc[imax,'brent']}")
print(f"  历史最低: {df.loc[imin,'date']} = {df.loc[imin,'brent']}")
print(f"  首日: {df.iloc[0]['date']} = {df.iloc[0]['brent']}   末日: {df.iloc[-1]['date']} = {df.iloc[-1]['brent']}")
print(f"  近5交易日: {df.tail(5)[['date','brent']].to_dict('records')}")