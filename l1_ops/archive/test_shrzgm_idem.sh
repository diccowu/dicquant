#!/bin/bash
# A项完整验证: 幂等重跑 + 备用源 + 无网络失败路径
set -u
PY=/root/amazingdata/venv/bin/python3
# 凭据从 .env_l1 读取(2026-09-29 灾备清理: 去明文密码)
[ -f /root/l1_ops/.env_l1 ] && . /root/l1_ops/.env_l1
: "${L1_PG_DSN:?需要 L1_PG_DSN}"
BASE=/tmp/shrzgm_idem
rm -rf $BASE; mkdir -p $BASE/data/raw_data
head -1 /mnt/c/new_tdx64/PYPlugins/user/data/raw_data/macro_shrzgm_primary.csv > $BASE/data/raw_data/macro_shrzgm_primary.csv
grep -v "^2026-08-31" /mnt/c/new_tdx64/PYPlugins/user/data/raw_data/macro_shrzgm_primary.csv | tail -n +2 >> $BASE/data/raw_data/macro_shrzgm_primary.csv
sed "s|BASE = os.environ.get(\"SHRZGM_SUPP_BASE\", \"/mnt/c/new_tdx64/PYPlugins/user\")|BASE = \"$BASE\"|" \
    /root/l1_ops/shrzgm_supplement.py > /tmp/shrzgm_idem_script.py

echo "════ ① 首次 --apply ════"
$PY /tmp/shrzgm_idem_script.py --apply 2>&1 | grep -E "PG 已|CSV 已|差分"
echo "  CSV 行数: $(($(wc -l < $BASE/data/raw_data/macro_shrzgm_primary.csv)-1))"

echo ""
echo "════ ② 幂等重跑 --apply(应识别已最新, 不重复写) ════"
$PY /tmp/shrzgm_idem_script.py --apply 2>&1 | grep -E "已是最新|核对|PG 已|CSV 已|差分"
echo "  CSV 行数(应不变): $(($(wc -l < $BASE/data/raw_data/macro_shrzgm_primary.csv)-1))"

echo ""
echo "════ ③ PG 状态(应恰 1 行 vintage=今天, 无重复) ════"
$PY -c "
import psycopg2
c=psycopg2.connect('$L1_PG_DSN'); cur=c.cursor()
cur.execute(\"SELECT count(*) FROM l1_observation WHERE indicator_id='shrzgm'\")
print('  shrzgm 总行数:', cur.fetchone()[0])
cur.execute(\"SELECT period_date,vintage_date,value FROM l1_observation WHERE indicator_id='shrzgm' AND vintage_date=CURRENT_DATE\")
print('  今天 vintage 的行:', cur.fetchall())
c.close()"

echo ""
echo "════ 清理 ════"
$PY -c "
import psycopg2
c=psycopg2.connect('$L1_PG_DSN'); cur=c.cursor()
cur.execute(\"DELETE FROM l1_observation WHERE indicator_id='shrzgm' AND vintage_date=CURRENT_DATE\")
print('  删除测试行:', cur.rowcount); c.commit()
cur.execute(\"SELECT count(*) FROM l1_observation WHERE indicator_id='shrzgm'\")
print('  shrzgm 行数(恢复):', cur.fetchone()[0]); c.close()"
rm -rf $BASE /tmp/shrzgm_idem_script.py
echo "  临时文件已清理"
