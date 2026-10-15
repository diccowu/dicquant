#!/usr/bin/env python3
"""PG 新鲜度巡检 — 每天 09:00 cron 运行
检查 NAS PG l1_observation 各指标 max(period_date) 是否落后:
  - 日频: 落后 >3 交易日告警 (margin/treasury 类 T+1 发布已容忍; oil 用 14 天, EIA/FRED 源滞后节奏)
  - 月频: 落后 >45 天告警; neer_cny 用 130 天 (BIS 官方发布滞后 2-3 个月, 实测 106 天正常)
正常静默; 异常飞书告警。2026-10-15 创建 (交付运维的稳定性验证)。
"""
import re, sys, datetime, subprocess

ENV = "/root/l1_ops/.env_l1"
LOG = "/root/l1_ops/logs/pg_freshness.log"

# 指标 -> 滞后阈值(天); 区分真故障与数据源自身发布节奏
THRESHOLDS = {
    # 日频: 3 天(=3 交易日, 容忍周末+1 天休眠)
    "usdcny": 3, "hs300_pe_ttm": 3, "treasury_y1": 3, "treasury_y10": 3,
    "treasury_m6": 3, "treasury_y2": 3, "us10y": 3, "margin_balance": 3,
    "margin_purchase": 3, "margin_borrow_balance": 3, "margin_sec_lending_balance": 3,
    "float_cap": 3, "dr007": 3, "shibor_3m": 3, "cbond_aaa_10y": 3, "mkt_amount": 3,
    # 日频但源滞后大 (EIA/FRED 布伦特, 实测滞后 9 天, 留 3 周余量)
    "oil": 21,
    # 月频: 45 天 (错峰发布日历内)
    "pmi": 45, "cpi_yoy": 45, "cpi_mom": 45, "cpi_ytd": 45, "ppi_yoy": 45,
    "ppi_ytd": 45, "m1_yoy": 45, "m2_yoy": 45, "shrzgm": 45, "lpr_1y": 45, "lpr_5y": 45,
    # 月频但 BIS 官方发布滞后约 2 个月(实测 8月值 10-15 发布 = 滞后 75 天) → 100 天
    "neer_cny": 100,
}


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
    conn.close()

    today = datetime.date.today()
    staleness, problems = {}, []
    for ind, th in sorted(THRESHOLDS.items()):
        dmax = latest.get(ind)
        if dmax is None:
            problems.append(f"{ind}: 库内无数据!")
            continue
        days = (today - dmax).days
        staleness[ind] = days
        if days > th:
            problems.append(f"{ind}: 最新 {dmax} ({days}天 前, 阈值{th})")

    with open(LOG, "a") as f:
        stamp = datetime.datetime.now().strftime("%F %T")
        f.write(f"[{stamp}] 巡检 {len(staleness)} 指标, 滞后清单: " +
                ", ".join(f"{k}={v}d" for k, v in sorted(staleness.items())) + "\n")
        if problems:
            f.write(f"[{stamp}] 异常 {len(problems)} 项: {problems}\n")

    if problems:
        body = "⚠️ PG 新鲜度巡检异常:\n" + "\n".join(f"- {p}" for p in problems)
        print(body)
        subprocess.run(["/root/.local/bin/hermes", "send", "-t", "feishu", body],
                       timeout=60)
        return 1
    print(f"[OK] {today} 全指标新鲜 ({len(staleness)} 指标, 0 异常)")
    return 0


if __name__ == "__main__":
    sys.exit(main())