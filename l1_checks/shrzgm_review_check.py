#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""社融 shrzgm 独立验收脚本——两层校验(2026-09-28 策略b批改)。

不 import 构建脚本, 自行拉源独立复核 CSV + pit.db。
  【定稿校验】(--seal)  锁指纹/行数/起止 + pit.db 行数/末日
  【增量校验】(默认)    V2列/无空 / V3官方累计锚 / V4年度重置+年内差分 /
                        V5差分补值精确 / V6 lag=17 / V7 CSV↔DB 一致

⚠️ 月频 + 口径断点注意项(用户 2026-09-28 指示):
  - SEAL 更新节奏 = **每月定稿后**(月频), 不随每日增量刷新。
  - **口径断点期禁用连续性断言**: shrzgm 有 v1a/v1b/v2a 口径分段(2015/2017/2018 切换),
    且 2026 全年 v3 口径未调整; 故本脚本**不做**单月增量连续性断言,
    改以 **V4 年度重置 + 年内差分闭合**(恒等式级, 更强且不误报) 作为结构性校验。
  - 差分补值(V5)为官方累计锚的派生物, 属结构性事实, 不随增量失效。
  - ★ A 项(社融半自动补数)落地后: 新增月份会使 V1 行数/起止变化 →
    须先跑 `--seal` 更新基线, 再走"复检→终检"流程(见 SEAL 注释)。
"""
import argparse
import hashlib
import os
import sys
from datetime import date, timedelta

BASE_RAW = os.environ.get(
    "SHRZGM_CHECK_RAW",
    r"C:\new_tdx64\PYPlugins\user\data\raw_data" if os.name == "nt"
    else "/mnt/c/new_tdx64/PYPlugins/user/data/raw_data")
BASE_PIT = os.environ.get(
    "SHRZGM_CHECK_PIT",
    r"C:\new_tdx64\PYPlugins\user\data\pit" if os.name == "nt"
    else "/mnt/c/new_tdx64/PYPlugins/user/data/pit")
CSV = os.path.join(BASE_RAW, "macro_shrzgm_primary.csv")
DB = os.path.join(BASE_PIT, "pit.db")

# ── 定稿基线(2026-09-28 批改; 月频 → 每月定稿后更新) ──
SEAL = {
    "date": "2026-09-28",
    "csv_sha16": "851f3f5dbea87926",
    "csv_rows": 140,
    "csv_first": "2015-01-31",
    "csv_last": "2026-08-31",
    "pit_rows": 140,
    "pit_last": "2026-08-31",
}
# 官方锚(2026, 万亿→亿, 容差±60): 前N月累计 —— 结构性历史事实
OFFICIAL_CUM = {1: 72200, 2: 96000, 3: 148300, 4: 154500,
                5: 174800, 6: 208400, 7: 222500, 8: 239100}
OFFICIAL_INC = {5: 20293, 6: 33600, 7: 14100, 8: 16600}
LAG = 17


def sha16(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()[:16]


def month_end(ym):
    y, m = int(ym[:4]), int(ym[4:])
    if m == 12:
        return date(y, 12, 31)
    return date(y, m + 1, 1) - timedelta(days=1)


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


def read_csv():
    lines = open(CSV, encoding="utf-8-sig").read().splitlines()
    hdr = lines[0].split(",")
    body = [l.split(",") for l in lines[1:] if l.strip()]
    return hdr, body


def run_seal():
    r = Report("定稿校验")
    print(f"══ 定稿校验(基线 {SEAL['date']}; 月频 → 每月定稿后更新) ══")
    hdr, body = read_csv()
    r.chk(f"指纹 {SEAL['csv_sha16']}", sha16(CSV) == SEAL["csv_sha16"],
          f"(实 {sha16(CSV)})")
    r.chk(f"行数 {SEAL['csv_rows']}", len(body) == SEAL["csv_rows"], f"(实 {len(body)})")
    r.chk(f"起止 {SEAL['csv_first']}~{SEAL['csv_last']}",
          body[0][0] == SEAL["csv_first"] and body[-1][0] == SEAL["csv_last"],
          f"(实 {body[0][0]}~{body[-1][0]})")
    if not os.path.exists(DB):
        r.chk(f"pit.db 存在 ({DB})", False, "(文件缺失 → 定稿件不完整)")
    else:
        import duckdb
        con = duckdb.connect(DB, read_only=True)
        row = con.execute("SELECT count(*), max(period_date) FROM observation "
                          "WHERE indicator_id='shrzgm'").fetchone()
        r.chk(f"pit.db shrzgm 行数 {SEAL['pit_rows']}", row[0] == SEAL["pit_rows"],
              f"(实 {row[0]})")
        r.chk(f"pit.db shrzgm 末日 {SEAL['pit_last']}", str(row[1]) == SEAL["pit_last"],
              f"(实 {row[1]})")
        con.close()
    return r.done()


def run_incremental():
    r = Report("增量校验")
    print("══ 增量校验(结构不变量, 与行数无关) ══")
    if not os.path.exists(CSV):
        r.chk(f"文件存在 ({CSV})", False)
        return r.done()
    hdr, body = read_csv()

    print("  -- 结构 --")
    r.chk("列 = ['date','shrzgm_cum','shrzgm_inc']",
          hdr == ["date", "shrzgm_cum", "shrzgm_inc"], f"(实 {hdr})")
    r.chk("无空值", all(all(x for x in row) for row in body))
    r.chk("日期递增", all(body[i][0] < body[i + 1][0] for i in range(len(body) - 1)))
    r.chk("全部月末", all(month_end(row[0].replace("-", "")[:6]).isoformat() == row[0]
                          for row in body))

    idx = {row[0]: (float(row[1]), float(row[2])) for row in body}

    print(f"  -- 官方累计锚(2026 前 N 月, 容差±60) --")
    for m, off in OFFICIAL_CUM.items():
        key = month_end(f"2026{m:02d}").isoformat()
        if key not in idx:
            r.chk(f"2026-{m:02d} 存在", False)
            continue
        got = idx[key][0]
        r.chk(f"2026-{m:02d} 累计 {off}", abs(got - off) <= 60, f"(实 {got})")

    print("  -- 年度重置 + 年内差分闭合(替代口径断点期的连续性断言) --")
    bad_reset = [row[0] for row in body
                 if row[0].endswith("-01-31") and float(row[1]) != float(row[2])]
    r.chk("每年 1 月 cum==inc(年度重置)", not bad_reset, f"(异常 {bad_reset[:3]})")
    bad_diff = []
    for i in range(1, len(body)):
        if body[i][0][:4] == body[i - 1][0][:4]:
            if float(body[i][1]) - float(body[i - 1][1]) != float(body[i][2]):
                bad_diff.append(body[i][0])
    r.chk("年内 cum 差分 == inc(逐月闭合)", not bad_diff, f"(异常 {bad_diff[:3]})")

    print("  -- 官方差分补值精确(2026-05~08) --")
    for m, v in OFFICIAL_INC.items():
        key = month_end(f"2026{m:02d}").isoformat()
        if key not in idx:
            r.chk(f"2026-{m:02d} 存在", False)
            continue
        got = idx[key][1]
        r.chk(f"2026-{m:02d} 单月增量 {v}", got == v, f"(实 {got})")

    if not os.path.exists(DB):
        r.chk(f"pit.db 存在 ({DB})", False)
        return r.done()
    import duckdb
    con = duckdb.connect(DB, read_only=True)
    rows = con.execute("SELECT period_date, announcement_date FROM observation "
                       "WHERE indicator_id='shrzgm' ORDER BY period_date").fetchall()
    print(f"  -- lag={LAG}(发布日口径) --")
    bad_lag = [d for d, a in rows if (a - d).days != LAG]
    r.chk(f"lag={LAG} 全表一致", not bad_lag, f"(异常 {[str(x) for x in bad_lag[:3]]})")

    print("  -- CSV ↔ pit.db 一致 --")
    db_vals = con.execute("SELECT period_date, value FROM observation "
                          "WHERE indicator_id='shrzgm' ORDER BY period_date").fetchall()
    con.close()
    r.chk("行数一致", len(db_vals) == len(body), f"(CSV {len(body)} / DB {len(db_vals)})")
    if len(db_vals) == len(body):
        mm = [i for i in range(len(body))
              if db_vals[i][0].isoformat() != body[i][0]
              or float(db_vals[i][1]) != float(body[i][2])]
        r.chk("逐行值一致", not mm, f"(不一致 index={mm[:5]})")
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