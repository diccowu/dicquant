# -*- coding: utf-8 -*-
"""第8项 us10y 独立验收脚本——两层校验(2026-09-28 策略b批改)。

背景:原脚本为"定稿点快照式"(行数/区间/SHA 写死), 增量后必然红灯。拆两层:
  【定稿校验】(--seal)  锁指纹/行数/末日 + pit.db 行数/末日
  【增量校验】(默认)    列集/递增/无空/值域/极值锚/FRED补值/精度分布/连续性(bp)

连续性依据(2026-09-28 实测): 收益率序列**不用相对偏离**(低利率失真: 真实相对偏离
  >15% 达 130 天, 2011 美债降级/2016 大选等真实行情); 用**绝对日变动(bp)**:
  真实 max=30.0bp → 阈值 45bp 零误报; 事故(5.18→51.8 数量级错位)=4500bp 必被抓住。
FRED 3 值锚点与精度分布为**结构性事实**(补值点与源格式特征), 不随增量失效。
"""
import argparse
import hashlib
import os
import sys

import duckdb
import pandas as pd

# 路径 env(统一命名 L1_CHECK_*, 2026-10-02; 旧名保留回退兼容)
BASE = os.environ.get("L1_CHECK_BASE") or os.environ.get(
    "US10Y_CHECK_BASE", "/mnt/c/new_tdx64/PYPlugins/user")
RAW_DIR = os.environ.get("L1_CHECK_RAW") or os.environ.get(
    "US10Y_CHECK_RAW", os.path.join(BASE, "data", "raw_data"))
RAW = os.path.join(RAW_DIR, "macro_us10y_primary.csv")
DB = os.environ.get("L1_CHECK_DB", os.path.join(BASE, "data", "pit", "pit.db"))

# ── 定稿基线(2026-09-28 批改) ──
SEAL = {
    "date": "2026-09-28",
    "csv_sha16": "404a6678214d13e7",
    "csv_rows": 4188,
    "csv_last": "2026-09-24",
    "pit_rows": 4188,       # pit.db 研究层; 2026-10-02 补尾 09-19..09-24 (=L0 源, PG 同键零冲突)
    "pit_last": "2026-09-24",
}
# ── 结构性不变量 ──
RANGE = (0.0, 10.0)
CONTINUITY_BP = 45.0
# FRED 补值锚点(历史事实, 不随增量变化)
FRED_ANCHORS = {"2013-02-15": 2.01, "2014-10-03": 2.45, "2015-01-02": 2.12}
# 极值锚(定稿点事实; 若后续新高出现, 由定稿人随 SEAL 一并更新)
EXTREME_ANCHORS = {"2020-08-04": 0.52, "2026-09-16": 5.01}
# 精度分布(源格式特征: 2010 段 1 位小数 399 行; FRED 补值 3 位小数 3 行)
PRECISION = {1: 399, 3: 3}


def sha16(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()[:16]


class Report:
    def __init__(self, title):
        self.title = title
        self.problems = []

    def chk(self, name, cond, detail=""):
        print(f"  [{'PASS' if cond else 'FAIL'}] {name} {detail}")
        if not cond:
            self.problems.append(name)

    def done(self):
        print(f"\n── {self.title} 结论 ──")
        if self.problems:
            print(f"FAIL [{len(self.problems)}]: {self.problems}")
            return 1
        print("ALL PASS ✅")
        return 0


def run_seal():
    r = Report("定稿校验")
    print(f"══ 定稿校验(基线 {SEAL['date']}) ══")
    n = sum(1 for _ in open(RAW, encoding="utf-8")) - 1
    df = pd.read_csv(RAW, dtype=str)
    r.chk(f"指纹 {SEAL['csv_sha16']}", sha16(RAW) == SEAL["csv_sha16"],
          f"(实 {sha16(RAW)})")
    r.chk(f"行数 {SEAL['csv_rows']}", n == SEAL["csv_rows"], f"(实 {n})")
    r.chk(f"末日 {SEAL['csv_last']}", str(df.date.iloc[-1]) == SEAL["csv_last"],
          f"(实 {df.date.iloc[-1]})")
    if not os.path.exists(DB):
        r.chk(f"pit.db 存在 ({DB})", False, "(文件缺失 → 定稿件不完整)")
    else:
        con = duckdb.connect(DB, read_only=True)
        row = con.execute("SELECT count(*), max(period_date) FROM observation "
                          "WHERE indicator_id='us10y'").fetchone()
        r.chk(f"pit.db us10y 行数 {SEAL['pit_rows']}",
              row[0] == SEAL["pit_rows"], f"(实 {row[0]})")
        r.chk(f"pit.db us10y 末日 {SEAL['pit_last']}",
              str(row[1]) == SEAL["pit_last"], f"(实 {row[1]})")
        con.close()
    return r.done()


def run_incremental():
    r = Report("增量校验")
    print("══ 增量校验(结构不变量, 与行数无关) ══")
    df = pd.read_csv(RAW)
    df["date"] = df["date"].astype(str)
    r.chk("列集 {date,us10y}", set(df.columns) == {"date", "us10y"},
          f"({list(df.columns)})")
    r.chk("日期唯一递增", bool(df.date.is_unique and df.date.is_monotonic_increasing))
    r.chk("无空值", int(df.us10y.isna().sum()) == 0,
          f"(实 {int(df.us10y.isna().sum())})")
    r.chk(f"值域 ({RANGE[0]},{RANGE[1]})",
          bool((df.us10y > RANGE[0]).all() and (df.us10y < RANGE[1]).all()),
          f"({df.us10y.min():.2f}~{df.us10y.max():.2f})")
    v = df.set_index("date").us10y
    for d, e in EXTREME_ANCHORS.items():
        r.chk(f"极值锚 {d}=={e}", abs(float(v[d]) - e) < 1e-9, f"(实 {v[d]})")
    for d, e in FRED_ANCHORS.items():
        r.chk(f"FRED补值 {d}=={e}", abs(float(v[d]) - e) < 1e-9, f"(实 {v[d]})")
    _dat = pd.read_csv(RAW, usecols=["us10y"], dtype={"us10y": str})["us10y"]
    dc = _dat.map(lambda x: len(x.split(".")[1]) if "." in x else 0)
    for nd, exp in PRECISION.items():
        got = int((dc == nd).sum())
        r.chk(f"精度 {nd}位小数={exp}", got == exp, f"(实 {got})")
    print("  -- 连续性: 绝对日变动(bp)(见文件头论证) --")
    d_bp = v.astype(float).diff().abs() * 100
    over = d_bp > CONTINUITY_BP
    r.chk(f"日变动 ≤ {CONTINUITY_BP:.0f}bp", int(over.sum()) == 0,
          f"(超限 {int(over.sum())} 日" +
          (f", 如 {list(d_bp.index[over].tolist()[:3])}" if over.any() else "") + ")")
    print(f"    (实测历史 max 日变动 {d_bp.max():.1f}bp; p99={d_bp.quantile(0.99):.1f}bp)")

    # ⑤ pit.db 研究层护栏(只读; 2026-10-02 补: 与 margin_review_check.py 同口径。
    #    背景: 原增量层只读 CSV、seal 层只看 pit 行数/末日, pit.db 值被篡改两层皆不亮)
    print("\n⑤ pit.db 研究层(只读, 增量在 PG 生产层)")
    if os.path.exists(DB):
        con = duckdb.connect(DB, read_only=True)
        row = con.execute(
            "SELECT count(*), count(*) FILTER (WHERE value IS NULL), "
            "min(value), max(value) FROM observation WHERE indicator_id='us10y'").fetchone()
        r.chk("pit.db us10y 无空值", row[1] == 0, f"(实 {row[1]})")
        lo_ok = row[2] is not None and row[3] is not None
        r.chk(f"pit.db us10y 值域内 ({RANGE[0]},{RANGE[1]})",
              bool(lo_ok and RANGE[0] <= row[2] and row[3] <= RANGE[1]),
              f"({row[2]:.3e} ~ {row[3]:.3e})" if lo_ok else "(空值/全空)")
        con.close()
    return r.done()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seal", action="store_true")
    ap.add_argument("--all", action="store_true")
    a = ap.parse_args()
    rc = 0
    if a.seal or a.all:
        rc |= run_seal()
        if a.all:
            print()
    if not a.seal or a.all:
        rc |= run_incremental()
    return rc


if __name__ == "__main__":
    sys.exit(main())