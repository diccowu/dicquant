# -*- coding: utf-8 -*-
"""float_cap 源数据构建脚本（第17项）
源: 星耀 AmazingData get_industry_daily('801003.SI') = 申万A指
全量 12 列 2010-01-04 ~ 最新, 落 data/raw_data/macro_floatcap_primary.csv
单位: 价点位; A_FLOAT_CAP/TOTAL_CAP 万元 (源原始,零加工)
"""
import os, sys, time, hashlib, csv
sys.path.insert(0, '/root/amazingdata')
import AmazingData as ad

USER, PASS = os.environ.get("AD_USERNAME"), os.environ.get("AD_PASSWORD")
HOST, PORT = os.environ.get("AD_HOST", "101.230.159.235"), int(os.environ.get("AD_PORT", "8600"))
OUT = "/mnt/c/new_tdx64/PYPlugins/user/data/raw_data/macro_floatcap_primary.csv"

ad.login(username=USER, password=PASS, host=HOST, port=PORT)
print("✅ 已登录", flush=True)
info = ad.InfoData()

t0 = time.time()
d = info.get_industry_daily(code_list=["801003.SI"], begin_date=20100104,
                            end_date=20260922, is_local=False)
print(f"拉取耗时 {time.time()-t0:.1f}s", flush=True)

df = None
for k, frame in (d.items() if hasattr(d, 'items') else []):
    df = frame
if df is None:
    raise SystemExit(f"❌ 未取到数据, keys={list(d.keys()) if hasattr(d,'keys') else d}")

df = df.sort_index()
print(f"行数={len(df)}  {df.index[0]} ~ {df.index[-1]}")

# 规范化列名 + 输出列序
cols = ['TRADE_DATE','OPEN','HIGH','LOW','CLOSE','PRE_CLOSE','VOLUME','AMOUNT',
        'PE','PB','TOTAL_CAP','A_FLOAT_CAP']
df = df.reset_index()
if 'TRADE_DATE' not in df.columns:
    df = df.rename(columns={df.columns[0]: 'TRADE_DATE'})
for c in ['TRADE_DATE'] + [x for x in cols if x != 'TRADE_DATE']:
    if c not in df.columns:
        print(f"⚠️ 缺列 {c}")
df = df[[c for c in cols if c in df.columns]]

# 数值列保留原值(整/浮), 不四舍五入不加工
df.to_csv(OUT, index=False, encoding='utf-8-sig')

# 自查: 行数 / 空洞 / 值域 / sha256
import pandas as pd
chk = pd.read_csv(OUT, parse_dates=['TRADE_DATE'])
n = len(chk)
gap = chk['TRADE_DATE'].diff().dt.days
big = (gap > 3).sum()
sha = hashlib.sha256(open(OUT,'rb').read()).hexdigest()
print("="*60)
print(f"✅ 已落 {OUT}")
print(f"行数={n}  起={chk['TRADE_DATE'].iloc[0].date()}  止={chk['TRADE_DATE'].iloc[-1].date()}")
print(f"空洞(>3天)={big}  最大={gap.max()}  空值={chk.isna().sum().sum()}")
print(f"A_FLOAT_CAP 值域=[{chk['A_FLOAT_CAP'].min():.0f}, {chk['A_FLOAT_CAP'].max():.0f}] 万元")
print(f"SHA256={sha}")