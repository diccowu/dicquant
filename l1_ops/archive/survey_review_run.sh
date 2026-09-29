#!/bin/bash
# 实测 4 个验收脚本的红灯状态(先查有无写操作, 确保只读安全)
cd /mnt/c/new_tdx64/PYPlugins/user || exit 1
PY=/root/amazingdata/venv/bin/python3

echo "=== 安全前置: 检查脚本有无写操作 ==="
for f in treasury_review_check.py us10y_review_check.py money_supply_review_check.py shrzgm_review_check.py; do
  w=$(grep -cE "to_csv|INSERT|UPDATE|DELETE|open\([^)]*['\"]w" "$f" 2>/dev/null || echo 0)
  printf "  %-34s 写操作命中=%s\n" "$f" "$w"
done
echo ""
echo "=== 实测退出码与失败项 ==="
for f in treasury_review_check.py us10y_review_check.py money_supply_review_check.py shrzgm_review_check.py; do
  echo "--- $f ---"
  out=$($PY "$f" 2>&1); rc=$?
  echo "  退出码=$rc"
  echo "$out" | grep -E "FAIL|结论|ALL PASS" | head -6 | sed 's/^/  /'
done
