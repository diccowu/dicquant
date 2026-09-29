# -*- coding: utf-8 -*-
"""定位 2011-06-28 后的 66 个空值分布"""
import pandas as pd
p = "/mnt/c/new_tdx64/PYPlugins/user/data/raw_data/macro_hs300_pe_primary.csv"
df = pd.read_csv(p)
first = df['pe_ttm'].first_valid_index()
after = df.loc[first:].copy()
gaps = after[after['pe_ttm'].isna()]
print(f"2011-06-28 后空值 {len(gaps)} 处:")
print(gaps['date'].tolist())
# 按年分布
gaps['yr'] = pd.to_datetime(gaps['date']).dt.year
print("\n按年:", gaps.groupby('yr').size().to_dict())
# 找最大连续空洞
d = pd.to_datetime(after['date']).reset_index(drop=True)
mask = after['pe_ttm'].isna().reset_index(drop=True)
# 连续空值段
runs = []
start = None
for i, m in enumerate(mask):
    if m and start is None:
        start = i
    elif not m and start is not None:
        runs.append((start, i-1)); start = None
if start is not None: runs.append((start, len(mask)-1))
print(f"\n连续空值段 {len(runs)} 个:")
for s, e in runs:
    print(f"  {after['date'].iloc[s]} ~ {after['date'].iloc[e]} ({e-s+1}天)")
# 最后一个空值
last_gap = gaps['date'].iloc[-1]
print(f"\n最后一个空值日: {last_gap}")
# 完全无空值的起点(最后一个空值之后)
after_last = after[after['date'] > last_gap]
print(f"最后空值之后: {len(after_last)}行, 空值={after_last['pe_ttm'].isna().sum()}, 起={after_last['date'].iloc[0]}")
