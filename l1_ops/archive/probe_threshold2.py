#!/usr/bin/env python3
"""定阈值: 限成熟期(2015+)后, 对比成交量指标的极端偏离阈值"""
import pandas as pd

DAILY = "/mnt/c/new_tdx64/PYPlugins/user/data/raw_data/macro_margin_ad_daily.csv"
dl = pd.read_csv(DAILY)
dl["date"] = dl["date"].astype(str)
mature = dl.date >= "2015-01-01"

for col in ["margin_balance", "margin_purchase"]:
    s = dl[col].astype(float)
    med20 = s.rolling(20, min_periods=5).median()
    dev = (s / med20 - 1).abs()
    print(f"\n{col}  (成熟期 2015+, 共 {int(mature.sum())} 日)")
    for t in [0.20, 0.30, 0.40, 0.50, 1.00, 1.50, 2.00, 3.00, 4.00]:
        n = int((dev[mature] > t).sum())
        flag = "✅零误报" if n == 0 else ""
        print(f"  dev20 > {t*100:>5.0f}% → {n:>4d} 日  {flag}")
    # 列出 1.0 以上的日期看可解释性
    idx = dev[mature & (dev > 1.0)].index
    if len(idx):
        print("    >100% 日期: " + ", ".join(f"{dl.date[i]}({dev[i]*100:.0f}%)" for i in idx[:8]))
    # 事故检出
    i = dl.index[dl.date == "2026-09-24"][0]
    fake = s.copy(); fake[i] = 1350506223746.0
    fdev = (fake / fake.rolling(20, min_periods=5).median() - 1).abs()
    print(f"  ★ 残缺态检出 dev20 = {fdev[i]*100:.0f}%")
