# -*- coding: utf-8 -*-
"""精确核算 hs300 PE 2011-06-28~2012-09-03 区间: 交易日总数 vs 空洞(PE空值) vs 有值日
对照: 新浪收盘(sh000300, 完整日序列) + floatcap(申万A指交易日) 双源
"""
import pandas as pd
RAW = "/mnt/c/new_tdx64/PYPlugins/user/data/raw_data/"

# 1) 中证官方 PE 全量(重建前的完整序列重新拉取对账)
import akshare as ak
df = ak.stock_zh_index_hist_csindex(symbol='000300', start_date='20050101', end_date='20260921')
df['日期'] = pd.to_datetime(df['日期']).dt.strftime('%Y-%m-%d')
pe = df[['日期', '滚动市盈率']].rename(columns={'日期': 'date'})
# 列名: 滚动市盈率

# 2) 新浪收盘完整日序列
sina = ak.stock_zh_index_daily(symbol='sh000300')
sina['date'] = pd.to_datetime(sina['date']).dt.strftime('%Y-%m-%d')
sina = sina[['date', 'close']]

# 3) floatcap 交易日(申万A指, 权威交易日)
fc = pd.read_csv(RAW + "macro_floatcap_primary.csv")
fc['date'] = pd.to_datetime(fc['TRADE_DATE']).dt.strftime('%Y-%m-%d')

lo, hi = '2011-06-28', '2012-09-03'
for name, src in [("中证官方PE", pe), ("新浪收盘", sina), ("申万A指(交易日)", fc)]:
    sub = src[(src['date'] >= lo) & (src['date'] <= hi)]
    print(f"{name}: {len(sub)}行 {sub['date'].iloc[0]}~{sub['date'].iloc[-1]}")

# 中证官方 PE 在此区间
sub_pe = pe[(pe['date'] >= lo) & (pe['date'] <= hi)]
print(f"\n中证官方PE区间内: 总{len(sub_pe)}日, PE空值={sub_pe['滚动市盈率'].isna().sum()}, 有值={sub_pe['滚动市盈率'].notna().sum()}")
# 新浪收盘在该区间
sub_sina = sina[(sina['date'] >= lo) & (sina['date'] <= hi)]
print(f"新浪收盘区间内: 总{len(sub_sina)}日")
# 空洞 = 新浪有交易日但 PE 为空
m = sub_sina.merge(sub_pe, on='date', how='left')
holes = m[m['滚动市盈率'].isna()]
print(f"按新浪交易日: {len(m)}日, 其中PE空洞={holes['滚动市盈率'].isna().sum()} ({holes['滚动市盈率'].isna().sum()/len(m)*100:.1f}%)")
print(f"空洞日期: {holes['date'].tolist()}")
# 连续性: 空洞是否成段
d = pd.to_datetime(m['date']).reset_index(drop=True)
print(f"日期间隔: max间隔={d.diff().dt.days.max()}天")
# 有值日的分布(分段)
m2 = m.dropna(subset=['滚动市盈率'])
d2 = pd.to_datetime(m2['date']).reset_index(drop=True)
print(f"有值日最大间隔={d2.diff().dt.days.max()}天")
