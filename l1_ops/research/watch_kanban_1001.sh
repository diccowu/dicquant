#!/bin/bash
# 守望 infomana 复检卡 t_5c0e1c96, 轮询直到 done/blocked, 最长 45 分钟
TID=t_5c0e1c96
for i in $(seq 1 90); do
  ST=$(hermes kanban --board quant-dev list 2>&1 | grep "$TID" | head -1)
  case "$ST" in
    *done*|*blocked*)
      echo "=== 卡状态: $ST ==="
      echo "--- result ---"
      hermes kanban --board quant-dev show "$TID" 2>&1 | tail -40
      echo "--- log ---"
      hermes kanban --board quant-dev log "$TID" 2>&1 | tail -30
      exit 0
      ;;
  esac
  sleep 30
done
echo "=== 守望超时(45min), 卡仍: $ST ==="
exit 3
