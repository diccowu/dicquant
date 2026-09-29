#!/bin/bash
# A项交付前总验证
set -u
cd /root/l1_ops
PY=/root/amazingdata/venv/bin/python3

echo "=== 1. 语法检查 ==="
$PY -m py_compile shrzgm_supplement.py && echo "  ✅ shrzgm_supplement.py 编译 OK"

echo ""
echo "=== 2. 已是最新场景(dry-run, 真实库) ==="
$PY shrzgm_supplement.py 2>&1 | tail -4
echo "  退出码=$?"

echo ""
echo "=== 3. L1 全量回归(确认补数脚本不影响主流程) ==="
# 凭据从 .env_l1 读取(2026-09-29 灾备清理: 去明文密码)
[ -f /root/l1_ops/.env_l1 ] && . /root/l1_ops/.env_l1
: "${L1_PG_DSN:?需要 L1_PG_DSN}"
# 凭据(含账号)一律从 .env_l1 读取(2026-09-29 灾备清理)
$PY l1_update.py --all --state-from pg --dry-run --pit-init /root/l1_ops/pit_init.py > /tmp/l1reg.log 2>&1
echo "  退出码=$?  末尾: $(grep '完成:' /tmp/l1reg.log | tail -1)"

echo ""
echo "=== 4. 指纹 ==="
printf "  shrzgm_supplement.py  %s  (%s 行)\n" "$(sha256sum shrzgm_supplement.py | cut -c1-16)" "$(wc -l < shrzgm_supplement.py)"