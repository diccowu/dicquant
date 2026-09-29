# -*- coding: utf-8 -*-
"""pit_init 重建前的值域实测(只读, 为 INDICATORS 断言定界)"""
import pandas as pd
RAW = "/mnt/c/new_tdx64/PYPlugins/user/data/raw_data/"

def rng(f, col, label):
    df = pd.read_csv(RAW+f, encoding='utf-8-sig')
    s = df[col].dropna()
    print(f"{label:14s} {f:32s} col={col:16s} n={len(s):6d} min={s.min():.4g} max={s.max():.4g} mean={s.mean():.6g}")

rng("macro_floatcap_primary.csv", "A_FLOAT_CAP", "float_cap(万元)")
rng("macro_floatcap_primary.csv", "TOTAL_CAP",   "total_cap(万元)")
rng("macro_usdcny_primary.csv",   "usdcny",      "usdcny")
rng("macro_hs300_pe_primary.csv", "pe_ttm",      "hs300_pe_ttm")
rng("brent_fred_daily.csv",       "brent",       "oil_daily")
rng("macro_oil_monthly.csv",      "oil_month_avg","oil_month_avg")
rng("macro_oil_monthly.csv",      "oil_yoy",     "oil_yoy(%)")
rng("macro_margin_ad_daily.csv",  "margin_balance","margin_balance")
rng("macro_margin_ad_daily.csv",  "margin_purchase","margin_purchase")

# treasury 列名确认
t = pd.read_csv(RAW+"macro_treasury_ad_primary.csv", encoding='utf-8-sig')
print("\ntreasury 列:", list(t.columns))
# money supply 列名
m = pd.read_csv(RAW+"macro_money_supply_primary.csv", encoding='utf-8-sig')
print("money_supply 列:", list(m.columns))
# shrzgm
s = pd.read_csv(RAW+"macro_shrzgm_primary.csv", encoding='utf-8-sig')
print("shrzgm 列:", list(s.columns))
