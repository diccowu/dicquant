#!/bin/bash
# 清理清单生成(不删, 只列出待你确认)
echo "════════ 候选清理: /root/l1_ops 一次性侦察/测试脚本 ════════"
cd /root/l1_ops
ls -1 probe_*.py 2>/dev/null | sed 's/^/  /'
ls -1 test_*.sh test_*.py 2>/dev/null | sed 's/^/  /'
ls -1 verify_*.sh verify_*.py 2>/dev/null | sed 's/^/  /'
ls -1 check_szse_nan.sh 2>/dev/null | sed 's/^/  /'
echo "  (以上为侦察/测试/验证工具, 已定稿, 可通过 git 历史恢复——但工作副本可删)"

echo ""
echo "════════ 候选清理: 工作目录 建库后不再需要 ════════"
cd /mnt/c/new_tdx64/PYPlugins/user
echo "--- build_*.py(建库脚本, 已执行完) ---"
ls -1 build_*.py 2>/dev/null | grep -v build_nas_l1 | sed 's/^/  /'
echo "--- selfcheck/check(自查类, 一次性) ---"
ls -1 selfcheck_*.py check_*.py 2>/dev/null | sed 's/^/  /'
echo "--- probe/一次性工具 ---"
ls -1 probe_ranges.py _tmp_oil_check.py xtquant_test.py check_sc42_0528.py fill_us10y_fred.py 2>/dev/null | sed 's/^/  /'

echo ""
echo "════════ 保留(不改) ════════"
echo "  生产: l1_update.py pit_init.py pg_conn.py l1_daily.sh shrzgm_supplement.py shrzgm_monthly_remind.sh .env_l1(.example)"
echo "  验收: margin/treasury/us10y/money_supply/shrzgm_review_check.py"
echo "  恢复追溯: audit/ docs/ COVERAGE_REGISTRY.md(事故复盘留痕, 不删)"
echo "  DataGuard: dataguard_validation_20260528.py 等(非 L1 职责, 未确认不动)"
echo "  build_nas_l1.py(NAS 建库脚本, 灾备重建要用, 保留)"

echo ""
echo "════════ 统计 ════════"
echo "  /root/l1_ops 候选删: $(ls -1 probe_*.py test_*.sh test_*.py verify_*.sh verify_*.py check_szse_nan.sh 2>/dev/null | wc -l) 个"
echo "  工作目录候选删: $(ls -1 build_*.py selfcheck_*.py check_*.py 2>/dev/null | wc -l) 个 +(probe/_tmp/xtquant/check_sc42/fill) 5 个"