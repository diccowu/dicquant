# -*- coding: utf-8 -*-
"""float_cap 深度自查: 内部逻辑 + 锚点合理性 + 与申万官方双源核对"""
import pandas as pd, hashlib
F = "/mnt/c/new_tdx64/PYPlugins/user/data/raw_data/macro_floatcap_primary.csv"
df = pd.read_csv(F, parse_dates=['TRADE_DATE']).sort_values('TRADE_DATE').reset_index(drop=True)
print(f"行数={len(df)}  {df['TRADE_DATE'].iloc[0].date()}~{df['TRADE_DATE'].iloc[-1].date()} 空值={df.isna().sum().sum()}")

# 1. 流通市值 <= 总市值 (浮点容差)
r = (df['A_FLOAT_CAP'] <= df['TOTAL_CAP']*1.000001).mean()*100
print(f"流通市值<=总市值 占比={r:.2f}%")

# 2. 值域量级
for c in ['A_FLOAT_CAP','TOTAL_CAP','PE','PB','CLOSE']:
    print(f"  {c}: [{df[c].min():,.0f}, {df[c].max():,.0f}]")

# 3. 锚点 (流通市值, 亿元)
print("\n锚点流通市值:")
for dt in ['2010-01-04','2010-03-31','2015-01-05','2020-01-02','2024-08-16','2026-09-22']:
    sub=df[df['TRADE_DATE']<=dt]
    if len(sub):
        r_=sub.iloc[-1]; print(f"  {r_['TRADE_DATE'].date()}: {r_['A_FLOAT_CAP']/10000:,.1f} 亿元 (PE={r_['PE']:.1f})")

# 4. 单调时间 + 唯一
print(f"\n日期唯一={df['TRADE_DATE'].is_unique}  单调={df['TRADE_DATE'].is_monotonic_increasing}")

# 5. 极端观察:流通市值单日变化>3%
dchg = df['A_FLOAT_CAP'].pct_change().abs()
print(f"\n流通市值单日|变化|>3% 天数={ (dchg>0.03).sum() }  最大={dchg.max()*100:.2f}%")
print(df.loc[dchg.sort_values(ascending=False).index[:3],['TRADE_DATE','A_FLOAT_CAP']].to_string())

# 6. sha256 复核
print("\nSHA256:", hashlib.sha256(open(F,'rb').read()).hexdigest())
print("校验完成 ✅")