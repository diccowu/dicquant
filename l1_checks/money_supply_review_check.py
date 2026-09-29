#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""M1/M2 货币供应量 独立验收脚本——两层校验(2026-09-28 策略b批改)。

原脚本大部分断言本就是结构性的(V2值域/V3锚点/V4注5/V5空值/V6环比自洽/V7覆盖),
仅 V1 含快照(行数224/起止) → 现拆两层:
  【定稿校验】(--seal)  锁指纹/行数/起止 + pit.db 行数/末日
  【增量校验】(默认)    列集/月末/无缺月/V2值域/V3锚点/V4注5/V5空值/V6环比自洽/V7覆盖

⚠️ 月频指标注意项(用户 2026-09-28 指示):
  - SEAL 更新节奏 = **每月定稿后**(日频是每日, 月频是每月), 不随每日增量刷新
  - **口径断点期禁用连续性断言**: M1 存在 2024-01 可比口径切换(央行注5),
    2024-01 的 m1_mom 已按设计置空(跨口径产物); 故本脚本**不做**环比连续性断言,
    改以"环比自洽(V6, 独立重拉源)"作为等价的结构性校验 —— 更强且不误报。
  - 连续性若要做, 只能限 2025 起(口径稳定段), 且阈值需按余额环比特性单独论证;
    当前版本不引入, 保持"零误报优先"。
"""
import argparse
import hashlib
import os
import sys
from datetime import date, timedelta

BASE_DIR = os.environ.get("MONEY_CHECK_BASE", "/mnt/c/new_tdx64/PYPlugins/user")
RAW_DIR = os.environ.get("MONEY_RAW_DIR", os.path.join(BASE_DIR, "data", "raw_data"))
DB = os.path.join(BASE_DIR, "data", "pit", "pit.db")
F = "macro_money_supply_primary.csv"
RAW = os.path.join(RAW_DIR, F)

# ── 定稿基线(2026-09-28 批改; 月频 → 每月定稿后更新) ──
SEAL = {
    "date": "2026-09-28",
    "csv_sha16": "4e6db134113197ed",
    "csv_rows": 224,
    "csv_first": "2008-01-31",
    "csv_last": "2026-08-31",
    "pit_rows": 224,
    "pit_last": "2026-08-31",
}
COLS = ["date", "m2_yoy", "m2_mom", "m1_yoy", "m1_mom"]
V2_RANGE = [("m2_yoy", -5, 40), ("m1_yoy", -20, 50), ("m2_mom", -5, 10), ("m1_mom", -10, 15)]
# 央行官方「注5」2024 各月末 M1 可比增速(%) —— 结构性历史事实
M1_2024 = {"2024-01": 3.3, "2024-02": 2.6, "2024-03": 2.3, "2024-04": 0.6, "2024-05": -0.8,
           "2024-06": -1.7, "2024-07": -2.6, "2024-08": -3.0, "2024-09": -3.3,
           "2024-10": -2.3, "2024-11": -0.7, "2024-12": 1.2}
M1_EASTMONEY_OLD = {"2024-01": 5.9, "2024-02": 1.2, "2024-03": 1.1, "2024-04": -1.4,
                    "2024-05": -4.2, "2024-06": -5.0, "2024-07": -6.6, "2024-08": -7.3,
                    "2024-09": -7.4, "2024-10": -6.1, "2024-11": -3.7, "2024-12": -1.4}
ANCHORS = {"2026-08": (7.5, 4.1), "2026-05": (8.6, 5.5), "2025-03": (7.0, 1.6)}


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
        self.warns = []

    def chk(self, name, cond, detail=""):
        print(f"  [{'PASS' if cond else 'FAIL'}] {name} {detail}")
        if not cond:
            self.problems.append(name)

    def done(self):
        print(f"\n── {self.title} 结论 ──")
        if self.warns:
            print("WARN: " + "; ".join(self.warns))
        if self.problems:
            print(f"FAIL [{len(self.problems)}]: {self.problems}")
            return 1
        print("ALL PASS ✅")
        return 0


def run_seal():
    r = Report("定稿校验")
    print(f"══ 定稿校验(基线 {SEAL['date']}; 月频 → 每月定稿后更新) ══")
    import pandas as pd
    n = sum(1 for _ in open(RAW, encoding="utf-8")) - 1
    df = pd.read_csv(RAW, encoding="utf-8-sig", dtype=str)
    r.chk(f"指纹 {SEAL['csv_sha16']}", sha16(RAW) == SEAL["csv_sha16"], f"(实 {sha16(RAW)})")
    r.chk(f"行数 {SEAL['csv_rows']}", n == SEAL["csv_rows"], f"(实 {n})")
    r.chk(f"起止 {SEAL['csv_first']}~{SEAL['csv_last']}",
          df.date.iloc[0] == SEAL["csv_first"] and df.date.iloc[-1] == SEAL["csv_last"],
          f"(实 {df.date.iloc[0]}~{df.date.iloc[-1]})")
    if not os.path.exists(DB):
        r.chk(f"pit.db 存在 ({DB})", False, "(文件缺失 → 定稿件不完整)")
    else:
        import duckdb
        con = duckdb.connect(DB, read_only=True)
        for iid in ["m1_yoy", "m2_yoy"]:
            row = con.execute("SELECT count(*), max(period_date) FROM observation "
                              "WHERE indicator_id=?", [iid]).fetchone()
            r.chk(f"pit.db {iid} 行数 {SEAL['pit_rows']}", row[0] == SEAL["pit_rows"],
                  f"(实 {row[0]})")
            r.chk(f"pit.db {iid} 末日 {SEAL['pit_last']}",
                  str(row[1]) == SEAL["pit_last"], f"(实 {row[1]})")
        con.close()
    return r.done()


def run_incremental():
    import pandas as pd
    r = Report("增量校验")
    print("══ 增量校验(结构不变量, 与行数无关) ══")
    if not os.path.exists(RAW):
        r.chk(f"文件存在 ({RAW})", False)
        return r.done()
    df = pd.read_csv(RAW, encoding="utf-8-sig")

    print("  -- 结构 --")
    r.chk(f"列名/顺序 == {COLS}", list(df.columns) == COLS, f"(实 {list(df.columns)})")
    per = pd.PeriodIndex(df["date"], freq="M")
    exp = pd.period_range(per.min(), per.max(), freq="M")
    r.chk("无缺月", len(exp.difference(per)) == 0, f"(缺 {list(exp.difference(per))[:3]})")
    r.chk("全部月末日期", bool(pd.to_datetime(df["date"]).dt.is_month_end.all()))
    r.chk("无重复日期", not df["date"].duplicated().any())

    print("  -- 值域 --")
    for c, lo, hi in V2_RANGE:
        s = df[c].dropna()
        r.chk(f"{c} ∈ [{lo},{hi}]", bool(s.between(lo, hi).all()),
              f"(实 [{s.min()},{s.max()}])")

    print("  -- 官方锚点(央行新闻稿原文) --")
    idx = df.assign(_m=df["date"].str[:7]).set_index("_m")
    for ym, (m2, m1) in ANCHORS.items():
        ok = ym in idx.index and (float(idx.loc[ym, "m2_yoy"]),
                                  float(idx.loc[ym, "m1_yoy"])) == (m2, m1)
        r.chk(f"{ym} 期望({m2},{m1})", ok)

    print("  -- 央行注5: 2024 M1 可比口径回溯值(全12期) --")
    for ym, v in M1_2024.items():
        r.chk(f"{ym} m1_yoy={v}", float(idx.loc[ym, "m1_yoy"]) == v,
              f"(实 {float(idx.loc[ym, 'm1_yoy'])})")

    print("  -- 空值 --")
    r.chk("m2_yoy 无空值", bool(df["m2_yoy"].notna().all()))
    r.chk("m1_yoy 无空值", bool(df["m1_yoy"].notna().all()))
    r.chk("2024-01 m1_mom 已置空(跨口径产物)",
          bool(df.loc[df["date"].str[:7] == "2024-01", "m1_mom"].isna().all()))
    r.chk("其余月份 m1_mom 均有值",
          bool(df.loc[df["date"].str[:7] != "2024-01", "m1_mom"].notna().all()))

    print("  -- 环比/同比自洽(独立重拉源; 替代口径断点期的连续性断言) --")
    try:
        import akshare as ak
        s = ak.macro_china_money_supply()

        def eom(ym):
            y, m = ym.replace("月份", "").split("年")
            y, m = int(y), int(m)
            nxt = date(y + 1, 1, 1) if m == 12 else date(y, m + 1, 1)
            return (nxt - timedelta(days=1)).isoformat()

        q = pd.DataFrame({"date": s["月份"].map(eom),
                          "m2_q": s["货币和准货币(M2)-数量(亿元)"],
                          "m1_q": s["货币(M1)-数量(亿元)"]}).sort_values("date").reset_index(drop=True)
        csv_by_date = df.set_index("date")
        for c, qc in [("m2_mom", "m2_q"), ("m1_mom", "m1_q")]:
            calc = ((q[qc] / q[qc].shift(1) - 1) * 100).reset_index(drop=True)
            csv_v = csv_by_date[c].reindex(q["date"]).reset_index(drop=True)
            mask = (q["date"] >= "2025-01-31").reset_index(drop=True)
            d = (calc - csv_v).abs()[mask]
            mx = float(d.max()) if len(d.dropna()) else 0.0
            r.chk(f"{c} 2025起 环比==余额环比 最大偏差 {round(mx,6)}pp ≤0.01", mx <= 0.01)
    except Exception as e:  # noqa: BLE001
        r.warns.append(f"源重拉失败: {e}")
        print(f"  [WARN] 源重拉失败: {e}")

    print("  -- 覆盖范围正确性 --")
    n_bad = sum(1 for ym, old in M1_EASTMONEY_OLD.items()
                if float(idx.loc[ym, "m1_yoy"]) == old)
    r.chk("2024 段旧口径值残留 0 期", n_bad == 0, f"(实 {n_bad})")
    try:
        s2 = ak.macro_china_money_supply()
        s2["_m"] = s2["月份"].str.replace("年", "-").str.replace("月份", "").str[:7]
        for ym in ["2023-12", "2020-06", "2015-01"]:
            rr = s2[s2["_m"] == ym]
            src_v = float(rr["货币(M1)-同比增长"].iloc[0]) if len(rr) else None
            csv_v = float(idx.loc[ym, "m1_yoy"])
            r.chk(f"{ym} m1_yoy={csv_v} 与源一致(未被误改)",
                  src_v is not None and abs(src_v - csv_v) < 1e-9, f"(源 {src_v})")
    except Exception as e:  # noqa: BLE001
        r.warns.append(f"源比对失败: {e}")
        print(f"  [WARN] 源比对失败: {e}")
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