#!/bin/bash
# 单独验证建议①: pit.db 缺失必须红灯(不影响 CSV 读取)
set -u
cd /mnt/c/new_tdx64/PYPlugins/user
PY=/root/amazingdata/venv/bin/python3
REAL_RAW=/mnt/c/new_tdx64/PYPlugins/user/data/raw_data
FAKE_BASE=/tmp/nonexistent_base

echo "=== 定稿校验: BASE 不存在(→pit.db 缺失), RAW 指向真实 ==="
MARGIN_CHECK_BASE=$FAKE_BASE MARGIN_CHECK_RAW=$REAL_RAW $PY margin_review_check.py --seal > /tmp/v5.log 2>&1
echo "退出码=$? (期望1=红灯)"
grep -E "pit.db|primary|daily|FAIL|ALL PASS" /tmp/v5.log | head -10

echo ""
echo "=== 对照: 正常 BASE 应 ALL PASS ==="
$PY margin_review_check.py --seal > /tmp/v6.log 2>&1
echo "退出码=$? (期望0)"
grep -E "ALL PASS|FAIL" /tmp/v6.log
