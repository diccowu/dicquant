# -*- coding: utf-8 -*-
"""第7项国债独立验收脚本(treasury_y1/treasury_y10)——两层校验(2026-09-28 策略b批改)。

背景:原脚本为"定稿点快照式"期望值(行数/区间/最新日写死), 增量更新后必然红灯。
拆两层:
  【定稿校验】(--seal)  锁指纹/行数/末日 + pit.db 行数/末日 —— 签发/定稿时跑
  【增量校验】(默认)    列集/递增/无空/值域/连续性(绝对bp) —— 每次更新后跑, 与行数无关

连续性依据(2026-09-28 实测全历史):
  - 收益率序列**不能用相对偏离**(低利率下相对值失真: y1 真实相对偏离 >15% 达 109 天,
    us10y >15% 130 天, 都是 2010~2016 真实行情); **改用绝对日变动(bp)**:
      y1 真实 max=48.2bp  → 阈值 60bp (0.60pp)  零误报
      y10 真实 max=20.8bp → 阈值 30bp (0.30pp)  零误报
      事故形态(1.68→16.8 等数量级错位) = 1500bp, 必被抓住
  - 阈值远超正常波动, 仅拦"数量级事故"; 对收益率日间 1~2bp 的正常波动零干扰。
"""
import argparse
import hashlib
import os
import sys

import duckdb
import pandas as pd

# 路径 env(统一命名 L1_CHECK_*, 2026-10-02; 旧名保留回退兼容)
BASE = os.environ.get("L1_CHECK_BASE") or os.environ.get(
    "TREASURY_CHECK_BASE", "/mnt/c/new_tdx64/PYPlugins/user")
RAW_DIR = os.environ.get("L1_CHECK_RAW") or os.environ.get(
    "TREASURY_CHECK_RAW", os.path.join(BASE, "data", "raw_data"))
RAW = os.path.join(RAW_DIR, "macro_treasury_ad_primary.csv")
DB = os.environ.get("L1_CHECK_DB", os.path.join(BASE, "data", "pit", "pit.db"))

COLS = ["date", "m3", "m6", "y1", "y2", "y3", "y5", "y7", "y10", "y30"]
TERMS = [c for c in COLS if c != "date"]

# ── 定稿基线(2026-09-28 批改; 每次走完 修改→复检→终检 后由定稿人更新并登记台账) ──
SEAL = {
    "date": "2026-09-28",
    "csv_sha16": "9d9c0c43ae49763e",   # 实测(2026-09-28): 增量后实物
    "csv_rows": 4138,
    "csv_last": "2026-09-24",
    "pit_rows": 4138,                    # pit.db 研究层; 2026-10-02 补尾 09-19..09-24 (=L0 源, PG 同键零冲突)
    "pit_last": "2026-09-24",
}
# ── 结构性不变量 ──
RANGE_TERMS = (0.0, 10.0)
CONTINUITY_BP = {"y1": 60.0, "y10": 30.0}   # 绝对日变动上限(bp); 见文件头论证


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
        for iid in ["treasury_y1", "treasury_y10"]:
            row = con.execute("SELECT count(*), max(period_date) FROM observation "
                              "WHERE indicator_id=?", [iid]).fetchone()
            r.chk(f"pit.db {iid} 行数 {SEAL['pit_rows']}",
                  row[0] == SEAL["pit_rows"], f"(实 {row[0]})")
            r.chk(f"pit.db {iid} 末日 {SEAL['pit_last']}",
                  str(row[1]) == SEAL["pit_last"], f"(实 {row[1]})")
        con.close()
    return r.done()


def run_incremental():
    r = Report("增量校验")
    print("══ 增量校验(结构不变量, 与行数无关) ══")
    df = pd.read_csv(RAW)
    df["date"] = df["date"].astype(str)
    r.chk("列集 9期限", set(df.columns) == set(COLS),
          f"(缺 {sorted(set(COLS) - set(df.columns))} / 多 {sorted(set(df.columns) - set(COLS))})")
    r.chk("日期唯一递增", bool(df.date.is_unique and df.date.is_monotonic_increasing))
    r.chk("全表无空值", int(df[TERMS].isna().sum().sum()) == 0,
          f"(实 {int(df[TERMS].isna().sum().sum())})")
    for c in TERMS:
        s = df[c].astype(float)
        r.chk(f"{c} 值域 [{RANGE_TERMS[0]},{RANGE_TERMS[1]}]",
              bool(s.min() >= RANGE_TERMS[0] and s.max() <= RANGE_TERMS[1]),
              f"({s.min():.2f}~{s.max():.2f})")
    print("  -- 连续性: 绝对日变动(bp)(见文件头论证) --")
    dfp = df.set_index("date")
    for c, limit in CONTINUITY_BP.items():
        s = dfp[c].astype(float)
        d_bp = s.diff().abs() * 100
        over = d_bp > limit
        r.chk(f"{c} 日变动 ≤ {limit:.0f}bp",
              int(over.sum()) == 0,
              f"(超限 {int(over.sum())} 日" +
              (f", 如 {list(dfp.index[over].tolist()[:3])}" if over.any() else "") + ")")
        print(f"    (实测历史 max 日变动 {d_bp.max():.1f}bp; 本次速览 p99={d_bp.quantile(0.99):.1f}bp)")

    # ⑤ pit.db 研究层护栏(只读; 2026-10-02 补: 与 margin_review_check.py 同口径。
    #    背景: 原增量层只读 CSV、seal 层只看 pit 行数/末日, pit.db 值被篡改两层皆不亮)
    print("\n⑤ pit.db 研究层(只读, 增量在 PG 生产层)")
    if os.path.exists(DB):
        con = duckdb.connect(DB, read_only=True)
        for iid in ["treasury_y1", "treasury_y10"]:
            row = con.execute(
                "SELECT count(*), count(*) FILTER (WHERE value IS NULL), "
                "min(value), max(value) FROM observation WHERE indicator_id=?",
                [iid]).fetchone()
            r.chk(f"pit.db {iid} 无空值", row[1] == 0, f"(实 {row[1]})")
            lo_ok = row[2] is not None and row[3] is not None
            r.chk(f"pit.db {iid} 值域内 [{RANGE_TERMS[0]},{RANGE_TERMS[1]}]",
                  bool(lo_ok and RANGE_TERMS[0] <= row[2] and row[3] <= RANGE_TERMS[1]),
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