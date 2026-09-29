#!/bin/bash
# 排查 float_cap 源 NaN: 是源本身未发布完, 还是采集/解析问题
cd /root/amazingdata || exit 1
# 凭据(含账号)一律从 .env_l1 读取(2026-09-29 灾备清理)
/root/amazingdata/venv/bin/python3 -c "
import AmazingData as ad
import pandas as pd
ad.login(username='$AD_USERNAME', password='$AD_PASSWORD', host='$AD_HOST', port=8600)
info = ad.InfoData()
d = info.get_industry_daily(code_list=['801003.SI'], begin_date=20260924, end_date=20260929, is_local=False)
df = d['801003.SI'].reset_index()
print('列:', [c for c in df.columns][:14])
print()
print('最近 6 行关键列:')
cols = ['TRADE_DATE','CLOSE','TOTAL_CAP','A_FLOAT_CAP']
have = [c for c in cols if c in df.columns]
print(df[have].tail(6).to_string())
print()
print('A_FLOAT_CAP 空值行数:', int(df['A_FLOAT_CAP'].isnull().sum()))
print('TOTAL_CAP 空值行数:', int(df['TOTAL_CAP'].isnull().sum()))
" 2>&1 | grep -vE "TGW Logon|logon json|login success|下载完成"
echo ""
echo "=== 现有 CSV 尾部 ==="
tail -4 /mnt/c/new_tdx64/PYPlugins/user/data/raw_data/macro_floatcap_primary.csv
echo ""
echo "=== 现有 CSV 是否有 NaN ==="
/root/amazingdata/venv/bin/python3 -c "
import pandas as pd
d = pd.read_csv('/mnt/c/new_tdx64/PYPlugins/user/data/raw_data/macro_floatcap_primary.csv')
print('行数:', len(d), '| 空值:', d.isnull().sum()[d.isnull().sum()>0].to_dict() or '无')
print('末日:', d.iloc[-1].to_dict())
"