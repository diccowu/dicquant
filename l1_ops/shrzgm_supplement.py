#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""社融 shrzgm 半自动补数(2026-09-28 A项)。

背景: akshare macro_china_shrzgm 停更于 2026-04; 缺口由央行《金融统计数据报告》
      "前N月社会融资规模增量累计 X 万亿元" 人工差分补足。本脚本把该流程半自动化。

流程:
  1. 抓取: 央行官网列表页(goutongjiaoliu/113456/113469) 定位最新《X月金融统计数据报告》
  2. 解析: 正则提取 "前N月社会融资规模增量累计为 X 万亿元"(兼容 一季度/上半年/前N个月/X月)
  3. 差分: 最新累计 - 已有末月累计 = 单月增量; 与台账 OFFICIAL_INC 交叉比对
  4. 确认卡: 输出 {数值/来源URL/差分过程/口径判断/与台账比对} → 人工确认
  5. --apply: 追加 CSV + UPSERT NAS PG + 提示更新 shrzgm_review_check.py SEAL

用法:
  python shrzgm_supplement.py            # dry-run: 抓取→解析→差分→打印确认卡(不写库)
  python shrzgm_supplement.py --apply    # 确认后写库(CSV + PG)
  python shrzgm_supplement.py --use-alt  # 用备用源(上海金融办)交叉验证

注意:
  - 数据源为官方网页, 无 API; 措辞/格式可能改版, 解析失败会显式报错(不静默)
  - 铁律: 未经人工确认禁止 --apply
"""
import argparse
import json
import os
import re
import sys
import urllib.request
from datetime import date, timedelta

import pandas as pd

BASE = os.environ.get("SHRZGM_SUPP_BASE", "/mnt/c/new_tdx64/PYPlugins/user")
RAW_DIR = os.path.join(BASE, "data", "raw_data")
CSV = os.path.join(RAW_DIR, "macro_shrzgm_primary.csv")
PIT_INIT = os.environ.get("SHRZGM_PIT_INIT",
                          "/root/l1_ops/pit_init.py")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
PBC_LIST = "https://www.pbc.gov.cn/goutongjiaoliu/113456/113469/index.html"
PBC_ART = "https://www.pbc.gov.cn{url}"
ALT_BASE = "https://jrj.sh.gov.cn/SCGK194/index.html"   # 备用源列表(见 probe)
# 官方累计锚(2026, 万亿→亿, 容差±60) —— 与 shrzgm_review_check.py 一致
OFFICIAL_CUM = {1: 72200, 2: 96000, 3: 148300, 4: 154500,
                5: 174800, 6: 208400, 7: 222500, 8: 239100}
OFFICIAL_INC = {5: 20293, 6: 33600, 7: 14100, 8: 16600}
LAG_DAYS = 17


def log(m):
    print(f"[{date.today()}] {m}", flush=True)


def http_get(url, timeout=25):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
    for enc in ("utf-8", "gb18030", "gbk"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "ignore")


def html_to_text(html):
    t = re.sub(r"<script.*?</script>|<style.*?</style>", "", html, flags=re.S)
    t = re.sub(r"<[^>]+>", " ", t)
    t = re.sub(r"&nbsp;|&#160;", " ", t)
    return re.sub(r"\s+", " ", t)


def find_report_urls(html, base_url=PBC_ART):
    """列表页 → [(标题文本, 完整URL)] 含'金融统计数据报告'"""
    links = re.findall(r'href="(/goutongjiaoliu/\d+/\d+/\d+/index\.html)"[^>]*>([^<]*)<',
                       html)
    out = []
    for href, text in links:
        if "金融统计数据报告" in text:
            out.append((text.strip(), base_url.format(url=href)))
    return out


def parse_cumulative(text):
    """从报告正文提取累计增量(亿元)。兼容措辞:
        - '前八个月社会融资规模增量累计为23.91万亿元'
        - '一季度社会融资规模增量增量累计为14.83万亿元'/'社会融资规模增量累计为14.83万亿元'
        - '上半年社会融资规模增量为…' (无'累计'时只提示, 需人工判)
    返回 (累计万亿值, 月份数) 或 (None, None)
    """
    m = re.search(r"社会融资规模增量累计为\s*([\d.]+)\s*万亿", text)
    if m:
        return float(m.group(1)), None   # 月份数由调用方从标题/日期推
    return None, None


def month_count_from_title(title):
    """'2026年8月金融统计数据报告' → (2026, 8); '2026年一季度' → (2026, 3)
    失败 → (None, None)。年份从标题动态取(2026-09-29 qucoder ④: 原硬编码 2026)"""
    m = re.search(r"(\d{4})年(\d{1,2})月金融统计数据报告", title)
    if m:
        return int(m.group(1)), int(m.group(2))
    y = re.search(r"(\d{4})年", title)
    year = int(y.group(1)) if y else None
    if year is None:
        return None, None
    for kw, n in [("一季度", 3), ("二季度", 6), ("上半年", 6),
                  ("三季度", 9), ("前三季度", 9), ("全年", 12), ("十二个月", 12)]:
        if kw in title:
            return year, n
    return year, None


def period_end(year, n):
    """(年份, 第n月) → 该月末 date"""
    if n == 12:
        return date(year, 12, 31)
    return date(year, n + 1, 1) - timedelta(days=1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="确认后写库(默认 dry-run)")
    ap.add_argument("--use-alt", action="store_true", help="备用源(上海金融办)")
    a = ap.parse_args()

    log(f"模式: {'APPLY(写库)' if a.apply else 'DRY-RUN(只出确认卡)'}")

    # ── 1. 读取现有 CSV 末行 ──
    if not os.path.exists(CSV):
        log(f"FAIL: 未找到 {CSV}")
        return 2
    df = pd.read_csv(CSV, encoding="utf-8-sig", dtype=str)
    last_row = df.iloc[-1]
    last_month = pd.Period(last_row["date"], freq="M")
    last_cum = float(last_row["shrzgm_cum"])
    log(f"现有数据: 末日 {last_row['date']} 累计={last_cum:,.0f} 单月={last_row['shrzgm_inc']}")

    # ── 2. 抓取报告 ──
    if a.use_alt:
        log("备用源: 上海金融办")
        html = http_get(ALT_BASE)
        art_url = ALT_BASE
        text = html_to_text(html)
        title_m = re.search(r"(20\d{2}年[^<]{0,10}金融统计数据报告)", text)
        title = title_m.group(1) if title_m else "备用源报告"
        art_text = text
    else:
        log("抓取央行列表页...")
        list_html = http_get(PBC_LIST)
        reports = find_report_urls(list_html)
        if not reports:
            log("FAIL: 列表页未找到'金融统计数据报告'链接(页面改版?)")
            return 1
        title, art_url = reports[0]
        log(f"最新报告: {title} → {art_url}")
        art_html = http_get(art_url)
        art_text = html_to_text(art_html)

    # ── 3. 解析累计增量 ──
    cum_w, _ = parse_cumulative(art_text)
    if cum_w is None:
        log("FAIL: 未解析到'社会融资规模增量累计为X万亿元'(措辞改版?)")
        log(f"  片段: ...{art_text[art_text.find('社会融资规模'):art_text.find('社会融资规模')+120]}...")
        return 1
    new_cum = round(cum_w * 10000)          # 万亿 → 亿
    rep_year, n_month = month_count_from_title(title)
    log(f"解析: 累计 {cum_w} 万亿 = {new_cum:,} 亿 (报告 {rep_year} 年第 {n_month} 月)")
    if n_month is None:
        # 2026-09-29 qucoder ③: 月份推断失败应显式退出(原 mean_a_month_end(None) 崩溃)
        log("FAIL: 无法从标题推断报告月份, 请人工确认归属月份后手动补数")
        log(f"  标题原文: {title}")
        return 1
    new_date = period_end(rep_year, n_month).isoformat()
    new_p = pd.Period(new_date, freq="M")

    # ── 3.5 已是最新判定(2026-09-28 修: 报告月份已在库 → 干净退出, 不生成误导性确认卡) ──
    if new_p <= last_month:
        log(f"已是最新: 报告月份 {new_p} ≤ 现有末月 {last_month} → 无需补数")
        if new_p == last_month:
            log(f"  核对: 库内累计={last_cum:,.0f} / 报告累计={new_cum:,} → "
                f"{'✅ 一致' if abs(last_cum - new_cum) <= 1 else '❌ 不一致(需人工核查)'}")
        else:
            log(f"  注: 报告({new_p})早于库内末月({last_month}), 无需动作")
        return 0

    inc = int(round(new_cum - last_cum))
    log(f"差分: {new_cum:,.0f} - {last_cum:,.0f} = {inc:,} 亿 (单月增量)")

    # ── 4. 交叉校验 ──
    # 官方锚 OFFICIAL_CUM/INC 为 2026 年台账登记值, 仅同年同月才比对
    # (2026-09-29 qucoder ④: 年份动态后, 跨年报告(如 2027-01)不得误比对 2026 锚)
    checks = []
    if rep_year == 2026:
        if n_month in OFFICIAL_CUM:
            ok = abs(new_cum - OFFICIAL_CUM[n_month]) <= 60
            checks.append(f"官方累计锚 {n_month}月={OFFICIAL_CUM[n_month]:,} → "
                          f"{'✅' if ok else '❌ 偏离'}")
        if n_month in OFFICIAL_INC:
            ok = inc == OFFICIAL_INC[n_month]
            checks.append(f"官方差分锚 {n_month}月≈{OFFICIAL_INC[n_month]:,} → "
                          f"{'✅' if ok else '⚠️ 与台账值不符(+/-注)'}")
    else:
        checks.append(f"⚠️ 报告年份 {rep_year} ≠ 台账锚点年份 2026, 锚点比对跳过(人工核对)")
    # 量级合理性: 单月增量 3000~50000 亿为常态(2026 实测 1.4万~3.4万)
    if not (3000 <= inc <= 50000):
        checks.append(f"⚠️ 单月增量 {inc:,} 超出常态区间(3000~50000 亿), 需人工复核")
    yoy_txt = re.search(r"比上年同期(多|少)([\d.]+)亿元", art_text)

    # ── 5. 确认卡 ──
    card = {
        "report_title": title,
        "report_url": art_url,
        "report_retrieved": date.today().isoformat(),
        "period": new_date,
        "month_count": n_month,
        "new_cum": new_cum,
        "last_cum": int(last_cum),
        "inc": inc,
        "official_cum_match": checks[0] if checks else "N/A",
        "yoy_note": (yoy_txt.group(0) if yoy_txt else None),
        "apply_warning": "UNCONFIRMED - 未经人工确认禁止写库" if not a.apply else "CONFIRMED",
    }
    print("\n" + "=" * 72)
    print("📋 补数确认卡")
    print("=" * 72)
    print(f"  报告      : {title}")
    print(f"  来源      : {art_url}")
    print(f"  归属月份  : {new_date} (第 {n_month} 月)")
    print(f"  累计      : {new_cum:,} 亿 (官方 {cum_w} 万亿)")
    print(f"  上一期    : {last_row['date']} 累计 {last_cum:,.0f} 亿")
    print(f"  单月增量  : {inc:,} 亿")
    print(f"  ┌─ 差分预览(人工只需核这两点) ─────────────────────────")
    print(f"  │  {last_row['date']}(库内) 累计 {last_cum:,.0f}")
    print(f"  │  − {new_date}(本期) 累计 {new_cum:,.0f}")
    print(f"  │  = 单月增量 {inc:,} 亿")
    print(f"  │  ① 与上月环比是否合理(常态 3000~50000 亿)")
    print(f"  │  ② 累计值与央行新闻稿原文是否一致(见上方来源 URL)")
    print(f"  └──────────────────────────────────────────────────────")
    print(f"  口径判断  : 官方累计/差分 {'✅' if n_month else '⚠️月份未定'}")
    if yoy_txt:
        print(f"  同比佐证  : {yoy_txt.group(0)}")
    for c in checks:
        print(f"  {c}")
    print("-" * 72)
    print("  ① 请核对累计值与央行官网一致; ② 确认无口径修订; ③ 确认后运行")
    print(f"     python shrzgm_supplement.py --apply")
    print("=" * 72)

    if not a.apply:
        log("DRY-RUN 结束 (未写库)")
        return 0

    # ── 6. --apply 写库(先 PG 后 CSV: PG 失败零改动可重试, CSV 失败下次幂等重做) ──
    # UPSERT PG
    import importlib.util
    import psycopg2
    spec = importlib.util.spec_from_file_location("pit", PIT_INIT)
    pit = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pit)
    dsnenv = os.environ.get("L1_PG_DSN")
    conn = psycopg2.connect(dsnenv or "host=100.76.208.125 port=5432 user=postgres "
                                     "dbname=quant connect_timeout=20")
    from psycopg2.extras import execute_values
    p = date.fromisoformat(new_date)
    ann = pit._announcement_date("M", LAG_DAYS, p)
    rows = [("shrzgm", p, ann, date.today().isoformat(), float(inc), "initial")]
    with conn.cursor() as cur:
        execute_values(cur, """INSERT INTO l1_observation
            (indicator_id, period_date, announcement_date, vintage_date, value, status)
            VALUES %s ON CONFLICT (indicator_id, period_date, vintage_date) DO NOTHING""",
                       rows)
        n_ins = cur.rowcount
    conn.commit()
    log(f"PG 已 UPSERT shrzgm {new_date} (ann={ann}, 插入 {n_ins} 行)")
    conn.close()

    # 追加 CSV(幂等: 若已存在该行则跳过 —— 防 PG 成功后 CSV 半程失败的重跑)
    if new_date in set(df["date"]):
        log(f"CSV 已含 {new_date} (幂等跳过); 当前 {len(df)} 行")
    else:
        new_row = pd.DataFrame([{"date": new_date,
                                 "shrzgm_cum": str(int(new_cum)),
                                 "shrzgm_inc": str(int(inc))}])
        df2 = pd.concat([df, new_row], ignore_index=True)
        # ⚠️ 编码红线(2026-09-29 qucoder ①): 社融 CSV 为 **UTF-8 无 BOM**(台账 L191,
        #    首字节 646174 实测)。若用 utf-8-sig 写出会加 BOM(efbbbf) → 台账漂移。
        #    读取用 utf-8-sig 兼容(旧文件可能带 BOM), 写出必须 utf-8 保持无 BOM。
        df2.to_csv(CSV, index=False, encoding="utf-8")
        log(f"CSV 已追加: {new_date} 累计{new_cum:,} 单月{inc:,} → {CSV} ({len(df2)} 行)")

    log("⚠️ 完成后请更新 shrzgm_review_check.py 的 SEAL(行数/末日/指纹) 并登记台账")
    return 0


if __name__ == "__main__":
    sys.exit(main())