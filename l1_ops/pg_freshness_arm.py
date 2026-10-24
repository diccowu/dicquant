#!/usr/bin/env python3
"""PG 新鲜度巡检 — 发布日历基准（2026-10-18 改造, 替代固定滞后天数）
判定: 库内最新期 vs 应到期(官方发布日历推算) —— 发布间隔本身不再误报。
背景: 固定45天标尺被用户裁定推翻("错的逻辑不允许保持"); pmi 47d 误报实证
(9月PMI 9-30发布, 10-18巡检47天=正常, 10月PMI 10-31才发布)。
2026-10-15 创建; 2026-10-18 改造: THRESHOLDS → PUBLISH_CALENDAR。
"""
import re, sys, datetime, subprocess
from datetime import date, timedelta

ENV = "/home/ubuntu/l1_ops/.env_l1"
LOG = "/home/ubuntu/l1_ops/logs/pg_freshness.log"

# 发布规则: (rule, tolerance_days, note)
#  rule 语义(period 惯例见注):
#   daily_t1   当日发布当日值(period=交易日)      → 应到期 = 最近交易日
#   daily_t2   T+1 发布 T 日值(period=交易日)     → 应到期 = 最近交易日前一日
#   pmi        月末发布当月(period=月初, 实测9-30发布9月50.1) → 本月最后一天已过→本月1日; 否则上月1日
#   cpi_9th    次月9日发布上月(period=月末)        → 今天≥本月9日→上月月末; 否则上上月月末
#   mid_15th   次月15日发布上月(period=月末)       → 今天≥本月15日→上月月末; 否则上上月月末
#   lpr_20th   每月20日发布当月(period=20日)       → 今天≥本月20日→本月20日; 否则上月20日
#   bimonthly  BIS双月发布滞后~2月(period=月初)    → 两个月前月初
PUBLISH_RULES = {
    "usdcny": ("daily_t1", 2, "当日发布"),
    "hs300_pe_ttm": ("daily_t1", 2, "当日发布"),
    "dr007": ("daily_t1", 2, "当日发布"),
    "shibor_3m": ("daily_t1", 2, "当日发布"),
    "cbond_aaa_10y": ("daily_t1", 2, "当日发布"),
    "float_cap": ("daily_t1", 2, "当日发布"),
    "treasury_m6": ("daily_t2", 2, "T+1发布 AmazingData(实测 vintage 滞后1天)"),
    "treasury_y1": ("daily_t2", 2, "T+1发布 AmazingData(实测 vintage 滞后1天)"),
    "treasury_y2": ("daily_t2", 2, "T+1发布 AmazingData(实测 vintage 滞后1天)"),
    "treasury_y10": ("daily_t2", 2, "T+1发布 AmazingData(实测 vintage 滞后1天)"),
    "us10y": ("daily_t1", 3, "akshare东财(非FRED)"),
    "margin_balance": ("daily_t2", 2, "T+1发布"),
    "margin_purchase": ("daily_t2", 2, "T+1发布"),
    "margin_borrow_balance": ("daily_t2", 2, "T+1发布"),
    "margin_sec_lending_balance": ("daily_t2", 2, "T+1发布"),
    "mkt_amount": ("daily_t2", 3, "T+1发布; ARM: NAS推送时序+1天"),
    "pmi": ("pmi", 2, "月末发布当月(period=月初)"),
    "cpi_yoy": ("cpi_9th", 3, "次月9日发布上月"),
    "cpi_mom": ("cpi_9th", 3, "次月9日发布上月"),
    "cpi_ytd": ("cpi_9th", 3, "次月9日发布上月"),
    "ppi_yoy": ("cpi_9th", 3, "次月9日发布上月"),
    "ppi_ytd": ("cpi_9th", 3, "次月9日发布上月"),
    "m1_yoy": ("mid_15th", 3, "次月15日发布上月"),
    "m2_yoy": ("mid_15th", 3, "次月15日发布上月"),
    "shrzgm": ("mid_15th", 3, "次月15日发布上月"),
    "lpr_1y": ("lpr_20th", 2, "每月20日发布当月"),
    "lpr_5y": ("lpr_20th", 2, "每月20日发布当月"),
    "neer_cny": ("bimonthly", 15, "BIS双月滞后~2月"),
    "neer_cfets": ("mid_15th", 7, "CFETS周频源,月频化(取月末最后交易日)"),
    "oil": ("daily_t1", 6, "FRED/EIA转发仍活(10-18双端实查,10-14正常); EIA滞后2-3天"),
}

def _month_end(d):
    """d 所在月的最后一天"""
    if d.month == 12:
        return date(d.year, 12, 31)
    return date(d.year, d.month + 1, 1) - timedelta(days=1)

def _prev_month(d):
    if d.month == 1:
        y, m = d.year - 1, 12
    else:
        y, m = d.year, d.month - 1
    last = _month_end(date(y, m, 1))
    return date(y, m, min(d.day, last.day))

def expected_period(rule, today, last_trade, prev_trade):
    """推算应到期 period_date（各指标惯例格式）; 返回 date 或 None(无法推算)"""
    if rule == "daily_t1":
        return last_trade
    if rule == "daily_t2":
        return prev_trade
    if rule == "pmi":
        # 月末发布当月: 本月最后一天已过且为今天或之后 → 应到期=本月1日
        if today >= _month_end(today):
            return date(today.year, today.month, 1)
        pm = _prev_month(today)
        return date(pm.year, pm.month, 1)
    if rule == "cpi_9th":
        if today.day >= 9:
            return _month_end(_prev_month(today))
        pm = _prev_month(today)
        return _month_end(_prev_month(pm))
    if rule == "mid_15th":
        if today.day >= 15:
            return _month_end(_prev_month(today))
        pm = _prev_month(today)
        return _month_end(_prev_month(pm))
    if rule == "lpr_20th":
        if today.day >= 20:
            return date(today.year, today.month, 20)
        pm = _prev_month(today)
        return date(pm.year, pm.month, 20)
    if rule == "bimonthly":
        pm = _prev_month(today)
        p2 = _prev_month(pm)
        return date(p2.year, p2.month, 1)
    raise ValueError(rule)

def main():
    env = open(ENV).read()
    m = re.search(r'L1_PG_DSN="([^"]+)"', env)
    if not m:
        print("未找到 L1_PG_DSN"); return 2
    dsn = m.group(1)

    import psycopg2
    conn = psycopg2.connect(dsn)
    cur = conn.cursor()
    cur.execute("""SELECT indicator_id, max(period_date) FROM l1_observation
                   GROUP BY indicator_id""")
    latest = dict(cur.fetchall())
    # 交易日锚: hs300_pe_ttm 的 period 集合 (A股交易日, 每交易日更新)
    cur.execute("""SELECT DISTINCT period_date FROM l1_observation
                   WHERE indicator_id='hs300_pe_ttm' ORDER BY period_date""")
    trade_days = [r[0] for r in cur.fetchall()]
    conn.close()

    today = date.today()
    # 最近交易日(≤今天) 与次近
    le = [d for d in trade_days if d <= today]
    last_trade = le[-1] if le else None
    prev_trade = le[-2] if len(le) >= 2 else last_trade

    problems = []
    for ind, (rule, tol, note) in sorted(PUBLISH_RULES.items()):
        dmax = latest.get(ind)
        if dmax is None:
            problems.append(f"{ind}: 库内无数据! [rule={rule} {note}]")
            continue
        if last_trade is None:
            problems.append(f"{ind}: 无法推算应到期(无交易日锚)")
            continue
        expect = expected_period(rule, today, last_trade, prev_trade)
        if expect is None:
            problems.append(f"{ind}: 规则 {rule} 无法推算应到期")
            continue
        if dmax < expect - timedelta(days=tol):
            problems.append(
                f"{ind}: 应到期 {expect} 库内 {dmax} 缺口 {(expect - dmax).days}天 "
                f"[rule={rule} {note}]")

    with open(LOG, "a") as f:
        stamp = datetime.datetime.now().strftime("%F %T")
        f.write(f"[{stamp}] 巡检 {len(PUBLISH_RULES)} 指标(发布日历基准), 异常 {len(problems)} 项\n")
        if problems:
            f.write(f"[{stamp}] 异常: {problems}\n")

    if problems:
        body = "⚠️ PG 新鲜度巡检异常:\n" + "\n".join(f"- {p}" for p in problems)
        print(body)
        subprocess.run(["/home/ubuntu/.local/bin/hermes", "send", "-t", "feishu", body],
                       timeout=60)
        return 1
    print(f"[OK] {today} 全指标新鲜 ({len(PUBLISH_RULES)} 指标, 0 异常) [发布日历基准]")
    return 0

if __name__ == "__main__":
    sys.exit(main())
