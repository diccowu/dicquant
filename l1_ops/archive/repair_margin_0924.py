#!/usr/bin/env python3
"""两融 2026-09-24 残缺值修复（事故沉淀 2026-09-28）

背景: 源按交易所异步发布, 09-24 采集时点星耀仅发布 SSE, 聚合层把"单交易所"当全市场 SUM
写入 → margin_balance 低 49%。修复: 从源重取 09-24 完整三所明细 → 重算聚合 → 修正 L0 CSV
→ PG 旧行置 deprecated + 写入修正行(vintage=今日, PIT 语义: 修正值在今日才可得)。

用法: python repair_margin_0924.py [--apply]   (默认 dry-run 只打印)
"""
import argparse, importlib.util, sys
from datetime import date
import pandas as pd

RAW = "/mnt/c/new_tdx64/PYPlugins/user/data/raw_data"
PRIM = f"{RAW}/macro_margin_ad_primary.csv"
DAILY = f"{RAW}/macro_margin_ad_daily.csv"
TARGET = "2026-09-24"
DSN = os.environ.get("L1_PG_DSN") or ("host=100.76.208.125 port=5432 user=postgres "
       "dbname=quant connect_timeout=20 ")

spec = importlib.util.spec_from_file_location("l1u", "/root/l1_ops/l1_update.py")
L1 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(L1)
_L = lambda m: print(f"[{date.today()}] {m}", flush=True)


def fetch_source_rows():
    """从星耀重取 TARGET 日完整明细"""
    L1._ad_login()
    import AmazingData as ad
    info = ad.InfoData()
    ms = info.get_margin_summary(begin_date=20260924, end_date=20260924, is_local=False)
    MC = {"TRADE_DATE": "date", "EXCHANGE": "exchange",
          "SUM_BORROW_MONEY_BALANCE": "borrow_balance",
          "SUM_PURCH_WITH_BORROW_MONEY": "purchase_amt",
          "SUM_REPAYMENT_OF_BORROW_MONEY": "repayment_amt",
          "SUM_SEC_LENDING_BALANCE": "sec_lending_balance",
          "SUM_SALES_OF_BORROWED_SEC": "sec_sale_vol",
          "SUM_MARGIN_TRADE_BALANCE": "margin_trade_balance"}
    df = ms.rename(columns=MC)[list(MC.values())].copy()
    df["date"] = pd.to_datetime(df["date"].astype(str)).dt.strftime("%Y-%m-%d")
    return df.sort_values(["date", "exchange"]).reset_index(drop=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="实际写盘(默认 dry-run)")
    a = ap.parse_args()

    _L(f"模式: {'APPLY(真实写盘)' if a.apply else 'DRY-RUN(只打印)'}")

    # ── 1. 源取完整明细 ──
    src = fetch_source_rows()
    _L(f"[1] 源 {TARGET} 明细 {len(src)} 行: {sorted(src['exchange'])}")
    need = L1._margin_need(TARGET)
    if not need <= set(src["exchange"]):
        _L(f"    ✋ 源仍残缺(缺 {sorted(need - set(src['exchange']))}) → 中止, 不改任何数据")
        return 1
    _L("    源已齐全 ✅")

    # ── 2. L0 primary CSV ──
    oldp = pd.read_csv(PRIM, dtype=str)
    before_p = oldp[oldp["date"] == TARGET]
    _L(f"[2] primary 修复前 {TARGET}: {len(before_p)} 行 {sorted(before_p['exchange'])}")
    newp = pd.concat([oldp[oldp["date"] != TARGET],
                      src.astype(str)], ignore_index=True)
    newp = newp.sort_values(["date", "exchange"]).reset_index(drop=True)
    after_p = newp[newp["date"] == TARGET]
    _L(f"    primary 修复后: {len(after_p)} 行 {sorted(after_p['exchange'])}")
    if a.apply:
        L1.atomic_write_csv(newp, PRIM)
        _L(f"    ✅ 已写入 {PRIM} ({len(newp)} 行)")

    # ── 3. L0 daily CSV（重算聚合）──
    bal = int(src["margin_trade_balance"].astype(float).sum())
    pur = int(src["purchase_amt"].astype(float).sum())
    _L(f"[3] 聚合重算: margin_balance={bal:,}  margin_purchase={pur:,}")
    oldd = pd.read_csv(DAILY, dtype=str)
    _L(f"    daily 修复前 {TARGET}: "
       f"{oldd[oldd['date']==TARGET][['margin_balance','margin_purchase']].to_dict('records')}")
    newd = oldd.copy()
    newd.loc[newd["date"] == TARGET, "margin_balance"] = str(bal)
    newd.loc[newd["date"] == TARGET, "margin_purchase"] = str(pur)
    if len(newd[newd["date"] == TARGET]) == 0:
        newd = pd.concat([newd, pd.DataFrame(
            [{"date": TARGET, "margin_balance": str(bal), "margin_purchase": str(pur)}])],
            ignore_index=True).sort_values("date").reset_index(drop=True)
    _L(f"    daily 修复后: "
       f"{newd[newd['date']==TARGET][['margin_balance','margin_purchase']].to_dict('records')}")
    if a.apply:
        L1.atomic_write_csv(newd, DAILY)
        _L(f"    ✅ 已写入 {DAILY} ({len(newd)} 行)")

    # ── 4. PG: 旧行 deprecated + 写入修正行 ──
    import psycopg2
    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    _L(f"[4] PG {TARGET} 修复前:")
    cur.execute("""SELECT indicator_id, vintage_date, value, status FROM l1_observation
                   WHERE indicator_id IN ('margin_balance','margin_purchase')
                     AND period_date=%s ORDER BY indicator_id, vintage_date""", (TARGET,))
    for r in cur.fetchall():
        _L(f"    {r[0]:16s} vin={r[1]} value={float(r[2]):,.0f} status={r[3]}")
    if not a.apply:
        _L("    (dry-run 未改 PG)")
        conn.close()
        _L("=== DRY-RUN 结束 ===")
        return 0

    cur.execute("""UPDATE l1_observation SET status='deprecated'
                   WHERE indicator_id IN ('margin_balance','margin_purchase')
                     AND period_date=%s AND status='initial'""", (TARGET,))
    _L(f"    旧行置 deprecated: {cur.rowcount} 行")
    from psycopg2.extras import execute_values
    vin = date.today().isoformat()
    rows = [("margin_balance", TARGET, TARGET, vin, float(bal), "initial"),
            ("margin_purchase", TARGET, TARGET, vin, float(pur), "initial")]
    execute_values(cur, """INSERT INTO l1_observation
        (indicator_id, period_date, announcement_date, vintage_date, value, status)
        VALUES %s ON CONFLICT (indicator_id, period_date, vintage_date) DO NOTHING""", rows)
    _L(f"    写入修正行: {cur.rowcount} 行 (vintage={vin})")
    conn.commit()
    cur.execute("""SELECT indicator_id, vintage_date, value, status FROM l1_observation
                   WHERE indicator_id IN ('margin_balance','margin_purchase')
                     AND period_date=%s ORDER BY indicator_id, vintage_date""", (TARGET,))
    _L(f"[4] PG {TARGET} 修复后:")
    for r in cur.fetchall():
        _L(f"    {r[0]:16s} vin={r[1]} value={float(r[2]):,.0f} status={r[3]}")
    conn.close()
    _L("=== APPLY 完成 ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
