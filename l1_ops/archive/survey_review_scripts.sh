#!/bin/bash
# 排查: 各 L0 CSV 的末日 vs 各验收脚本的硬编码期望(判断红灯是否已触发/潜伏)
cd /mnt/c/new_tdx64/PYPlugins/user/data/raw_data || exit 1
echo "=== L0 CSV 实际末日 ==="
for f in macro_treasury_ad_primary.csv macro_us10y_primary.csv macro_money_supply_primary.csv macro_shrzgm_primary.csv macro_margin_ad_daily.csv; do
  [ -f "$f" ] && printf "  %-34s 末日=%s  行数=%s\n" "$f" "$(tail -1 "$f" | cut -d, -f1)" "$(($(wc -l < "$f")-1))"
done
echo ""
echo "=== 验收脚本硬编码期望(快照点) ==="
echo "  treasury_review_check.py : 数据行 4133 / 区间 ~2026-09-18"
echo "  us10y_review_check.py    : 区间 ~2026-09-18 / 1位小数=399 / 极值max@2026-09-16"
echo "  money_supply_review_check.py : 行数 224 / 起止 2008-01-31~2026-08-31"
echo "  shrzgm_review_check.py   : 行数 140 / 末日 2026-08-31 / EXP_SHA256"
echo "  margin_review_check.py   : ✅ 已两层化(本次 P2)"
