#!/bin/bash
# A项验证: (1)已是最新 → 干净退出 (2)真实补数场景(库内截到7月) → 确认卡正确
set -u
PY=/root/amazingdata/venv/bin/python3
REAL=/mnt/c/new_tdx64/PYPlugins/user/data/raw_data/macro_shrzgm_primary.csv
T=/tmp/shrzgm_supp; rm -rf $T; mkdir -p $T

echo "════ 场景1: 已是最新(真实库内到 2026-08) ════"
cd /root/l1_ops
$PY shrzgm_supplement.py 2>&1 | tail -6
echo "退出码=$?"

echo ""
echo "════ 场景2: 真实补数(构造库内只到 2026-07, 应差分出 8月=16600) ════"
head -1 "$REAL" > "$T/macro_shrzgm_primary.csv"
grep -v "^2026-08-31" "$REAL" | tail -n +2 >> "$T/macro_shrzgm_primary.csv"
echo "  构造后末行: $(tail -1 "$T/macro_shrzgm_primary.csv")"
SHRZGM_SUPP_BASE=/tmp/nonexistent $PY -c "
import os,sys
os.environ['SHRZGM_SUPP_BASE']='/tmp/nonexistent'
" 2>/dev/null
# 用 env 覆盖 RAW 目录不可行(BASE 派生), 故临时改脚本变量方式: 直接复制脚本改路径
sed "s|BASE = os.environ.get(\"SHRZGM_SUPP_BASE\", \"/mnt/c/new_tdx64/PYPlugins/user\")|BASE = \"/tmp/shrzgm_supp_base\"|" \
    /root/l1_ops/shrzgm_supplement.py > /tmp/shrzgm_supp_script.py
mkdir -p /tmp/shrzgm_supp_base/data/raw_data
cp "$T/macro_shrzgm_primary.csv" /tmp/shrzgm_supp_base/data/raw_data/
$PY /tmp/shrzgm_supp_script.py 2>&1 | tail -22
