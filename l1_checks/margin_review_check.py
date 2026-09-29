# -*- coding: utf-8 -*-
"""第6项两融验收脚本(margin_balance/margin_purchase)——两层校验(2026-09-28 策略b重构)。

背景:原脚本为"定稿点快照式"期望值(行数/区间/口径段写死),每次增量更新后必然红灯,
红灯语义不清(分不清"数据坏了"还是"数据正常增长了")。现拆两层:

  【定稿校验】(--seal)  锁指纹 + 行数, 签发/定稿时跑一次
      红灯含义 = 定稿件被改动 → 必须重新走复检流程
      期望值取自 COVERAGE_REGISTRY.md 登记, 或本文件 SEAL 常量(定稿时更新)

  【增量校验】(默认)    恒等式 + 连续性 + 护栏, 每次数据更新后跑
      红灯含义 = 数据出现结构性问题(聚合错/跳变/残缺) → 需人工介入
      断言与行数无关, 增量天然不误报

用法:
  python margin_review_check.py            # 增量校验(日常, 绿灯=数据健康)
  python margin_review_check.py --seal     # 定稿校验(锁定稿指纹/行数)
  python margin_review_check.py --all      # 两层都跑
"""
import argparse
import hashlib
import os
import sys

import duckdb
import pandas as pd

BASE = os.environ.get("MARGIN_CHECK_BASE", "/mnt/c/new_tdx64/PYPlugins/user")
RAW = os.environ.get("MARGIN_CHECK_RAW", os.path.join(BASE, "data", "raw_data"))
DB = os.path.join(BASE, "data", "pit", "pit.db")
PRIM = os.path.join(RAW, "macro_margin_ad_primary.csv")
DAILY = os.path.join(RAW, "macro_margin_ad_daily.csv")

# ── 定稿基线(2026-09-28 两融 09-24 残缺修复后定稿点) ────────────────────────
# 更新时机:每次走完「修改→复检→用户终检定稿」后, 由定稿人更新此处并登记台账。
SEAL = {
    "date": "2026-09-28",
    "prim_sha16": "2d747c3228770ad9",
    "prim_rows": 8895,
    "daily_sha16": "e6fc66ed24b05bfa",
    "daily_rows": 4007,
    "daily_last": "2026-09-24",
    "pit_rows_per_ind": 4003,     # pit.db 研究层(9/25 重灌版), 增量在 PG 生产层
    "pit_last": "2026-09-18",
}
# ── 结构性不变量(任何时点都必须成立, 与行数无关) ───────────────────────────
NEEQ_START = "2023-02-13"
RANGE = {"margin_balance": (0.0, 5e12), "margin_purchase": (0.0, 1e13)}

# 连续性断言: 只对**存量**指标 margin_balance 适用
#   阈值依据(2026-09-28 实测全历史): 成熟期(2015+) 相对 20 日滚动中位偏离
#     >20% 13 日 / >30% 4 日 / >40% **0 日**(零误报)
#     而 09-24 残缺态偏离 = 49% → 40% 阈值可零误报地抓住本次事故
#   早期(2010~2014)为市场培育期(余额从百万级涨到千亿级, 跨 4 个数量级), 连续性无意义 → 排除
#   ⚠️ 流量指标 margin_purchase **不做**连续性断言, 原因(实测): 其天然波动极大
#      (成熟期最大真实偏离 868% —— 2024-10 行情), 而 09-24 残缺态仅 701%,
#      即真实行情比事故更猛 → 任何能抓 701% 的阈值都会误报真实行情(统计不可分)。
#      purchase 的残缺检出**依赖上方"交易所完整性"与"聚合层无残缺日"两条断言**(实测可直接命中)。
MATURITY_START = "2015-01-01"
CONTINUITY = {"margin_balance": 0.40}   # 指标 → 相对20日中位偏离上限
ROLL_WIN = 20
# 参与聚合的列(必须零空值; 其余列存在台账已登记的合法豁免, 见 run_incremental 注释)
AGG_COLS = ["borrow_balance", "purchase_amt", "sec_lending_balance", "margin_trade_balance"]


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


# ══════════════════════════════════════════════════════════════════════════
# 第一层:定稿校验(锁指纹 + 行数)
# ══════════════════════════════════════════════════════════════════════════
def run_seal():
    print(f"══ 定稿校验(基线日期 {SEAL['date']}) ══")
    print("\n① 交付物指纹/行数(锁定期望值)")
    r = Report("定稿校验")
    for label, path, sha_k, rows_k in [
        ("原始层 primary", PRIM, "prim_sha16", "prim_rows"),
        ("聚合层 daily", DAILY, "daily_sha16", "daily_rows"),
    ]:
        got_sha, exp_sha = sha16(path), SEAL[sha_k]
        n = sum(1 for _ in open(path, encoding="utf-8")) - 1
        r.chk(f"{label} 指纹 {exp_sha}", got_sha == exp_sha, f"(实 {got_sha})")
        r.chk(f"{label} 行数 {SEAL[rows_k]}", n == SEAL[rows_k], f"(实 {n})")
    dl = pd.read_csv(DAILY)
    r.chk(f"daily 末日 {SEAL['daily_last']}", str(dl.date.iloc[-1]) == SEAL["daily_last"],
          f"(实 {dl.date.iloc[-1]})")
    # pit.db 研究层: 缺库即红灯(2026-09-28 qucoder 建议①: 原 os.path.exists 静默跳过会漏检)
    if not os.path.exists(DB):
        r.chk(f"pit.db 存在 ({DB})", False, "(文件缺失 → 定稿件不完整)")
    else:
        con = duckdb.connect(DB, read_only=True)
        for iid in RANGE:
            row = con.execute(
                "SELECT count(*), max(period_date) FROM observation WHERE indicator_id=?",
                [iid]).fetchone()
            r.chk(f"pit.db {iid} 行数 {SEAL['pit_rows_per_ind']}",
                  row[0] == SEAL["pit_rows_per_ind"], f"(实 {row[0]})")
            r.chk(f"pit.db {iid} 末日 {SEAL['pit_last']}",
                  str(row[1]) == SEAL["pit_last"], f"(实 {row[1]})")
        con.close()
    return r.done()


# ══════════════════════════════════════════════════════════════════════════
# 第二层:增量校验(恒等式 + 连续性 + 护栏;与行数无关)
# ══════════════════════════════════════════════════════════════════════════
def run_incremental():
    print("══ 增量校验(结构不变量, 与行数无关) ══")
    r = Report("增量校验")

    print("\n① 原始层结构")
    prim = pd.read_csv(PRIM)
    prim["date"] = prim["date"].astype(str)
    # 恒等式:融资融券余额 = 融资余额 + 融券余额
    d = (prim["margin_trade_balance"] - prim["borrow_balance"] - prim["sec_lending_balance"]).abs()
    r.chk("恒等式 融资融券余额=融资余额+融券余额 0差", int((d > 1).sum()) == 0,
          f"(非零 {int((d>1).sum())})")
    # 主键唯一
    r.chk("主键 (date,exchange) 无重复", not prim.duplicated(["date", "exchange"]).any(),
          f"(重复 {int(prim.duplicated(['date','exchange']).sum())})")
    # 护栏:交易所完整性(≥NEEQ_START 必须三所;之前两所)
    cnt = prim.groupby("date")["exchange"].apply(lambda s: len(set(s)))
    late_bad = sorted(cnt[(cnt.index >= NEEQ_START) & (cnt != 3)].to_dict().items())
    early_bad = sorted(cnt[(cnt.index < NEEQ_START) & (cnt != 2)].to_dict().items())
    r.chk(f"护栏 交易所完整性(≥{NEEQ_START} 三所 / 之前两所)",
          not late_bad and not early_bad,
          f"(三所期异常 {late_bad[:3]} / 两所期异常 {early_bad[:3]})")
    r.chk("数值非负", bool((prim.select_dtypes("number").fillna(0) >= 0).all().all()))
    r.chk("日期递增", bool(prim["date"].is_monotonic_increasing))
    # 空值断言(2026-09-28 qucoder 建议②): 原值域/恒等式/非负断言对 NaN 有盲点
    #   (值域 min/max 跳过 NaN; 恒等式 NaN 比较恒 False 被漏; 非负 fillna(0) 吞 NaN)
    #   仅对**参与聚合的列**要求无 NaN —— 非聚合列存在台账已登记的合法豁免:
    #   `2026-08-17 SZSE` 的 repayment_amt/sec_sale_vol 为空(东财补值无该明细,
    #   见 COVERAGE_REGISTRY.md 两融节「2026-08-17 SZSE 回补」, 不入 PIT 无影响)。
    for c in AGG_COLS:
        n_na = int(prim[c].isnull().sum())
        r.chk(f"聚合列 {c} 无空值", n_na == 0, f"(实 {n_na})")
    na_cols = {c: int(prim[c].isnull().sum()) for c in prim.columns
               if prim[c].isnull().any()}
    print(f"  [INFO] 全表空值分布(非聚合列合法豁免见台账): {na_cols or '无'}")

    print("\n② 聚合层与原始层一致(逐日)")
    dl = pd.read_csv(DAILY)
    dl["date"] = dl["date"].astype(str)
    for c in ["margin_balance", "margin_purchase"]:
        n_na = int(dl[c].isnull().sum())
        r.chk(f"聚合层 {c} 无空值", n_na == 0, f"(实 {n_na})")
    r.chk("聚合层日期唯一", bool(dl.date.is_unique))
    r.chk("聚合层日期递增", bool(dl.date.is_monotonic_increasing))
    # 聚合恒等式:margin_balance == SUM(borrow+sec_lending);margin_purchase == SUM(purchase_amt)
    # 仅对"交易所齐全日"比对(残缺日按设计不入聚合层)
    need = cnt[cnt.index.map(lambda x: (3 if x >= NEEQ_START else 2) == cnt[x])].index
    agg = prim[prim["date"].isin(need)].groupby("date").agg(
        mb=("borrow_balance", "sum"), sl=("sec_lending_balance", "sum"),
        mp=("purchase_amt", "sum"))
    agg["mb"] = agg["mb"] + agg["sl"]
    al = dl.merge(agg[["mb", "mp"]], left_on="date", right_index=True, how="inner")
    r.chk("聚合恒等式 margin_balance == SUM(融资+融券) 0差",
          int(((al.margin_balance - al.mb).abs() > 1).sum()) == 0,
          f"(非零 {int(((al.margin_balance-al.mb).abs()>1).sum())} / 比对 {len(al)} 日)")
    r.chk("聚合恒等式 margin_purchase == SUM(融资买入额) 0差",
          int(((al.margin_purchase - al.mp).abs() > 1).sum()) == 0,
          f"(非零 {int(((al.margin_purchase-al.mp).abs()>1).sum())})")
    # 聚合层不得含残缺日(设计保证:残缺日不入聚合)
    dl_inc = sorted(set(dl.date) - set(need))
    r.chk("聚合层无残缺日", not dl_inc, f"(异常 {dl_inc[:3]})")

    print(f"\n③ 连续性(仅存量指标, 成熟期 {MATURITY_START}+, 相对 {ROLL_WIN} 日滚动中位)")
    dl_m = dl[dl.date >= MATURITY_START].reset_index(drop=True)
    for col, limit in CONTINUITY.items():
        s = dl_m[col].astype(float)
        med = s.rolling(ROLL_WIN, min_periods=5).median()
        dev = (s / med - 1).abs()
        over = dev > limit
        r.chk(f"{col} 相对{ROLL_WIN}日中位偏离 ≤ {limit:.0%}",
              int(over.sum()) == 0,
              f"(超限 {int(over.sum())} 日" +
              (f", 如 {dl_m.date[over].tolist()[:3]}" if over.any() else "") + ")")
    skip = [c for c in RANGE if c not in CONTINUITY]
    if skip:
        print(f"  [SKIP] {', '.join(skip)} 不做连续性断言(流量指标, 天然波动大于事故幅度 — "
              f"见文件头常量注释); 其残缺检出依赖 ①完整性 / ②聚合层无残缺日")

    print("\n④ 值域")
    for col, (lo, hi) in RANGE.items():
        s = dl[col].astype(float)
        r.chk(f"{col} 值域内 ({lo:.0e},{hi:.0e})",
              bool(s.min() >= lo and s.max() <= hi), f"({s.min():.3e} ~ {s.max():.3e})")

    print("\n⑤ pit.db 研究层(只读, 增量在 PG 生产层)")
    if os.path.exists(DB):
        con = duckdb.connect(DB, read_only=True)
        for iid, (lo, hi) in RANGE.items():
            row = con.execute(
                "SELECT count(*), count(*) FILTER (WHERE value IS NULL), "
                "min(value), max(value) FROM observation WHERE indicator_id=?", [iid]).fetchone()
            r.chk(f"{iid} 无空值", row[1] == 0, f"(实 {row[1]})")
            r.chk(f"{iid} 值域内", bool(lo <= row[2] and row[3] <= hi),
                  f"({row[2]:.3e} ~ {row[3]:.3e})")
        con.close()
    return r.done()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seal", action="store_true", help="只跑定稿校验(锁指纹/行数)")
    ap.add_argument("--all", action="store_true", help="两层都跑")
    a = ap.parse_args()
    rc = 0
    if a.seal or a.all:
        rc |= run_seal()
        if a.all:
            print()
    if not a.seal or a.all:
        rc |= run_incremental()
    sys.exit(rc)


if __name__ == "__main__":
    main()
