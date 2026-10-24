#!/bin/bash
# L1 日常增量更新 — ARM (arm-free-01) 版, 接管办公室 10-16 起的主采职责
# cron: 每交易日 09:30 UTC (= 北京 17:30, 收盘+星耀两融发布后)
# 2026-10-20 重构: 两段式采集
#   Pass 1: 系统 Python (ARM 原生, 无 qemu) → akshare/FRED/BIS/CFETS/TDX 指标
#   Pass 2: qemu adpython → AmazingData 指标 (treasury/margin/floatcap)
#   原因: qemu 网络栈导致 akshare 静默返回空 → "无新数据" 假阴性
set -uo pipefail
cd /home/ubuntu/l1_ops
source /home/ubuntu/l1_ops/.env_l1

SYS_PY=/home/ubuntu/l1_ops/venv/bin/python3
QEMU_PY=/home/ubuntu/bin/adpython
LOG=/home/ubuntu/l1_ops/logs/l1_daily_$(date +%Y%m).log
mkdir -p /home/ubuntu/l1_ops/logs

# Pass 1: akshare + FRED + BIS + CFETS + TDX (系统 Python, ARM 原生)
AK_IDS="hs300_pe_ttm,us10y,usdcny,dr007,shibor_3m,cbond_aaa_10y,oil,\
pmi,cpi_yoy,cpi_mom,cpi_ytd,ppi_yoy,ppi_ytd,m1_yoy,m2_yoy,shrzgm,\
neer_cny,neer_cfets,lpr_1y,lpr_5y,mkt_amount"

# Pass 2: AmazingData (qemu x86_64, 星耀 SDK 仅 x86)
AD_IDS="treasury_y1,treasury_y10,treasury_m6,treasury_y2,\
margin_balance,margin_purchase,margin_borrow_balance,margin_sec_lending_balance,float_cap"

rc=2
{
  echo "===== $(date '+%F %T') 开始 ====="
  echo "--- Pass 1: 系统 Python (akshare/FRED/BIS/CFETS/TDX) ---"
  for i in 1 2 3; do
    timeout 600 $SYS_PY l1_update.py --only "$AK_IDS" --state-from pg --pit-init /home/ubuntu/l1_ops/pit_init.py
    rc=$?
    echo "----- pass1 round $i rc=$rc -----"
    # 0=全绿 2=部分失败(流程完整) → 停止重试; 1=Python崩溃(缺模块等) / 124=超时 / 134,139=信号 → 重试
    if [ "$rc" -eq 0 ] || [ "$rc" -eq 2 ]; then break; fi
    sleep 10
  done

  echo "--- Pass 2: qemu adpython (AmazingData) ---"
  rc2=2
  for i in 1 2 3; do
    timeout 1500 "$QEMU_PY" l1_update.py --only "$AD_IDS" --state-from pg --pit-init /home/ubuntu/l1_ops/pit_init.py
    rc2=$?
    echo "----- pass2 round $i rc=$rc2 -----"
    # 0=全绿 2=部分失败(流程完整) → 停止重试; 1=Python崩溃 / 124=超时 / 134,139=信号 → 重试
    if [ "$rc2" -eq 0 ] || [ "$rc2" -eq 2 ]; then break; fi
    sleep 30
  done

  # 汇总: pass1 或 pass2 有失败 → 报警
  rc=$(( rc > rc2 ? rc : rc2 ))
  echo "===== $(date '+%F %T') 结束 pass1_rc=$rc pass2_rc=$rc2 总rc=$rc ====="
} >> "$LOG" 2>&1

if [ "$rc" -ne 0 ]; then
  TAIL=$(tail -20 "$LOG" | tr '\n' ' ')
  /home/ubuntu/.local/bin/hermes send -t feishu \
    "⚠️ L1 日常更新失败 rc=$rc | 日志: $LOG | 尾部: ${TAIL: -400}" 2>/dev/null || true
fi
exit "$rc"
