#!/usr/bin/env python3
"""验证 shrzgm_monthly_remind.sh 的静默/输出行为(沙箱, 自动清理)"""
import os
import shutil
import subprocess
import sys

BASE = "/tmp/szgm_remind"
shutil.rmtree(BASE, ignore_errors=True)
os.makedirs(f"{BASE}/data/raw_data", exist_ok=True)

REAL = "/mnt/c/new_tdx64/PYPlugins/user/data/raw_data/macro_shrzgm_primary.csv"
with open(REAL, encoding="utf-8-sig") as f:
    lines = f.readlines()
with open(f"{BASE}/data/raw_data/macro_shrzgm_primary.csv", "w", encoding="utf-8") as f:
    f.writelines([l for l in lines if not l.startswith("2026-08-31")])

# 生成沙箱版补数脚本 + 提醒脚本
src_supp = open("/root/l1_ops/shrzgm_supplement.py", encoding="utf-8").read()
src_supp = src_supp.replace('BASE = os.environ.get("SHRZGM_SUPP_BASE", "/mnt/c/new_tdx64/PYPlugins/user")',
                            f'BASE = "{BASE}"')
open("/tmp/szgm_supp_boxed.py", "w", encoding="utf-8").write(src_supp)

src_remind = open("/root/l1_ops/shrzgm_monthly_remind.sh", encoding="utf-8").read()
src_remind = src_remind.replace("shr_zgm_supplement.py", "szgm_supp_boxed.py")
src_remind = src_remind.replace("/root/l1_ops/shrzgm_supplement.py", "/tmp/szgm_supp_boxed.py")
open("/tmp/szgm_remind_boxed.sh", "w", encoding="utf-8").write(src_remind)
os.chmod("/tmp/szgm_remind_boxed.sh", 0o755)

print("=== 场景1: 有新月(库截到 7 月) → 应输出确认卡 ===")
r = subprocess.run(["/tmp/szgm_remind_boxed.sh"], capture_output=True, text=True, timeout=180)
print(f"  退出码={r.returncode}  输出字节={len(r.stdout)}")
head = "\n".join(r.stdout.splitlines()[:10])
print(f"  输出前10行:\n{head}")
print(f"  含'补数确认卡': {'✅' if '补数确认卡' in r.stdout else '❌'}")

print()
print("=== 场景2: 无新月(真实库, 应已是最新) → 应静默 ===")
r2 = subprocess.run(["bash", "/root/l1_ops/shrzgm_monthly_remind.sh"],
                    capture_output=True, text=True, timeout=180)
print(f"  退出码={r2.returncode}  输出字节={len(r2.stdout)}")
print(f"  静默: {'✅' if len(r2.stdout.strip()) == 0 else '❌ 输出=' + r2.stdout[:200]}")

# 清理
shutil.rmtree(BASE, ignore_errors=True)
for p in ("/tmp/szgm_supp_boxed.py", "/tmp/szgm_remind_boxed.sh"):
    try:
        os.remove(p)
    except FileNotFoundError:
        pass
print()
print("沙箱已清理")