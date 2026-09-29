#!/usr/bin/env python3
"""评估 purchase/balance 比例断言价值 + 确认"完整性能抓住本次事故" """
import pandas as pd

DAILY = "/mnt/c/new_tdx64/PYPlugins/user/data/raw_data/macro_margin_ad_daily.csv"
dl = pd.read_csv(DAILY)
dl["date"] = dl["date"].astype(str)
ratio = dl["margin_purchase"].astype(float) / dl["margin_balance"].astype(float)

print("=== purchase/balance 比例分布 ===")
for q in [0.0, 0.01, 0.05, 0.5, 0.95, 0.99, 1.0]:
    print(f"  {q*100:>5.1f}% 分位 = {ratio.quantile(q)*100:>7.3f}%")
mature = dl.date >= "2015-01-01"
print(f"  成熟期(2015+): min={ratio[mature].min()*100:.3f}%  max={ratio[mature].max()*100:.3f}%")
print(f"  09-24 修正后 = {ratio[dl.date=='2026-09-24'].iloc[0]*100:.3f}%")
print(f"  09-24 残缺态 = {77396224473/1350506223746*100:.3f}%   ← 与修正后几乎相同 → 抓不住")
print()
print("=== 关键: 完整性断言的检出力(本次事故) ===")
prim = pd.read_csv("/mnt/c/new_tdx64/PYPlugins/user/data/raw_data/macro_margin_ad_primary.csv")
prim["date"] = prim["date"].astype(str)
cnt = prim.groupby("date")["exchange"].apply(lambda s: len(set(s)))
print(f"  现状: 三所期(<2023-02-13 之后) 非3所日 = {sorted(cnt[(cnt.index>='2023-02-13') & (cnt!=3)].to_dict().items())}  → 0 即健康")
print("  若 09-24 残缺(只有SSE): cnt['2026-09-24']=1 → 断言 FAIL ✅ 直接命中")
print("  聚合层无残缺日断言: 09-24 在聚合层但 primary 不齐 → FAIL ✅ 直接命中")
