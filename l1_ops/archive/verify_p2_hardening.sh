#!/bin/bash
# 验证 qucoder 两条非阻塞建议已落地 + 负向测试仍有效
set -u
cd /mnt/c/new_tdx64/PYPlugins/user
PY=/root/amazingdata/venv/bin/python3

echo "=== ① 增量校验(正常数据, 应含新增空值断言) ==="
$PY margin_review_check.py > /tmp/v1.log 2>&1; echo "退出码=$? (期望0)"
grep -E "无空值|INFO|ALL PASS|FAIL" /tmp/v1.log

echo ""
echo "=== ② 定稿校验(应含 pit.db 存在断言) ==="
$PY margin_review_check.py --seal > /tmp/v2.log 2>&1; echo "退出码=$? (期望0)"
grep -E "pit.db|ALL PASS|FAIL" /tmp/v2.log

echo ""
echo "=== ③ 建议① 负向验证: 指向不存在的 DB 目录应红灯 ==="
MARGIN_CHECK_BASE=/tmp/nonexistent_base $PY margin_review_check.py --seal > /tmp/v3.log 2>&1
echo "退出码=$? (期望1=红灯)"
grep -E "pit.db|primary|FAIL" /tmp/v3.log | head -4

echo ""
echo "=== ④ 建议② 负向验证: 注入 NaN 到聚合列应红灯 ==="
RAW=/mnt/c/new_tdx64/PYPlugins/user/data/raw_data
T=/tmp/margin_nan; rm -rf $T; mkdir -p $T
cp "$RAW/macro_margin_ad_daily.csv" "$T/"
$PY -c "
import pandas as pd
p = pd.read_csv('$RAW/macro_margin_ad_primary.csv')
p.loc[0,'borrow_balance'] = None   # 注入 NaN 到聚合列
p.to_csv('$T/macro_margin_ad_primary.csv', index=False)
print('已注入 NaN 到 borrow_balance[0]')
"
MARGIN_CHECK_RAW=$T $PY margin_review_check.py > /tmp/v4.log 2>&1
echo "退出码=$? (期望1=红灯)"
grep -E "borrow_balance 无空值|FAIL" /tmp/v4.log | head -3

echo ""
echo "=== ⑤ 负向测试(09-24 残缺态)仍有效 ==="
bash /root/l1_ops/test_margin_negative.sh 2>&1 | grep -E "命中|漏检|退出码"

echo ""
echo "=== 最终指纹 ==="
sha256sum margin_review_check.py | cut -c1-16
wc -l < margin_review_check.py
