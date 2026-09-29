# -*- coding: utf-8 -*-
"""oil 深度自查 (2026-09-24 第19项)
V1 结构 / V2 指纹 / V3 编码 / V4 值域 / V5 锚点 / V6 逻辑(同比自洽) / V7 完整性(交易日)
"""
import hashlib, pandas as pd
from pathlib import Path
RAW = Path('/mnt/c/new_tdx64/PYPlugins/user/data/raw_data')

d = pd.read_csv(RAW / 'brent_fred_daily.csv')
m = pd.read_csv(RAW / 'macro_oil_monthly.csv')

print(f"V1 日频结构: {len(d)}行 {d['date'].iloc[0]}~{d['date'].iloc[-1]} 列={list(d.columns)} 空值={d.isna().sum().sum()} 唯一={d['date'].is_unique} 递增={pd.to_datetime(d['date']).is_monotonic_increasing}")
print(f"V1 月频结构: {len(m)}行 {m['ym'].iloc[0]}~{m['ym'].iloc[-1]} 列={list(m.columns)} 空值={m.isna().sum().sum()}")

for f in ['brent_fred_daily.csv', 'macro_oil_monthly.csv']:
    h = hashlib.sha256((RAW/f).read_bytes()).hexdigest()
    print(f"V2 指纹 {f}: {h}")

head = (RAW/'brent_fred_daily.csv').read_bytes()[:3]
print(f"V3 编码日频: 首3字节={head.hex()} ({'有BOM' if head==b'\\xef\\xbb\\xbf' else '无BOM'})")
head = (RAW/'macro_oil_monthly.csv').read_bytes()[:3]
print(f"V3 编码月频: 首3字节={head.hex()} ({'有BOM' if head==b'\\xef\\xbb\\xbf' else '无BOM'})")

print(f"V4 日频值域: min={d['brent'].min():.2f} max={d['brent'].max():.2f} mean={d['brent'].mean():.2f}")
print(f"V4 月频值域: avg min={m['oil_month_avg'].min():.2f} max={m['oil_month_avg'].max():.2f} | yoy min={m['oil_yoy'].min():.1f}% max={m['oil_yoy'].max():.1f}%")

print("V5 锚点:")
for a in ['2008-07-03', '1998-12-10', '2020-04-20', '2022-03-08', '2026-09-22']:
    r = d[d['date']==a]
    print(f"   {a}: brent={r.iloc[0]['brent'] if len(r) else '无'}")

# V6 同比自洽: 逐月重算
m2 = m.copy()
m2['ym_dt'] = pd.to_datetime(m2['ym'])
m2 = m2.sort_values('ym_dt').reset_index(drop=True)
calc = m2['oil_month_avg'].pct_change(12)*100
diff = (calc - m2['oil_yoy']).abs().max()
print(f"V6 同比自洽: 逐月重算 vs 文件最大差={diff:.6f} (expect 0)")

# V7 完整性: 月份连续性(1988-05起 有同比 逐月连续?)
mm = m[m['oil_yoy'].notna()].copy()
mm['ym_dt'] = pd.to_datetime(mm['ym'])
gaps = mm['ym_dt'].diff().dt.days
print(f"V7 月频连续性(有同比段): {len(mm)}月, 最大间隔={gaps.max()}天 (expect<=31,即逐月无缺)")

# 交易日均值重算抽查: 2026-09
sep = d[(d['date']>='2026-09-01')&(d['date']<='2026-09-30')]
avg_calc = sep['brent'].mean()
avg_file = m[m['ym']=='2026-09']['oil_month_avg'].iloc[0]
print(f"V6b 月均值重算 2026-09: 文件={avg_file:.4f} vs 重算={avg_calc:.4f} 差={abs(avg_file-avg_calc):.6f}")
