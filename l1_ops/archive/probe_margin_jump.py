#!/usr/bin/env python3
"""实测两融日变动分布, 用数据定连续性阈值(替代拍脑袋的 10%)"""
import pandas as pd

DAILY = "/mnt/c/new_tdx64/PYPlugins/user/data/raw_data/macro_margin_ad_daily.csv"
dl = pd.read_csv(DAILY)
dl["date"] = dl["date"].astype(str)

print("=== 全历史 pct_change 分位数 ===")
for col in ["margin_balance", "margin_purchase"]:
    s = dl[col].astype(float)
    p = s.pct_change().abs().dropna()
    print(f"\n{col}:")
    for q in [0.5, 0.9, 0.99, 0.999, 1.0]:
        print(f"  {q*100:>6.1f}% 分位 |Δ|/前值 = {p.quantile(q):.4f} ({p.quantile(q)*100:.2f}%)")
    print(f"  超 10% 天数: {int((p>0.10).sum())} / {len(p)}")
    print(f"  超 20% 天数: {int((p>0.20).sum())} / {len(p)}")
    print(f"  超 30% 天数: {int((p>0.30).sum())} / {len(p)}")
    print(f"  超 40% 天数: {int((p>0.40).sum())} / {len(p)}")
    top = p.nlargest(5)
    print("  最大5个变动:")
    for i, v in top.items():
        print(f"    {dl.date[i]}  {v*100:.2f}%  值={s[i]:,.0f}  前值={s[i-1]:,.0f}")

print()
print("=== 近一年(2025-09-28 起)分布 ===")
recent = dl[dl.date >= "2025-09-28"]
for col in ["margin_balance", "margin_purchase"]:
    s = recent[col].astype(float)
    p = s.pct_change().abs().dropna()
    print(f"  {col}: max={p.max()*100:.2f}%  p99={p.quantile(0.99)*100:.2f}%  超10%={int((p>0.10).sum())}/{len(p)}")

print()
print("=== 本次事故(09-24 残缺态)的变动幅度 ===")
s = dl["margin_balance"].astype(float)
i = dl.index[dl.date == "2026-09-24"][0]
print(f"  修正后 09-24 = {s[i]:,.0f}  (前值 09-23 = {s[i-1]:,.0f}) → 变动 {abs(s[i]/s[i-1]-1)*100:.2f}%")
print(f"  若为残缺态 1,350,506,223,746 → 变动 {abs(1350506223746/s[i-1]-1)*100:.2f}%")
