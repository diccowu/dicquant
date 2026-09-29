#!/usr/bin/env python3
"""流量指标 margin_purchase: 成熟期 dev20 最大值, 用于定"极端异常"阈值"""
import pandas as pd

DAILY = "/mnt/c/new_tdx64/PYPlugins/user/data/raw_data/macro_margin_ad_daily.csv"
dl = pd.read_csv(DAILY)
dl["date"] = dl["date"].astype(str)
s = dl["margin_purchase"].astype(float)
med20 = s.rolling(20, min_periods=5).median()
dev = (s / med20 - 1).abs()
mature = dl.date >= "2015-01-01"

top = dev[mature].nlargest(8)
print("成熟期(2015+) dev20 最大的 8 天:")
for i, v in top.items():
    print(f"  {dl.date[i]}  dev={v*100:>7.1f}%   值={s[i]:,.0f}  20日中位={med20[i]:,.0f}")

mx = top.max()
print(f"\n成熟期最大正常偏离 = {mx*100:.1f}%")
print(f"残缺态检出偏离     = 701%")
for t in [5.0, 6.0, 7.0, 8.0]:
    n = int((dev[mature] > t).sum())
    ok = "✅零误报 + ✅抓得住701%" if n == 0 and 7.01 > t else ("零误报" if n == 0 else f"{n}日误报")
    print(f"  阈值 > {t*100:.0f}% → 误报 {n} 日  {ok}")
