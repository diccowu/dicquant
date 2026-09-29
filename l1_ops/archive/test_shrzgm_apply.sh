#!/bin/bash
# 验证 --apply 写库链路(沙箱: 临时 CSV + 测试用 PG 行, 完成后清理)
set -u
PY=/root/amazingdata/venv/bin/python3
# 凭据从 .env_l1 读取(2026-09-29 灾备清理: 去明文密码)
[ -f /root/l1_ops/.env_l1 ] && . /root/l1_ops/.env_l1
: "${L1_PG_DSN:?需要 L1_PG_DSN}"
BASE=/tmp/shrzgm_apply
rm -rf $BASE; mkdir -p $BASE/data/raw_data

echo "=== 构造: 库内只到 7 月 ==="
head -1 /mnt/c/new_tdx64/PYPlugins/user/data/raw_data/macro_shrzgm_primary.csv > $BASE/data/raw_data/macro_shrzgm_primary.csv
grep -v "^2026-08-31" /mnt/c/new_tdx64/PYPlugins/user/data/raw_data/macro_shrzgm_primary.csv | tail -n +2 >> $BASE/data/raw_data/macro_shrzgm_primary.csv
echo "  末行: $(tail -1 $BASE/data/raw_data/macro_shrzgm_primary.csv)  行数: $(($(wc -l < $BASE/data/raw_data/macro_shrzgm_primary.csv)-1))"

sed "s|BASE = os.environ.get(\"SHRZGM_SUPP_BASE\", \"/mnt/c/new_tdx64/PYPlugins/user\")|BASE = \"$BASE\"|" \
    /root/l1_ops/shrzgm_supplement.py > /tmp/shrzgm_apply_script.py

echo ""
echo "=== 记录 PG 写前状态 ==="
$PY -c "
import psycopg2
c=psycopg2.connect('$L1_PG_DSN'); cur=c.cursor()
cur.execute(\"SELECT count(*) FROM l1_observation WHERE indicator_id='shrzgm'\")
print('  shrzgm 行数(写前):', cur.fetchone()[0])
cur.execute(\"SELECT period_date,value,status FROM l1_observation WHERE indicator_id='shrzgm' AND period_date='2026-08-31'\")
print('  2026-08-31 行:', cur.fetchall())
c.close()"

echo ""
echo "=== --apply 写库 ==="
$PY /tmp/shrzgm_apply_script.py --apply 2>&1 | tail -8

echo ""
echo "=== 验证写入结果 ==="
echo "  CSV 末行: $(tail -1 $BASE/data/raw_data/macro_shrzgm_primary.csv)  行数: $(($(wc -l < $BASE/data/raw_data/macro_shrzgm_primary.csv)-1))"
$PY -c "
import psycopg2
c=psycopg2.connect('$L1_PG_DSN'); cur=c.cursor()
cur.execute(\"SELECT period_date,value,status,vintage_date FROM l1_observation WHERE indicator_id='shrzgm' AND period_date='2026-08-31' ORDER BY vintage_date\")
for r in cur.fetchall(): print('  PG:', r)
c.close()"

echo ""
echo "=== 清理(删除测试写入的 PG 行 + 临时文件) ==="
$PY -c "
import psycopg2
c=psycopg2.connect('$L1_PG_DSN'); cur=c.cursor()
cur.execute(\"DELETE FROM l1_observation WHERE indicator_id='shrzgm' AND period_date='2026-08-31' AND vintage_date=CURRENT_DATE\")
print('  删除测试行:', cur.rowcount)
c.commit(); c.close()"
$PY -c "
import psycopg2
c=psycopg2.connect('$L1_PG_DSN'); cur=c.cursor()
cur.execute(\"SELECT count(*) FROM l1_observation WHERE indicator_id='shrzgm'\")
print('  shrzgm 行数(清理后, 应恢复):', cur.fetchone()[0])
cur.execute(\"SELECT period_date,value,status FROM l1_observation WHERE indicator_id='shrzgm' AND period_date='2026-08-31'\")
print('  2026-08-31 行:', cur.fetchall())
c.close()"
rm -rf $BASE /tmp/shrzgm_apply_script.py
echo "  临时文件已清理"
