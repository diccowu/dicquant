# -*- coding: utf-8 -*-
"""hs300_pe_ttm 深度自查 (2026-09-24 第18项)
V1 结构 / V2 指纹 / V3 编码 / V4 值域 / V5 锚点 / V6 逻辑(异源) / V7 完整性
"""
import hashlib, subprocess, pandas as pd
from pathlib import Path
RAW = Path('/mnt/c/new_tdx64/PYPlugins/user/data/raw_data')
F = RAW / 'macro_hs300_pe_primary.csv'

df = pd.read_csv(F)
print(f"V1 结构: {len(df)}行 {df['date'].iloc[0]}~{df['date'].iloc[-1]} 列={list(df.columns)} 空值={df.isna().sum().sum()} 唯一={df['date'].is_unique} 递增={pd.to_datetime(df['date']).is_monotonic_increasing}")

h = hashlib.sha256(F.read_bytes()).hexdigest()
print(f"V2 指纹: sha256={h}")

head = F.read_bytes()[:3]
print(f"V3 编码: 首3字节={head.hex()} → {'有BOM' if head==b'\\xef\\xbb\\xbf' else '无BOM(UTF-8)'}")

print(f"V4 值域: min={df['pe_ttm'].min():.2f} max={df['pe_ttm'].max():.2f} mean={df['pe_ttm'].mean():.2f}")

for a in ['2012-09-04', '2015-06-15', '2018-12-31', '2020-01-02', '2021-02-18', '2026-09-21']:
    r = df[df['date'] == a]
    print(f"V5 锚点 {a}: PE={r.iloc[0]['pe_ttm'] if len(r) else '无'}")

# 2012-09-04 后交易日 vs 申万A指交易日(权威日历)
fc = pd.read_csv(RAW / 'macro_floatcap_primary.csv')
fc['d'] = pd.to_datetime(fc['TRADE_DATE']).dt.strftime('%Y-%m-%d')
fc = fc[fc['d'] >= '2012-09-04']
missing = set(fc['d']) - set(df['date'])
print(f"V7 完整性: 对照申万A指 {len(fc)}交易日, PE缺失日={len(missing)} {sorted(missing)[:10] if missing else ''}")

# 异源: 新浪收盘重拉(不写入)
import akshare as ak
sina = ak.stock_zh_index_daily(symbol='sh000300')
sina['date'] = pd.to_datetime(sina['date']).dt.strftime('%Y-%m-%d')
sina = sina[['date', 'close']]
cs = ak.stock_zh_index_hist_csindex(symbol='000300', start_date='20120904', end_date='20260921')
cs['日期'] = pd.to_datetime(cs['日期']).dt.strftime('%Y-%m-%d')
cs = cs[['日期', '收盘']].rename(columns={'日期': 'date', '收盘': 'close'})
m = cs.merge(sina, on='date', suffixes=('_cs', '_sina'))
diff = (m['close_cs'] - m['close_sina']).abs()
print(f"V6 异源对照: 共同{len(m)}日, 最大差={diff.max():.4f}, 均值差={diff.mean():.4f}, 相对最大={((m['close_cs']-m['close_sina']).abs()/m['close_cs']*100).max():.3f}%")
