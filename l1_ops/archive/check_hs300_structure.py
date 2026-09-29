# -*- coding: utf-8 -*-
"""检查 macro_hs300_pe_primary.csv 结构: 首个非空段后是否有零星空值 + 唯一性/递增"""
import pandas as pd
p = "/mnt/c/new_tdx64/PYPlugins/user/data/raw_data/macro_hs300_pe_primary.csv"
df = pd.read_csv(p)
print(f"总行: {len(df)}  列: {list(df.columns)}")
print(f"日期唯一: {df['date'].is_unique}  空值总数: {df['pe_ttm'].isna().sum()}")
# 首个非空
first = df['pe_ttm'].first_valid_index()
print(f"首个非空PE index={first} date={df.loc[first,'date']} pe={df.loc[first,'pe_ttm']}")
# 首个非空之后是否有空值
after = df.loc[first:]
print(f"首个非空后: {len(after)}行, 其中空值 {after['pe_ttm'].isna().sum()}")
# 日期递增检查
d = pd.to_datetime(df['date'])
print(f"日期单调递增: {d.is_monotonic_increasing}")
print(f"日期范围: {df['date'].iloc[0]} ~ {df['date'].iloc[-1]}")
# 尾部
print("尾部3行:")
print(df.tail(3).to_string())
# 值域
print(f"PE min={df['pe_ttm'].min()} max={df['pe_ttm'].max()}")
