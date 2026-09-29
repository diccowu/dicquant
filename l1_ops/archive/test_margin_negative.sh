#!/bin/bash
# 负向测试(决定性证据): 构造"09-24 残缺态" → 新增量校验应 FAIL 且命中正确断言
set -u
RAW=/mnt/c/new_tdx64/PYPlugins/user/data/raw_data
T=/tmp/margin_neg
rm -rf "$T"; mkdir -p "$T"

# 构造残缺态: primary 09-24 只留 SSE; daily 09-24 改为残缺值
head -1 "$RAW/macro_margin_ad_primary.csv" > "$T/macro_margin_ad_primary.csv"
grep -v "^2026-09-24" "$RAW/macro_margin_ad_primary.csv" | tail -n +2 >> "$T/macro_margin_ad_primary.csv"
echo "2026-09-24,SSE,1331841736225,77396224473,86336677880,18664487521,84996899,1350506223746" >> "$T/macro_margin_ad_primary.csv"

head -1 "$RAW/macro_margin_ad_daily.csv" > "$T/macro_margin_ad_daily.csv"
grep -v "^2026-09-24" "$RAW/macro_margin_ad_daily.csv" | tail -n +2 >> "$T/macro_margin_ad_daily.csv"
echo "2026-09-24,1350506223746,77396224473" >> "$T/macro_margin_ad_daily.csv"

echo "残缺态构造完成: primary 09-24 交易所数=$(awk -F, '$1=="2026-09-24"' "$T/macro_margin_ad_primary.csv" | wc -l) (应为1)"
echo ""
echo "=== 跑增量校验(指向残缺态) ==="
cd /mnt/c/new_tdx64/PYPlugins/user
MARGIN_CHECK_RAW="$T" /root/amazingdata/venv/bin/python3 margin_review_check.py > /tmp/neg.log 2>&1
RC=$?
echo "真实退出码=$RC (期望 1 = 红灯)"
grep -E "FAIL|结论|SKIP" /tmp/neg.log | head -12
echo ""
echo "=== 检出判定 ==="
for k in "交易所完整性" "聚合层无残缺日"; do
  if grep -q "FAIL.*$k" /tmp/neg.log; then echo "  ✅ 命中: $k"; else echo "  ❌ 漏检: $k"; fi
done
if grep -qE "FAIL.*margin_balance 相对20日中位偏离" /tmp/neg.log; then
  echo "  ✅ 命中: margin_balance 连续性(49% > 40%)"
else
  echo "  ⚠️ 连续性未命中(残缺值落在聚合层, 但其偏离幅度需看日志)"
fi
echo ""
echo "--- 连续性行实测 ---"
grep -E "margin_balance 相对" /tmp/neg.log
