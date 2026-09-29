#!/bin/bash
# 两融完整性护栏修复 — 一键事实核对脚本(只输出事实, 判定由复检人下)
# 用法: bash /root/l1_ops/run_verify_margin.sh          # 全量(含实源拉取 + PG)
#       bash /root/l1_ops/run_verify_margin.sh --no-net # 离线(纯逻辑 + L0 文件)
cd /root/l1_ops || exit 1
set -a
[ -f /root/l1_ops/.env_l1 ] && . /root/l1_ops/.env_l1
set +a
exec /root/amazingdata/venv/bin/python3 /root/l1_ops/verify_margin_fix.py "$@" 2>&1 \
  | grep -vE "TGW Logon|logon json|login success|下载完成"
