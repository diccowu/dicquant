#!/bin/bash
# 10-01 扩源落库 一键事实输出 (供 qucoder/infomana 复检用; 只输出事实, 不做判定)
# 判定由复检人对照卡内期望值自己下
cd /root/l1_ops
set -a; . /root/l1_ops/.env_l1 2>/dev/null; set +a
export L1_PG_DSN="host=100.76.208.125 port=5432 user=postgres password=$QUANT_PG_PASSWORD dbname=quant connect_timeout=60 keepalives=1 keepalives_idle=30 keepalives_interval=10 keepalives_count=6"

echo "===== 0. 交付物指纹 ====="
sha256sum /root/l1_ops/pit_init.py /root/l1_ops/l1_update.py \
          /root/l1_ops/sync_10_01_collect.py /root/l1_ops/sync_10_01_load.py \
          /root/l1_ops/research/verify_10_01_expand.py
echo ""
echo "===== 1. 自检脚本 ===== (真实退出码见行尾)"
/root/amazingdata/venv/bin/python3 /root/l1_ops/research/verify_10_01_expand.py; echo "自检真实退出码=$?"

echo ""
echo "===== 2. PG 9 指标行数 (独立复核) ====="
timeout 60 env PGCONNECT_TIMEOUT=30 PGPASSWORD="$QUANT_PG_PASSWORD" psql -h 100.76.208.125 -p 5432 -U postgres -d quant -t -A -F'|' -c "SELECT indicator_id, count(*) FROM l1_observation WHERE indicator_id IN ('treasury_m6','treasury_y2','neer_cny','dr007','shibor_3m','lpr_1y','lpr_5y','cbond_aaa_10y','mkt_amount') GROUP BY 1 ORDER BY 1;"

echo ""
echo "===== 3. meta 总数 + NULL 值检查 ====="
timeout 60 env PGCONNECT_TIMEOUT=30 PGPASSWORD="$QUANT_PG_PASSWORD" psql -h 100.76.208.125 -p 5432 -U postgres -d quant -t -A -c "SELECT 'meta_total='||count(*) FROM l1_indicator_meta; SELECT 'value_null='||count(*) FROM l1_observation WHERE value IS NULL; SELECT 'total_obs='||count(*) FROM l1_observation;"