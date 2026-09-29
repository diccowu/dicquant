#!/bin/bash
# L1 日常增量更新 — 办公室 Hermes 单机全量采集(18 指标, 含星耀)
# cron: 每天 21:30
set -uo pipefail
cd /root/l1_ops
source /root/l1_ops/.env_l1

PY=/root/amazingdata/venv/bin/python3
LOG=/root/l1_ops/logs/l1_daily_$(date +%Y%m).log
mkdir -p /root/l1_ops/logs

{
  echo "===== $(date '+%F %T') 开始 ====="
  "$PY" l1_update.py --all --state-from pg --pit-init /root/l1_ops/pit_init.py
  rc=$?
  echo "===== $(date '+%F %T') 结束 rc=$rc ====="
} >> "$LOG" 2>&1

if [ "$rc" -ne 0 ]; then
  TAIL=$(tail -20 "$LOG" | tr '\n' ' ')
  /root/.local/bin/hermes send --platform feishu \
    "⚠️ L1 日常更新失败 rc=$rc | 日志: $LOG | 尾部: ${TAIL: -400}" 2>/dev/null || true
fi
exit "$rc"
