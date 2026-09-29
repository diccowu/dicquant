#!/bin/bash
# 4 条 qucoder 意见落地后总验证
set -u
cd /root/l1_ops
PY=/root/amazingdata/venv/bin/python3
# 凭据从 .env_l1 读取(2026-09-29 灾备清理: 去明文密码)
[ -f /root/l1_ops/.env_l1 ] && . /root/l1_ops/.env_l1
: "${L1_PG_DSN:?需要 L1_PG_DSN}"
# 凭据(含账号)一律从 .env_l1 读取(2026-09-29 灾备清理)

echo "=== 1. 语法 ==="
$PY -m py_compile shrzgm_supplement.py l1_update.py && echo "  ✅ 编译 OK"

echo ""
echo "=== 2. 已最新场景(dry-run) ==="
$PY shrzgm_supplement.py 2>&1 | tail -3

echo ""
echo "=== 3. 补数场景(库截到7月) + --apply 沙箱, 验证编码无 BOM ==="
BASE=/tmp/szgm_fix; rm -rf $BASE; mkdir -p $BASE/data/raw_data
head -1 /mnt/c/new_tdx64/PYPlugins/user/data/raw_data/macro_shrzgm_primary.csv > $BASE/data/raw_data/macro_shrzgm_primary.csv
grep -v "^2026-08-31" /mnt/c/new_tdx64/PYPlugins/user/data/raw_data/macro_shrzgm_primary.csv | tail -n +2 >> $BASE/data/raw_data/macro_shrzgm_primary.csv
sed "s|BASE = os.environ.get(\"SHRZGM_SUPP_BASE\", \"/mnt/c/new_tdx64/PYPlugins/user\")|BASE = \"$BASE\"|" \
    shrzgm_supplement.py > /tmp/szgm_fix_script.py
$PY /tmp/szgm_fix_script.py --apply 2>&1 | grep -E "PG 已|CSV 已|差分"
echo "  写出首字节(应 646174 无 BOM): $(head -c3 $BASE/data/raw_data/macro_shrzgm_primary.csv | xxd -p)"
echo "  CSV 末行: $(tail -1 $BASE/data/raw_data/macro_shrzgm_primary.csv)"

echo ""
echo "=== 4. 清理 PG 测试行 ==="
$PY -c "
import psycopg2
c=psycopg2.connect('$L1_PG_DSN'); cur=c.cursor()
cur.execute(\"DELETE FROM l1_observation WHERE indicator_id='shrzgm' AND vintage_date=CURRENT_DATE\")
print('  删除:', cur.rowcount); c.commit()
cur.execute(\"SELECT count(*) FROM l1_observation WHERE indicator_id='shrzgm'\")
print('  恢复行数:', cur.fetchone()[0]); c.close()"
rm -rf $BASE /tmp/szgm_fix_script.py

echo ""
echo "=== 5. 全量回归(含 float_cap 护栏语义修正) ==="
$PY l1_update.py --all --state-from pg --dry-run --pit-init /root/l1_ops/pit_init.py > /tmp/l1reg3.log 2>&1
echo "  退出码=$?  完成: $(grep '完成:' /tmp/l1reg3.log | tail -1)"
grep "窗口护栏" /tmp/l1reg3.log | head -2

echo ""
echo "=== 6. 最终指纹 ==="
for f in shrzgm_supplement.py l1_update.py; do
  printf "  %-24s %s  (%s 行)\n" "$f" "$(sha256sum $f | cut -c1-16)" "$(wc -l < $f)"
done
