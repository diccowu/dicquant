# -*- coding: utf-8 -*-
"""重建 hs300_pe_ttm (2026-09-24, 第18项, 用户指示: 从无空值起点开始)
源: akshare 中证官方 stock_zh_index_hist_csindex('000300') (滚动市盈率)
    新浪 stock_zh_index_daily('sh000300') 收盘 作异源对照(仅验证,不写入)
策略(用户 2026-09-24 定): **从无空值起点截断** —— 丢弃 2005-01~最后一个PE空值日(2012-09-03)前段,
     文件从 2012-09-04 起(实测最后一个空值=2012-09-03,之后 3412 行零空值)
编码: UTF-8 无 BOM(to_csv 默认) —— 日频惯例(与 shrzgm/margin/treasury/us10y/usdcny 一致)
产出:
  data/raw_data/macro_hs300_pe_primary.csv {date, pe_ttm}
"""
import akshare as ak
import pandas as pd
from pathlib import Path

RAW = Path('/mnt/c/new_tdx64/PYPlugins/user/data/raw_data')
RAW.mkdir(parents=True, exist_ok=True)

# ---- 1. 中证官方: 收盘 + 滚动市盈率(同一次调用) ----
df = ak.stock_zh_index_hist_csindex(symbol='000300', start_date='20050101', end_date='20260921')
df['日期'] = pd.to_datetime(df['日期']).dt.strftime('%Y-%m-%d')

pe = df[['日期', '滚动市盈率']].rename(columns={'日期': 'date', '滚动市盈率': 'pe_ttm'})

# ---- 2. 新浪 收盘(异源对照) ----
sina = ak.stock_zh_index_daily(symbol='sh000300')
sina['date'] = pd.to_datetime(sina['date']).dt.strftime('%Y-%m-%d')
sina = sina[['date', 'close']]

# ---- 3. 严格无空值截断: 从最后一个空值日之后起 ----
last_gap = pe['pe_ttm'].isna().idxmax()  # 第一个空值位
# 改为: 找最后一个空值日期
gap_dates = pe.loc[pe['pe_ttm'].isna(), 'date']
last_gap_date = gap_dates.iloc[-1]
cut = pe[pe['date'] > last_gap_date].copy().reset_index(drop=True)
assert cut['pe_ttm'].notna().all(), "截断后仍有空值!"
assert cut['date'].is_unique, "日期不唯一!"
assert pd.to_datetime(cut['date']).is_monotonic_increasing, "日期不递增!"

# ---- 4. 写文件 (无BOM) ----
pe_out = cut[['date', 'pe_ttm']]
pe_out.to_csv(RAW / 'macro_hs300_pe_primary.csv', index=False)

# ---- 5. 自查报告 ----
print(f"截断点: 最后一个空值日={last_gap_date} → 文件起始={cut.iloc[0,0]}")
print(f"结构: {len(cut)}行 {cut.iloc[0,0]}~{cut.iloc[-1,0]} 空值={cut['pe_ttm'].isna().sum()} 唯一={cut['date'].is_unique}")
print(f"值域: min={cut['pe_ttm'].min():.2f} max={cut['pe_ttm'].max():.2f}")

# 异源对照(共同日, 最大差): 中证收盘(对照用,不落地) vs 新浪
cs_close = df[['日期', '收盘']].rename(columns={'日期': 'date', '收盘': 'close'})
m = cs_close.merge(sina, on='date', suffixes=('_cs', '_sina'))
diff = (m['close_cs'] - m['close_sina']).abs()
print(f"异源对照: 共同{len(m)}日, 最大差={diff.max():.4f}, 均值差={diff.mean():.4f}")

# 锚点抽查: 2012-09-04(首日) / 2020-01-02 / 2026-09-21(末日)
for anchor in ['2012-09-04', '2020-01-02', '2026-09-21']:
    row = cut[cut['date'] == anchor]
    print(f"锚点 {anchor}: PE={row.iloc[0]['pe_ttm'] if len(row) else '无此行'}")

import hashlib
f = 'macro_hs300_pe_primary.csv'
h = hashlib.sha256((RAW / f).read_bytes()).hexdigest()[:16]
print(f"SHA256({f}) = {h}...")
