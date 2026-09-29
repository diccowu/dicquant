#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
L1 数据层日常运维脚本 —— 双模式, 办公室 & 家里 Hermes 共用同一份代码

    办公室 (local 模式):  增量起点=本地 L0 CSV → 采集 → append CSV → UPSERT NAS PG
    家里   (pg 模式):     增量起点=NAS PG   → 采集 → 只 UPSERT NAS PG (不碰 CSV)

铁律(不可违背):
    1. 只增量 append, 绝不重写/覆盖历史已定稿数据(错误数据不污染)
    2. 任何护栏失败 → 该指标不写盘、不落库(其它指标继续), 最终 rc!=0
    3. 幂等: 重复运行不产生重复行(CSV 去重 keep=last; PG 主键 ON CONFLICT)
    4. 反假: 拉取为空/源结构异常 → 报错, 不静默跳过

用法:
    # 办公室(默认 local): 从 CSV 起点增量, 同时维护 CSV + PG
    python l1_update.py --all --raw-dir /path/to/raw_data

    # 家里: 从 PG 起点增量, 只写 PG
    python l1_update.py --all --state-from pg

    python l1_update.py --daily | --monthly | --only us10y,usdcny
    python l1_update.py --all --dry-run

环境变量:
    L1_PG_DSN   NAS PG 连接串(默认内置)
    AD_USERNAME / AD_PASSWORD / AD_HOST / AD_PORT   星耀账号(默认内置)
"""
import argparse
import importlib.util
import os
import sys
import traceback
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

SCRIPT_DIR = Path(__file__).resolve().parent
# keepalive 30s: 防 NAT/中继掐空闲连接(参考 quant_tools/pg_conn.py 实测结论)
PG_DEFAULT = ("host=100.76.208.125 port=5432 user=postgres "
              "dbname=quant connect_timeout=20 "
              "keepalives=1 keepalives_idle=30 keepalives_interval=10 keepalives_count=6")

DAILY = ["hs300_pe_ttm", "treasury_y1", "treasury_y10", "us10y",
         "usdcny", "oil", "margin_balance", "margin_purchase", "float_cap"]
MONTHLY = ["pmi", "cpi_yoy", "cpi_mom", "cpi_ytd", "ppi_yoy", "ppi_ytd",
           "m1_yoy", "m2_yoy", "shrzgm"]

# 两融交易所完整性基准(与 pit_init 口径段一致): 2023-02-13 北交所两融开通起含 NEEQ
MARGIN_NEEQ_START = "2023-02-13"


def _margin_need(dstr):
    """某日应含的交易所集合(两融口径分段)"""
    return {"SSE", "SZSE", "NEEQ"} if str(dstr) >= MARGIN_NEEQ_START else {"SSE", "SZSE"}


def margin_complete_prefix(prim):
    """两融交易所完整性截断(2026-09-24 事故沉淀)。

    源按交易所**异步发布**, 残缺日参与 SUM 会显著低估全市场值(09-24 只含 SSE
    → 比真实值低 49%)。本函数:
      - 逐日核对交易所集合是否 ⊇ _margin_need(该日口径)
      - 返回 **首个残缺日之前的完整前缀**(不越过缺口 → 增量起点不会被推过缺口,
        残缺日不会变成永久空洞; 下次增量从缺口处重取, 源补齐即自愈)
      - 同时返回残缺明细 [(日期, 缺失交易所集合), ...] 供日志/告警

    入参/出参均为 DataFrame(需含 date / exchange 列); 无残缺时原样返回, bad=[]。
    """
    if prim is None or len(prim) == 0:
        return prim, []
    ex_sets = prim.groupby("date")["exchange"].apply(lambda s: set(s.astype(str)))
    bad = [(d, _margin_need(d) - ex_sets[d]) for d in sorted(ex_sets.index)
           if not _margin_need(d) <= ex_sets[d]]
    if not bad:
        return prim, []
    return prim[prim["date"] < bad[0][0]].reset_index(drop=True), bad


# ── 复用 pit_init.py 的注册表与发布日映射(单一事实源, 避免分叉) ──────────────
def load_pit_init(raw_dir=None, explicit=None):
    """定位 pit_init.py(注册表单一事实源)。部署时建议与之同目录"""
    cands = []
    if explicit:
        cands.append(Path(explicit))
    cands += [SCRIPT_DIR / "pit_init.py", SCRIPT_DIR.parent / "pit_init.py"]
    if raw_dir:
        cands.append(Path(raw_dir).parent.parent / "pit_init.py")
    for cand in cands:
        if cand.exists():
            spec = importlib.util.spec_from_file_location("pit_init", cand)
            m = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(m)
            return m
    raise FileNotFoundError("未找到 pit_init.py (注册表单一事实源)")


# ── 通用工具 ────────────────────────────────────────────────────────────────
def log(msg):
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


def atomic_write_csv(df, path):
    tmp = Path(str(path) + ".tmp")
    df.to_csv(tmp, index=False)
    os.replace(tmp, path)


def read_csv(path):
    return pd.read_csv(path, dtype=str)


def existing_max_date(df, col="date"):
    if len(df) == 0:
        return None
    return str(df[col].max())


def merge_append(old, new, keys, date_col="date"):
    if len(new) == 0:
        return old, 0
    combined = pd.concat([old, new], ignore_index=True)
    combined = combined.drop_duplicates(subset=keys, keep="last")
    added = len(combined) - len(old)
    combined = combined.sort_values(date_col).reset_index(drop=True)
    return combined, added


def guard(df, name, value_cols, ranges, date_col="date", dup_key=None):
    """护栏。dup_key: 同日多行源(如两融按交易所明细)传 ["date","exchange"]，默认按日期单行"""
    errs = []
    if len(df) == 0:
        errs.append("空表")
    for c in [date_col] + value_cols:
        if c not in df.columns:
            errs.append(f"缺列 {c}")
    if errs:
        raise ValueError(f"{name} 结构异常: {errs}")
    keys = dup_key or [date_col]
    for k in keys:
        if k not in df.columns:
            raise ValueError(f"{name} dup_key 缺列: {k}")
    if df[keys].duplicated().any():
        errs.append(f"键重复 {df[keys].duplicated().sum()} 行 {keys}")
    if len(keys) == 1 and not df[date_col].is_monotonic_increasing:
        errs.append("日期非递增")
    for c in value_cols:
        s = pd.to_numeric(df[c], errors="coerce")
        if s.isna().any():
            errs.append(f"{c} 含 NaN {s.isna().sum()} 行")
        lo, hi = ranges.get(c, (None, None))
        if lo is not None and s.min() < lo:
            errs.append(f"{c} 低于值域 {s.min()} < {lo}")
        if hi is not None and s.max() > hi:
            errs.append(f"{c} 超出值域 {s.max()} > {hi}")
    if errs:
        raise ValueError(f"{name} 护栏失败: {errs}")
    return True


def _filter_new(df, since, col, fmt="%Y-%m-%d"):
    """since: datetime.date | None → 只保留 > since 的行"""
    if since is None:
        return df.reset_index(drop=True)
    return df[df[col] > since.strftime(fmt)].reset_index(drop=True)


def _month_period(s_m):
    """'2026年08月份' / '202608' → ('2026-08-01', '2026-08-31')"""
    s = str(s_m)
    if "年" in s:
        y, m = s.split("年")[0], s.split("年")[1].replace("月份", "").replace("月", "")
    else:
        y, m = s[:4], s[4:6]
    y, m = int(y), int(m)
    first = date(y, m, 1)
    nxt = date(y + (m == 12), 1 if m == 12 else m + 1, 1)
    return first.isoformat(), (nxt - timedelta(days=1)).isoformat()


# ── 源采集器: 日频 (since: date|None) ───────────────────────────────────────
def collect_usdcny(since):
    """akshare currency_boc_safe (SAFE 官方中间价) → {date, usdcny}; 源单位 100外币/元 ÷100"""
    import akshare as ak
    df = ak.currency_boc_safe()
    dcol = "日期" if "日期" in df.columns else df.columns[0]
    out = df[[dcol, "美元"]].copy()
    out.columns = ["date", "usdcny"]
    out["date"] = pd.to_datetime(out["date"]).dt.strftime("%Y-%m-%d")
    out["usdcny"] = (pd.to_numeric(out["usdcny"], errors="coerce") / 100.0).round(4)
    out = out.dropna(subset=["usdcny"]).drop_duplicates("date", keep="last")
    out = out.sort_values("date").reset_index(drop=True)
    return _filter_new(out, since, "date")


def collect_us10y(since):
    """akshare bond_zh_us_rate (东财中美债宽表) → {date, us10y}"""
    import akshare as ak
    df = ak.bond_zh_us_rate(start_date="20100104")
    out = df[["日期", "美国国债收益率10年"]].copy()
    out.columns = ["date", "us10y"]
    out["date"] = pd.to_datetime(out["date"]).dt.strftime("%Y-%m-%d")
    out["us10y"] = pd.to_numeric(out["us10y"], errors="coerce").round(2)
    out = out.dropna(subset=["us10y"]).drop_duplicates("date", keep="last")
    out = out.sort_values("date").reset_index(drop=True)
    return _filter_new(out, since, "date")


def collect_hs300_pe(since):
    """akshare 中证官方 stock_zh_index_hist_csindex('000300') → {date, pe_ttm}"""
    import akshare as ak
    df = ak.stock_zh_index_hist_csindex(symbol="000300", start_date="20120904",
                                        end_date=date.today().strftime("%Y%m%d"))
    out = df[["日期", "滚动市盈率"]].copy()
    out.columns = ["date", "pe_ttm"]
    out["date"] = pd.to_datetime(out["date"]).dt.strftime("%Y-%m-%d")
    out["pe_ttm"] = pd.to_numeric(out["pe_ttm"], errors="coerce").round(2)
    out = out.dropna(subset=["pe_ttm"]).drop_duplicates("date", keep="last")
    out = out.sort_values("date").reset_index(drop=True)
    return _filter_new(out, since, "date")


def collect_oil(since):
    """FRED DCOILBRENTEU (EIA 布伦特即期) → {date, brent}; 境外源, 家里需代理"""
    import urllib.request
    url = ("https://fred.stlouisfed.org/graph/fredgraph.csv?id=DCOILBRENTEU"
           "&cosd=2026-01-01")
    raw = urllib.request.urlopen(url, timeout=90).read().decode()
    rows = [r.split(",") for r in raw.strip().split("\n")[1:] if r.strip()]
    out = pd.DataFrame([(r[0], r[1]) for r in rows], columns=["date", "brent"])
    out["brent"] = pd.to_numeric(out["brent"].replace(".", pd.NA), errors="coerce").round(2)
    out = out.dropna(subset=["brent"]).drop_duplicates("date", keep="last")
    out = out.sort_values("date").reset_index(drop=True)
    return _filter_new(out, since, "date")


# ── 源采集器: 月频 ──────────────────────────────────────────────────────────
def collect_pmi(since):
    """akshare macro_china_pmi (东财) → {date, pmi}; ⚠️ date='YYYY-MM'(对齐现有 CSV)"""
    import akshare as ak
    df = ak.macro_china_pmi()
    out = pd.DataFrame({"date": [f"{_month_period(m)[0][:7]}" for m in df["月份"]],
                        "pmi": pd.to_numeric(df["制造业-指数"], errors="coerce").round(1)})
    out = out.dropna(subset=["pmi"]).drop_duplicates("date", keep="last")
    out = out.sort_values("date").reset_index(drop=True)
    return _filter_new(out, since, "date", "%Y-%m")


def collect_cpi(since):
    """akshare macro_china_cpi → {date, cpi_yoy, cpi_mom, cpi_ytd}; date 月末"""
    import akshare as ak
    df = ak.macro_china_cpi()
    out = pd.DataFrame({
        "date": [_month_period(m)[1] for m in df["月份"]],
        "cpi_yoy": pd.to_numeric(df["全国-同比增长"], errors="coerce").round(1),
        "cpi_mom": pd.to_numeric(df["全国-环比增长"], errors="coerce").round(1),
        "cpi_ytd": pd.to_numeric(df["全国-累计"], errors="coerce").round(1),
    })
    out = out.dropna(subset=["cpi_yoy"]).drop_duplicates("date", keep="last")
    out = out.sort_values("date").reset_index(drop=True)
    return _filter_new(out, since, "date")


def collect_ppi(since):
    """akshare macro_china_ppi → {date, ppi_yoy, ppi_ytd}; 累计列=100+累计平均同比 → -100 还原"""
    import akshare as ak
    df = ak.macro_china_ppi()
    out = pd.DataFrame({
        "date": [_month_period(m)[1] for m in df["月份"]],
        "ppi_yoy": pd.to_numeric(df["当月同比增长"], errors="coerce").round(1),
        "ppi_ytd": (pd.to_numeric(df["累计"], errors="coerce") - 100.0).round(1),
    })
    out = out.dropna(subset=["ppi_yoy"]).drop_duplicates("date", keep="last")
    out = out.sort_values("date").reset_index(drop=True)
    return _filter_new(out, since, "date")


def collect_money_supply(since):
    """akshare macro_china_money_supply → {date, m2_yoy, m2_mom, m1_yoy, m1_mom}; date 月末"""
    import akshare as ak
    df = ak.macro_china_money_supply()
    out = pd.DataFrame({
        "date": [_month_period(m)[1] for m in df["月份"]],
        "m2_yoy": pd.to_numeric(df["货币和准货币(M2)-同比增长"], errors="coerce").round(1),
        "m2_mom": pd.to_numeric(df["货币和准货币(M2)-环比增长"], errors="coerce").round(4),
        "m1_yoy": pd.to_numeric(df["货币(M1)-同比增长"], errors="coerce").round(1),
        "m1_mom": pd.to_numeric(df["货币(M1)-环比增长"], errors="coerce").round(4),
    })
    out = out.dropna(subset=["m2_yoy"]).drop_duplicates("date", keep="last")
    out = out.sort_values("date").reset_index(drop=True)
    return _filter_new(out, since, "date")


def collect_shrzgm(since):
    """akshare macro_china_shrzgm (2026-04 后停更) → {date, shrzgm_cum, shrzgm_inc}
    ⚠️ 停更月份补数需央行金融统计数据报告(半自动)"""
    import akshare as ak
    df = ak.macro_china_shrzgm()
    rows = [( _month_period(m)[1], int(v)) for m, v in zip(df["月份"], df["社会融资规模增量"])]
    out = pd.DataFrame(rows, columns=["date", "shrzgm_inc"])
    out = out.drop_duplicates("date", keep="last").sort_values("date").reset_index(drop=True)
    out["shrzgm_cum"] = out.groupby(out["date"].str[:4])["shrzgm_inc"].cumsum()
    out = out[["date", "shrzgm_cum", "shrzgm_inc"]]
    return _filter_new(out, since, "date")


# ── 源采集器: 星耀 AmazingData (单点登录, 串行) ─────────────────────────────
_AD = {"logged_in": False}


def _ad_login():
    if _AD["logged_in"]:
        return
    import AmazingData as ad
    ad.login(username=os.environ.get("AD_USERNAME"),
             password=os.environ.get("AD_PASSWORD"),
             host=os.environ.get("AD_HOST", "101.230.159.235"),
             port=int(os.environ.get("AD_PORT", "8600")))
    _AD["logged_in"] = True


def collect_treasury(since):
    """星耀 get_treasury_yield → dict{term: DataFrame['YIELD']}(index=DATE, 倒序) → {date, m3..y30}"""
    _ad_login()
    import AmazingData as ad
    info = ad.InfoData()
    terms = ["m3", "m6", "y1", "y2", "y3", "y5", "y7", "y10", "y30"]
    ty = info.get_treasury_yield(terms, begin_date=20100101,
                                 end_date=int(date.today().strftime("%Y%m%d")),
                                 is_local=False)
    if not isinstance(ty, dict):
        raise TypeError(f"国债返回类型异常: {type(ty).__name__}")
    frames = {}
    for k, d in ty.items():
        s = d["YIELD"].copy()
        s.index = pd.to_datetime(s.index.astype(str), format="%Y%m%d")
        frames[k] = s.rename(k)
    wide = pd.DataFrame(frames).sort_index()          # 索引倒序→正序(坑!)
    wide.index.name = "date"
    wide = wide.reset_index()
    wide["date"] = pd.to_datetime(wide["date"]).dt.strftime("%Y-%m-%d")
    expect = ["date"] + terms
    if list(wide.columns) != expect:
        raise ValueError(f"国债表头异常: {list(wide.columns)}")
    wide = wide.dropna(subset=terms, how="any").reset_index(drop=True)
    return _filter_new(wide, since, "date")


def collect_margin(since):
    """星耀 get_margin_summary → DataFrame[TRADE_DATE,EXCHANGE,SUM_*]
    → (primary{date,exchange,...}, daily{date,margin_balance,margin_purchase} 按日SUM)

    ⚠️ 完整性护栏(2026-09-24 事故沉淀): 源按交易所**异步发布**, 残缺日(缺任一交易所)
    参与 SUM 会显著低估全市场值(09-24 只含 SSE → 低于真实 49%)。故: 只对交易所齐全的
    日期做聚合; 残缺日**跳过聚合**(primary 明细照常保留), 下次增量源补齐后自动纳入。
    """
    _ad_login()
    import AmazingData as ad
    info = ad.InfoData()
    MC = {"TRADE_DATE": "date", "EXCHANGE": "exchange",
          "SUM_BORROW_MONEY_BALANCE": "borrow_balance",
          "SUM_PURCH_WITH_BORROW_MONEY": "purchase_amt",
          "SUM_REPAYMENT_OF_BORROW_MONEY": "repayment_amt",
          "SUM_SEC_LENDING_BALANCE": "sec_lending_balance",
          "SUM_SALES_OF_BORROWED_SEC": "sec_sale_vol",
          "SUM_MARGIN_TRADE_BALANCE": "margin_trade_balance"}
    b = int(since.strftime("%Y%m%d")) if since else 20100331
    end = int(date.today().strftime("%Y%m%d"))
    if b >= end:
        return pd.DataFrame(), pd.DataFrame()
    try:
        ms = info.get_margin_summary(begin_date=b, end_date=end, is_local=False)
    except TypeError:
        return pd.DataFrame(), pd.DataFrame()   # 区间无已发布数据(SDK 内部抛, 预期)
    if ms is None or not hasattr(ms, "columns") or len(ms) == 0:
        return pd.DataFrame(), pd.DataFrame()
    prim = ms.rename(columns=MC)[list(MC.values())].copy()
    prim["date"] = pd.to_datetime(prim["date"].astype(str)).dt.strftime("%Y-%m-%d")
    prim = prim.sort_values(["date", "exchange"]).reset_index(drop=True)
    prim = _filter_new(prim, since, "date")
    if len(prim) == 0:
        return pd.DataFrame(), pd.DataFrame()
    # —— 交易所完整性护栏 ——
    prim, bad = margin_complete_prefix(prim)
    if bad:
        detail = "; ".join(f"{d}(缺{','.join(sorted(m))})" for d, m in bad[:5])
        log(f"   ⚠️ 完整性: 残缺日 {len(bad)} 个 → 截断至 {bad[0][0]} 前, 该日及之后待源补齐 "
            f"| {detail}{' ...' if len(bad) > 5 else ''}")
        if len(prim) == 0:
            log("   ⚠️ 完整性: 本次全部日期均残缺 → 不产出数据(源补齐后自动纳入)")
            return pd.DataFrame(), pd.DataFrame()
    daily = (prim.groupby("date", as_index=False)
             .agg(margin_balance=("margin_trade_balance", "sum"),
                  margin_purchase=("purchase_amt", "sum")))
    return prim, daily.sort_values("date").reset_index(drop=True)


def collect_floatcap(since):
    """星耀 get_industry_daily → dict{code: DataFrame}(index=TRADE_DATE) → 全宽表"""
    _ad_login()
    import AmazingData as ad
    info = ad.InfoData()
    COLS = ["TRADE_DATE", "OPEN", "HIGH", "LOW", "CLOSE", "PRE_CLOSE",
            "VOLUME", "AMOUNT", "PE", "PB", "TOTAL_CAP", "A_FLOAT_CAP"]
    b = int(since.strftime("%Y%m%d")) if since else 20100104
    end = int(date.today().strftime("%Y%m%d"))
    if b >= end:
        return pd.DataFrame()
    d = info.get_industry_daily(code_list=["801003.SI"], begin_date=b,
                                end_date=end, is_local=False)
    if not isinstance(d, dict) or "801003.SI" not in d:
        raise TypeError(f"行业指数返回异常: {type(d).__name__}")
    df = d["801003.SI"].reset_index()
    df["TRADE_DATE"] = pd.to_datetime(df["TRADE_DATE"].astype(str)).dt.strftime("%Y-%m-%d")
    df = df[COLS].drop_duplicates("TRADE_DATE", keep="last")
    df = df.sort_values("TRADE_DATE").reset_index(drop=True)
    # ⚠️ 窗口护栏(2026-09-29 回归事故沉淀): 源对"当日(未收盘/未发布市值)"行,
    # TOTAL_CAP/A_FLOAT_CAP 返回 NaN —— 若纳入会把残缺行当完整写入。
    # 只保留市值齐全的行; 当日缺失 → 下次增量(T+1 源补齐)自动纳入。
    n_before = len(df)
    bad_na = int(df[["TOTAL_CAP", "A_FLOAT_CAP"]].isna().sum().sum())
    if bad_na:
        df = df.dropna(subset=["TOTAL_CAP", "A_FLOAT_CAP"]).reset_index(drop=True)
        # 语义: 报"剔除 N 行"按行数计(2026-09-29 qucoder ②: 原按 NaN 单元格数虚报)
        n_dropped = n_before - len(df)
        log(f"   ⚠️ 窗口护栏: 剔除市值不全行 {n_dropped} 行(NaN 单元格 {bad_na} 个; "
            f"源未发布完整 → 下次增量自动补)")
    return _filter_new(df, since, "TRADE_DATE")


# ── 指标 → 文件/采集器/值列/值域 计划 ───────────────────────────────────────
def build_plan():
    def s(file, engine, gc, rng, date_col="date", dup_key=None):
        return dict(file=file, engine=engine, guard_cols=gc, ranges=rng,
                    date_col=date_col, dup_key=dup_key)
    return {
        "hs300_pe_ttm":   s("macro_hs300_pe_primary.csv", "ak_hs300_pe", ["pe_ttm"],
                            {"pe_ttm": (8.0, 25.0)}),
        "treasury_y1":    s("macro_treasury_ad_primary.csv", "ad_treasury",
                            ["m3", "m6", "y1", "y2", "y3", "y5", "y7", "y10", "y30"],
                            {"y1": (0.0, 10.0)}),
        "treasury_y10":   s("macro_treasury_ad_primary.csv", "ad_treasury",
                            ["m3", "m6", "y1", "y2", "y3", "y5", "y7", "y10", "y30"],
                            {"y10": (0.0, 10.0)}),
        "us10y":          s("macro_us10y_primary.csv", "ak_us10y", ["us10y"],
                            {"us10y": (0.0, 10.0)}),
        "usdcny":         s("macro_usdcny_primary.csv", "ak_usdcny", ["usdcny"],
                            {"usdcny": (6.0, 9.0)}),
        "oil":            s("brent_fred_daily.csv", "fred_oil", ["brent"],
                            {"brent": (5.0, 250.0)}),
        "margin_balance": s("macro_margin_ad_daily.csv", "ad_margin",
                            ["margin_balance", "margin_purchase"],
                            {"margin_balance": (0.0, 5e12), "margin_purchase": (0.0, 1e13)},
                            dup_key=["date", "exchange"]),
        "margin_purchase": s("macro_margin_ad_daily.csv", "ad_margin",
                             ["margin_balance", "margin_purchase"],
                             {"margin_balance": (0.0, 5e12), "margin_purchase": (0.0, 1e13)},
                             dup_key=["date", "exchange"]),
        "float_cap":      s("macro_floatcap_primary.csv", "ad_floatcap", ["A_FLOAT_CAP"],
                            {"A_FLOAT_CAP": (6.0e8, 6.0e9), "TOTAL_CAP": (5.0e8, 1.0e10)},
                            date_col="TRADE_DATE"),
        "pmi":            s("macro_pmi_primary.csv", "ak_pmi", ["pmi"], {"pmi": (30.0, 70.0)}),
        "cpi_yoy":        s("macro_cpi_primary.csv", "ak_cpi", ["cpi_yoy", "cpi_mom", "cpi_ytd"],
                            {"cpi_yoy": (-5.0, 15.0)}),
        "cpi_mom":        s("macro_cpi_primary.csv", "ak_cpi", ["cpi_yoy", "cpi_mom", "cpi_ytd"],
                            {"cpi_mom": (-5.0, 5.0)}),
        "cpi_ytd":        s("macro_cpi_primary.csv", "ak_cpi", ["cpi_yoy", "cpi_mom", "cpi_ytd"],
                            {"cpi_ytd": (-5.0, 15.0)}),
        "ppi_yoy":        s("macro_ppi_primary.csv", "ak_ppi", ["ppi_yoy", "ppi_ytd"],
                            {"ppi_yoy": (-15.0, 30.0)}),
        "ppi_ytd":        s("macro_ppi_primary.csv", "ak_ppi", ["ppi_yoy", "ppi_ytd"],
                            {"ppi_ytd": (-15.0, 30.0)}),
        "m1_yoy":         s("macro_money_supply_primary.csv", "ak_money",
                            ["m2_yoy", "m2_mom", "m1_yoy", "m1_mom"],
                            {"m1_yoy": (-20.0, 50.0)}),
        "m2_yoy":         s("macro_money_supply_primary.csv", "ak_money",
                            ["m2_yoy", "m2_mom", "m1_yoy", "m1_mom"],
                            {"m2_yoy": (-5.0, 40.0)}),
        "shrzgm":         s("macro_shrzgm_primary.csv", "ak_shrzgm",
                            ["shrzgm_cum", "shrzgm_inc"],
                            {"shrzgm_inc": (-10000.0, 100000.0)}),
    }


# ── PG: 起点查询 + UPSERT ───────────────────────────────────────────────────
PG_UPSERT = """
INSERT INTO l1_observation
    (indicator_id, period_date, announcement_date, vintage_date, value, status)
VALUES %s
ON CONFLICT (indicator_id, period_date, vintage_date) DO NOTHING
"""


def pg_max_period(conn, indicator_id):
    with conn.cursor() as cur:
        cur.execute("SELECT max(period_date) FROM l1_observation WHERE indicator_id=%s",
                    (indicator_id,))
        r = cur.fetchone()[0]
    return r      # datetime.date | None


def _parse_period(s):
    """'2026-08' / '2026-08-01' → date (pmi 的 CSV 用 YYYY-MM 无日)"""
    s = str(s)
    if len(s) == 7:
        return date(int(s[:4]), int(s[5:7]), 1)
    return date.fromisoformat(s)


def upsert_pg(conn, indicator_id, df, pit, value_col, period_col="date", dry_run=False):
    """增量 UPSERT 到 l1_observation; announcement_date 复用 pit_init 的映射"""
    ind = {i[0]: i for i in pit.INDICATORS}[indicator_id]
    freq, lag = ind[2], ind[5]
    vintage = date.today().isoformat()
    rows = []
    for _, r in df.iterrows():
        p = _parse_period(r[period_col])
        rows.append((indicator_id, p, pit._announcement_date(freq, lag, p),
                     vintage, float(r[value_col]), "initial"))
    if dry_run or not rows:
        return 0, len(rows)
    from psycopg2.extras import execute_values
    with conn.cursor() as cur:
        execute_values(cur, PG_UPSERT, rows, page_size=1000)
        inserted = cur.rowcount          # 实际插入数(ON CONFLICT 命中的不计)
    conn.commit()
    return inserted, len(rows)


# ── 主流程 ─────────────────────────────────────────────────────────────────
def run_collector(engine, since):
    return {
        "ak_usdcny": collect_usdcny, "ak_us10y": collect_us10y,
        "ak_hs300_pe": collect_hs300_pe, "fred_oil": collect_oil,
        "ak_pmi": collect_pmi, "ak_cpi": collect_cpi, "ak_ppi": collect_ppi,
        "ak_money": collect_money_supply, "ak_shrzgm": collect_shrzgm,
        "ad_treasury": collect_treasury, "ad_floatcap": collect_floatcap,
        "ad_margin": collect_margin,
    }[engine](since)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--daily", action="store_true")
    ap.add_argument("--monthly", action="store_true")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--only", default="")
    ap.add_argument("--state-from", choices=["local", "pg"], default="local",
                    help="local=从本地 L0 CSV 取增量起点(并维护 CSV); pg=从 NAS PG 取起点(只写 PG)")
    ap.add_argument("--raw-dir", default=str(SCRIPT_DIR.parent / "data" / "raw_data"))
    ap.add_argument("--pit-init", default="", help="pit_init.py 路径(默认同目录查找)")
    ap.add_argument("--pg-dsn", default=os.environ.get("L1_PG_DSN", PG_DEFAULT))
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    ids = [x.strip() for x in a.only.split(",") if x.strip()] if a.only else []
    if not ids:
        if a.all or a.daily:
            ids += DAILY
        if a.all or a.monthly:
            ids += MONTHLY
    if not ids:
        ap.error("需指定 --daily / --monthly / --all / --only")

    raw = Path(a.raw_dir)
    plan = build_plan()
    pit = load_pit_init(a.raw_dir, a.pit_init or None)
    ind_meta = {i[0]: i for i in pit.INDICATORS}
    write_csv = (a.state_from == "local")

    log(f"目标 {len(ids)} 指标 | 模式={a.state_from} | L0={raw if write_csv else '(不写)'} | dry_run={a.dry_run}")

    conn = None
    if not a.dry_run or a.state_from == "pg":
        import psycopg2
        conn = psycopg2.connect(a.pg_dsn)

    # 按文件分组(共享文件只采集一次)
    by_file = {}
    for i in ids:
        by_file.setdefault(plan[i]["file"], []).append(i)

    results, failed = {}, {}
    for fname, group in by_file.items():
        fpath = raw / fname
        engine = plan[group[0]]["engine"]
        dcol = plan[group[0]].get("date_col", "date")
        try:
            # —— 增量起点 ——
            if a.state_from == "pg":
                since = pg_max_period(conn, group[0])
                old = None
            else:
                old = read_csv(fpath) if fpath.exists() else pd.DataFrame()
                since = None
                if len(old) and dcol in old.columns:
                    since = _parse_period(existing_max_date(old, dcol))
            log(f"── {fname} [{engine}] 起点={since or '全量'}")

            # —— 采集 ——
            if engine == "ad_margin":
                new, new_daily = collect_margin(since)
            else:
                new, new_daily = run_collector(engine, since), None

            if new is None or len(new) == 0:
                log("   → 无新数据(源已最新)")
                results[fname] = 0
                continue

            # —— 护栏 ——
            gcols = [c for c in plan[group[0]]["guard_cols"] if c in new.columns]
            ranges = plan[group[0]]["ranges"]
            guard(new, fname, gcols, ranges, dcol, dup_key=plan[group[0]].get("dup_key"))
            if engine == "ad_margin" and new_daily is not None and len(new_daily):
                guard(new_daily, fname + "(daily聚合层)", ["margin_balance", "margin_purchase"],
                      ranges, "date")

            # —— 写 CSV (仅 local 模式) ——
            if write_csv and not a.dry_run:
                if engine == "ad_margin":
                    oldp = read_csv(raw / "macro_margin_ad_primary.csv")
                    mp, _ = merge_append(oldp, new, ["date", "exchange"])
                    atomic_write_csv(mp, raw / "macro_margin_ad_primary.csv")
                    if new_daily is not None and len(new_daily):
                        md, _ = merge_append(old, new_daily, ["date"])
                        atomic_write_csv(md, fpath)
                    log(f"   → 明细 +{len(new)} 行; 聚合层 {len(new_daily) if new_daily is not None else 0} 行"
                        f"(残缺日不聚合, 源补齐后自动纳入)")
                else:
                    merged, _ = merge_append(old, new, [dcol], dcol)
                    guard(merged, fname + "(merged)", gcols, plan[group[0]]["ranges"], dcol)
                    atomic_write_csv(merged, fpath)
                log(f"   → CSV +{len(new)} 行  {new[dcol].iloc[0]}~{new[dcol].iloc[-1]}")

            # —— 落 NAS PG ——
            for i in group:
                vc = ind_meta[i][7]
                if vc is None:      # 单数据列文件(未登记 value_col) → 取唯一非日期列
                    cand = [c for c in new.columns if c != dcol]
                    vc = cand[0] if len(cand) == 1 else None
                src = new_daily if engine == "ad_margin" else new
                if src is None or len(src) == 0:
                    log(f"   {i}: 跳过 PG(本次无齐全日聚合, 源补齐后自动纳入)")
                    continue
                if vc is None or vc not in src.columns:
                    log(f"   {i}: 跳过 PG(value_col={vc} 不可用)")
                    continue
                n, tot = upsert_pg(conn, i, src, pit, vc, dcol, a.dry_run)
                log(f"   {i}: PG 插入 {n}/{tot} 行")
            results[fname] = len(new)

        except Exception as e:
            failed[fname] = f"{type(e).__name__}: {e}"
            log(f"   !! FAILED: {failed[fname]}")
            traceback.print_exc(limit=2)

    if conn:
        conn.close()

    log("=" * 60)
    log(f"完成: 成功 {len(results)} 文件 / 失败 {len(failed)}")
    for f, e in failed.items():
        log(f"  ✗ {f}: {e}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
