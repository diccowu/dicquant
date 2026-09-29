#!/bin/bash
# 社融月度补数提醒 —— 供 cron 调用(建议每月 16~20 日, 每日一次)
#
# 设计(2026-09-29):
#   - 跑 dry-run: 有新月 → 打印补数确认卡(非空 stdout → cron 投递到飞书)
#   - 无新月(已是最新/报告未发布) → 不打印任何内容(空 stdout → 静默, 不打扰)
#   - 与 timeout 硬约束: 网络抓取最长 120s
#
# 挂载示例(办公室 Hermes cron):
#   hermes cron create --name "社融月度补数提醒" --schedule "0 10 16-20 * *" \
#     --no-agent --script shrzgm_monthly_remind.sh --deliver origin
set -uo pipefail
cd /root/l1_ops || exit 1
PY=/root/amazingdata/venv/bin/python3
export L1_PG_DSN="${L1_PG_DSN:-$(grep -oP 'L1_PG_DSN="\K[^"]+' /root/l1_ops/.env_l1 2>/dev/null || echo '')}"

OUT=$(timeout 120 "$PY" /root/l1_ops/shrzgm_supplement.py 2>&1)
RC=$?

if [ $RC -ne 0 ]; then
  # 抓取/解析异常 → 必须提醒(非空输出即投递)
  echo "⚠️ 社融补数检查异常(rc=$RC)"
  echo "$OUT" | tail -15
  exit 0
fi

# 有新月 → 输出确认卡; 否则静默
# (2026-09-29 修: 原 sed 范围 '/补数确认卡/,/^=\{20,\}$/' 因分隔线长达 72 字符
#  且首行即为 '=' 分隔线, 导致只抓到标题 → 改为直接截取"补数确认卡"起至末尾)
if echo "$OUT" | grep -q "补数确认卡"; then
  echo "$OUT" | sed -n '/📋 补数确认卡/,$p' | head -25
  echo ""
  echo "→ 核对无误后运行: python /root/l1_ops/shrzgm_supplement.py --apply"
  echo "→ 完成后须更新 shrzgm_review_check.py 的 SEAL 并登记台账"
fi
# 未匹配"补数确认卡" → 无输出 → cron 不投递(静默)
exit 0
