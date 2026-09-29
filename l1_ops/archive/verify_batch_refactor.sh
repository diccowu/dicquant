#!/bin/bash
# 4 个脚本批改后总验证: 三模式 + 负向测试 + 指纹
cd /mnt/c/new_tdx64/PYPlugins/user || exit 1
PY=/root/amazingdata/venv/bin/python3
for s in treasury_review_check us10y_review_check money_supply_review_check shrzgm_review_check; do
  echo "════════ $s ════════"
  for mode in "--seal" "" "--all"; do
    out=$($PY $s.py $mode 2>&1); rc=$?
    res=$(echo "$out" | grep -cE "FAIL \[" )
    st=$(echo "$out" | grep -oE "ALL PASS ✅" | tail -1)
    printf "  模式=%-8s rc=%s %s\n" "${mode:-默认}" "$rc" "${st:-$(echo "$out" | grep -oE 'FAIL \[[0-9]+\]:.*' | tail -1)}"
  done
  printf "  指纹=%s 行数=%s\n" "$(sha256sum $s.py | cut -c1-16)" "$(wc -l < $s.py)"
done
echo ""
echo "════════ 负向测试: treasury 构造 10 倍错位(数量级事故) ════════"
T=/tmp/treasury_neg; rm -rf $T; mkdir -p $T
$PY -c "
import pandas as pd
d = pd.read_csv('/mnt/c/new_tdx64/PYPlugins/user/data/raw_data/macro_treasury_ad_primary.csv')
d.loc[d.index[-1],'y10'] = d.loc[d.index[-1],'y10']*10   # 数量级错位
d.to_csv('$T/macro_treasury_ad_primary.csv', index=False)
print('已注入 10x 错位: y10 末日 ->', d.loc[d.index[-1],'y10'])
"
TREASURY_CHECK_RAW=$T $PY treasury_review_check.py > /tmp/tn.log 2>&1
echo "  退出码=$? (期望1)"
grep -E "FAIL|值域|连续性|日变动" /tmp/tn.log | head -5
echo ""
echo "════════ 负向测试: shrzgm 构造累计差分断裂 ════════"
T2=/tmp/szgm_neg; rm -rf $T2; mkdir -p $T2
$PY -c "
import shutil
shutil.copy('/mnt/c/new_tdx64/PYPlugins/user/data/raw_data/macro_shrzgm_primary.csv','$T2/')
p='$T2/macro_shrzgm_primary.csv'
ls=open(p,encoding='utf-8-sig').read().splitlines()
r=ls[-1].split(','); r[2]=str(float(r[2])+999); ls[-1]=','.join(r)
open(p,'w',encoding='utf-8-sig').write('\n'.join(ls)+'\n')
print('已破坏末日 inc(差分不再闭合)')
"
SHRZGM_CHECK_RAW=$T2 SHRZGM_CHECK_PIT=/nonexistent $PY shrzgm_review_check.py > /tmp/sn.log 2>&1
echo "  退出码=$? (期望1)"
grep -E "FAIL|差分|年度重置" /tmp/sn.log | head -4
