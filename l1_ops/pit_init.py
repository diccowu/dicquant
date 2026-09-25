#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pit_init.py — PIT 数据层初始化(2026-09-25 重建 v2.0)

职责:
  1. 建三张表: indicator_meta(指标字典) / observation(观测主表) / methodology_version(口径断点)
  2. 从 data/raw_data/*.csv 迁移原始数据 → observation,计算 announcement_date
  3. 生成全量快照 snapshots/<date>.parquet

设计原则(来源: wiki/量化开发/数据源/PIT数据层.md + 框架.md 铁律):
  - 三时间轴: period_date(数据所属期) / announcement_date(发布日,PIT 可得性过滤) / vintage_date(入库日)
  - 发布日近似: 日频=当日; 月频/季频 = period 期末 + release_lag 天
    * lag=0 表示"期末当天发布"(PMI 月末口径,统计局常规月当月最后一日 9:30 发布)
  - 只存原始水平值,同比/环比/派生量(如 m1m2 剪刀差)下沉因子层,不在此派生
  - 快照 = 原子写入(临时文件 + os.replace),失败不留半成品
  - 幂等: 同 period 重复插入按 vintage 链追加(initial/revised),不覆盖

v2.0 重建说明(2026-09-25, 双重复检 qucoder+infomana 前交付物):
  - 依据 16 项源数据逐项定稿成果(12 项终检定稿 + qfii_mv 不建降观察池):
    1) 删除 hs300_close(已判出局,源文件不存在) 与 qfii_mv(不建)
    2) 新增 float_cap(第17项定稿: macro_floatcap_primary.csv, 流通市值,两融占比分母)
    3) hs300_pe_ttm 注册口径更新: 起点 2011-06/连续段2012-03 → 截断起点 2012-09-04;
       值域 (5.0,80.0) → (8.0,25.0)(实测 8.55~20.38); 补 lag 语义: PE(T) 于 T+1 可得,
       消费端恒 T+1 起 usable
    4) oil 源替换: oil_sc_main_daily.csv(SC主力,已废弃) → brent_fred_daily.csv(FRED
       DCOILBRENTEU,第19项定稿); value_col=brent, 值域 (5.0,250.0)
    5) usdcny 值域 (5.0,10.0) → (6.0,9.0)(台账登记口径, 实测 6.093~8.71)
    6) REQUIRED 扩至 18 项 = 全部已定稿指标(含复核参照序列)
    7) DATE_COL 别名: 支持非 date/period_date 命名(如 float_cap 的 TRADE_DATE)
    8) METHODOLOGY_VERSIONS 新增 float_cap 两段(2011-01-04 疑口径切换)

用法:
  python pit_init.py                      # 建库 + 迁移全部可用指标 + 快照
  python pit_init.py --db=xxx.duckdb      # 指定库文件(测试用)
  python pit_init.py --raw=DIR            # 指定原始数据目录
  python pit_init.py --snapshots=DIR      # 指定快照目录
  python pit_init.py --check              # 只检查数据文件可用性,不建库
"""
import argparse
import calendar as _cal
import os
import sys
import tempfile
from datetime import date, timedelta

import duckdb
import pandas as pd

RAW_DEFAULT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "raw_data")
DB_DEFAULT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "pit", "pit.db")
SNAP_DEFAULT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "pit", "snapshots")

# 已逐项终检确认的原始数据指标集合。
# 扩展现有指标: 每通过一项用户终检,就往这个集合加一个 indicator_id,
# 之后该指标文件缺失 / 发布日口径不符都会使自检 FAIL(不允许静默丢项)。
# 当前已确认(v2.0 2026-09-25, 18 项 = 全部已定稿指标, 含复核参照序列):
#   pmi/cpi_yoy/cpi_mom/cpi_ytd/ppi_yoy/ppi_ytd/m2_yoy/m1_yoy/shrzgm(1~9, 已定稿)
#   hs300_pe_ttm(第18项)/float_cap(第17项)/usdcny(第14项)/treasury_y1/treasury_y10/us10y
#   oil(第19项)/margin_balance/margin_purchase
REQUIRED = {"pmi", "cpi_yoy", "cpi_mom", "cpi_ytd", "ppi_yoy", "ppi_ytd",
            "m2_yoy", "m1_yoy", "shrzgm", "hs300_pe_ttm",
            "treasury_y1", "treasury_y10", "us10y", "usdcny",
            "oil", "margin_balance", "margin_purchase", "float_cap"}

# 日期列别名: 源 CSV 日期列名 → 标准列名(date/period_date)。
# 说明: 大部分源文件用 'date';float_cap 源为宽表, 日期列名是 TRADE_DATE。
DATE_COL_ALIAS = {"TRADE_DATE": "date"}

# ---------------------------------------------------------------------------
# 指标字典
# 字段: id, raw_file, freq, sa_flag, methodology, release_lag, source, value_col, value_range
#   freq: D=日频 M=月频 Q=季频
#   release_lag: 发布日距 period 期末的天数(0=期末当天, 见 _announcement_date)
#   value_col: 从 raw_file 取哪列作指标值; None=取文件唯一值列(单列文件)
#   value_range: (min,max) 值域断言,防 value_col 取错列; None=不检查
# ---------------------------------------------------------------------------
INDICATORS = [
    # —— 统计局(nbs)——  (CPI 三值列官方口径: 同比 因子层 + 环比/累计 复核参照)
    ("pmi",        "macro_pmi_primary.csv",        "M", 1, "制造业PMI,2026-09-19重建:起点2008-01(224月),源=akshare macro_china_pmi(东财,统计月口径);方案A:announcement=月末口径(lag=0)", 0, "eastmoney", None, (30.0, 70.0)),
    ("cpi_yoy",    "macro_cpi_primary.csv",        "M", 0, "CPI同比涨跌幅(%),官方公布原样值(月度新闻稿'居民消费价格'行);2026-09-20重建:4列{date,cpi_yoy,cpi_mom,cpi_ytd},0.1精度;官方xlsx核对一致(2026-08:同比0.8/环比0.4/累计0.9);拉取=akshare macro_china_cpi(东财转载统计局公布值);发布日非固定次月9日(2026日程表5/12月晚于9日,最坏次月14日)→lag=14", 14, "nbs", "cpi_yoy", (-5.0, 15.0)),
    ("cpi_mom",    "macro_cpi_primary.csv",        "M", 0, "CPI环比涨跌幅(%),官方公布原样值(新闻稿'居民消费价格'行);复核参照(role=reference);发布日同cpi_yoy:lag=14;值域(-5,5):历史max=2.6(2008-02),原(-3,3)上界余量仅0.4过紧", 14, "nbs", "cpi_mom", (-5.0, 5.0)),
    ("cpi_ytd",    "macro_cpi_primary.csv",        "M", 0, "CPI 1-N月累计同比涨跌幅(%),官方公布原样值(新闻稿'居民消费价格'行);复核参照(role=reference),供断点/跨源比较;发布日同cpi_yoy:lag=14;⚠️年度重置序列:每年1月=单月(非全年累计)、12月=全年,跨年不连续,禁止差分/趋势/跨年同比", 14, "nbs", "cpi_ytd", (-5.0, 15.0)),
    ("ppi_yoy",    "macro_ppi_primary.csv",        "M", 0, "PPI同比涨跌幅(%),官方公布原样值;2026-09-20重建:3列{date,ppi_yoy,ppi_ytd}(1日期列+2数据列),单源=akshare macro_china_ppi(东财转载统计局公布值),0.1精度;官方xlsx核对一致(2026-08:同比3.8/2026-07:3.5/2026-06:4.1/2026-03:0.5/2024-09:-2.8/2008-08:10.1/2009-07:-8.2/2017-02:7.8/2021-10:13.5;2009-01 yoy 东财源单点污染-3.4,经统计局2009-02-10新闻稿核定为-3.3(TASK_005 2026-09-20修复);akshare接口无环比列,原始层不含环比(环比仅存于统计局官网xlsx);发布日与CPI同(次月上旬,最坏次月14日)→lag=14", 14, "nbs", "ppi_yoy", (-15.0, 30.0)),
    ("ppi_ytd",    "macro_ppi_primary.csv",        "M", 0, "PPI 1-N月累计平均同比涨跌幅(%),官方公布原样值(源列'累计'=100+累计平均同比 → -100 还原);复核参照(role=reference),供断点/跨源比较;发布日同ppi_yoy:lag=14;⚠️年度重置序列:每年1月=单月(非全年累计)、12月=全年,跨年不连续,禁止差分/趋势/跨年同比", 14, "nbs", "ppi_ytd", (-15.0, 30.0)),
    # —— 央行(pbc)——  (共享文件: 多列源,按列拆分 value_col)
    ("m2_yoy",     "macro_money_supply_primary.csv", "M", 0, "M2同比增速(%),官方公布原样值(央行货币供应量统计);2026-09-20重建:5列{date,m2_yoy,m2_mom,m1_yoy,m1_mom},起点2008-01(224月),0.1精度;拉取=akshare macro_china_money_supply(东财转载央行公布值),官方锚点三处核对一致(2026-08:7.5/2026-05:8.6/2025-03:7.0);M2无2024口径断点,同比原样保留(注:源余额列历史多段被后续口径调整回溯,与当时公布同比在2009/2011-2012/2014-2015/2017段存差异,属源机制非错误,详见台账);发布日实测(2025-03→04-13 / 2026-05→06-12 / 2026-07→08-17 / 2026-08→09-15),最坏17天→lag=17", 17, "pbc", "m2_yoy", (-5.0, 40.0)),
    ("m1_yoy",     "macro_money_supply_primary.csv", "M", 0, "M1同比增速(%),官方公布原样值(央行货币供应量统计);2026-09-20重建:2024全12期同比采用央行注5「按可比口径回溯」值(源余额列已回溯 12/12 吻合官方、同比列仍为发布当日旧口径值 12/12 不符,偏差+2.6~-4.3pp);2024-01起新口径(M0+单位活期+个人活期+支付机构备付金),断点见methodology_version;2024-01环比因跨口径置空;发布日同m2_yoy→lag=17", 17, "pbc", "m1_yoy", (-20.0, 50.0)),
    ("shrzgm",     "macro_shrzgm_primary.csv",     "M", 0, "社融增量(亿元);2026-09-20重建:3列{date,shrzgm_cum,shrzgm_inc}(cum官方当年累计/年度重置,禁跨年差分同比;inc单月差分=value_col);源=akshare macro_china_shrzgm(2015-01~2026-04)+央行金融统计数据报告前N月累计差分补2026-05~08(akshare停更;官方前1~前4累计=15.45万亿与akshare累计100%吻合无断点,前5~前8=17.48/20.84/22.25/23.91万亿差分闭环84593亿;2026全年v3口径未调整);2017-01起为央行可比口径回溯值;因子起点:单月同比2018-02,TTM同比2019-01(2017年同比为新/旧掺混已弃用);口径段见methodology_version;发布日最坏2026-07→08-17(17天)同M1/M2→lag=17", 17, "pbc", "shrzgm_inc", (-10000.0, 100000.0)),
    # —— 市场行情/估值(日频,当日可得)——  (2026-09-25: hs300_close 已判出局删除)
    ("hs300_pe_ttm",  "macro_hs300_pe_primary.csv",   "D", 0, "中证指数官方HS300 PE_TTM;2026-09-22定稿:截断起点 2012-09-04(前段2011-06~2012-09为源空值区非缺口,数据连续段自2012-09-04起零空值);值域实测 8.55~20.38;可得时点=T日盘后/T+1盘前,PE(T)于T+1可得,消费端恒T+1起usable(前视审查同两融)→lag=0自洽", 0, "csindex", None, (8.0, 25.0)),
    ("treasury_y1",   "macro_treasury_ad_primary.csv", "D", 0, "1Y国债到期收益率(%),中债,AmazingData get_treasury_yield;9期限宽表{m3,m6,y1,y2,y3,y5,y7,y10,y30}按列拆分;可得时点=T日盘后/T+1盘前,消费端恒T+1起usable(前视审查同两融2026-09-21)→lag=0自洽", 0, "ad", "y1", (0.0, 10.0)),
    ("treasury_y10",  "macro_treasury_ad_primary.csv", "D", 0, "10Y国债到期收益率(%),中债,AmazingData get_treasury_yield;9期限宽表按列拆分;中美利差=treasury_y10-us10y在因子层合成;可得时点=T日盘后/T+1盘前,消费端恒T+1起usable(前视审查同两融2026-09-21)→lag=0自洽", 0, "ad", "y10", (0.0, 10.0)),
    ("us10y",         "macro_us10y_primary.csv",       "D", 0, "美国10Y国债收益率(%),源=akshare bond_zh_us_rate(东财,2026-09重建4184行,FRED补3缺口日);中美利差=treasury_y10-us10y在因子层合成;可得时点=T日盘后/T+1盘前,消费端恒T+1起usable(前视审查同两融2026-09-21)", 0, "akshare", "us10y", (0.0, 10.0)),
    ("usdcny",        "macro_usdcny_primary.csv",      "D", 0, "美元兑人民币汇率(元/美元);单位统一为元(历史分计×100已于2026-09-18修正);2026-09-22定稿:值域(6.0,9.0)台账登记,实测6.093~8.71", 0, "exch", None, (6.0, 9.0)),
    ("oil",           "brent_fred_daily.csv",          "D", 0, "布伦特原油日收盘价(美元/桶);2026-09-24定稿:源=FRED DCOILBRENTEU(EIA官方,1987-05-20~今);实测 9.1~143.9;机构口径:月度均值同比作PPI先行列(领先1~2期),月频派生(交易日均值+同比)在因子层,不入库", 0, "fred", "brent", (5.0, 250.0)),
    # —— 两融(AmazingData,日频)——  (共享文件: 多列, value_col 按列拆分 margin_balance/margin_purchase)
    ("margin_balance",  "macro_margin_ad_daily.csv",  "D", 0, "两融余额(融资融券余额三所SUM,元);2026-09-21重建:2列日序{margin_balance,margin_purchase}(派生聚合层daily,源=AmazingData get_margin_summary三所逐日→按日SUM);口径段:2010-03-31~2023-02-10两所(SSE+SZSE)/2023-02-13起含NEEQ(北交融资融券开通,占比<0.3%);2026-08-17 SZSE源缺由东财(akshare)一致源回补(前/后一周相对差0.00%,恒等式SUM(融资余额+融券余额)=margin_balance全表0差);日频可得时点=T日盘后/T+1盘前,消费端恒T+1起usable(前视审查2026-09-21 TASK_007)→lag=0自洽", 0, "ad", "margin_balance", (0.0, 5e12)),
    ("margin_purchase", "macro_margin_ad_daily.csv",  "D", 0, "融资买入额(三所SUM,元);2026-09-21重建:派生聚合层daily[macro_margin_ad_daily.csv],源=AmazingData get_margin_summary;口径段与回补同margin_balance;日频可得时点=T日盘后/T+1盘前,消费端恒T+1起usable(前视审查2026-09-21 TASK_007)→lag=0自洽", 0, "ad", "margin_purchase", (0.0, 1e13)),
    # —— 流通市值(AmazingData,日频, 第17项定稿 2026-09-22)——
    ("float_cap",     "macro_floatcap_primary.csv",    "D", 0, "A股流通市值(万元);2026-09-22定稿:源=AmazingData 申万A指 801003.SI 日频宽表{TRADE_DATE,...,TOTAL_CAP,A_FLOAT_CAP},value_col=A_FLOAT_CAP;两融占比因子分母;⚠️2011-01-04 疑似口径切换(占比72.33%→33.05%,流通市值当日−54.01%),下游跨2010/2011须显式处理,见methodology_version;实测值域6.36万亿~52.62万亿元(=6.36e8~5.26e9万元)", 0, "ad", "A_FLOAT_CAP", (6.0e8, 6.0e9)),
]

# 口径断点登记(社融 v1a~v3,出处见 PIT数据层.md 第五节,2026-09-17 用户核验全 verified)
METHODOLOGY_VERSIONS = [
    # (indicator_id, version, valid_from, valid_to, change_desc, verified)
    ("shrzgm", "v1a", "2015-01-01", "2016-12-31",
     "原始口径:人民币贷款、外币贷款、委托贷款、信托贷款、未贴现银行承兑汇票、企业债券、非金融企业境内股票融资;央行未回溯至本段;水平值与2017-01后不可比,2017年同比为新/旧掺混已弃用", 1),
    ("shrzgm", "v1b", "2017-01-01", "2018-06-30",
     "央行可比口径回溯值(经2018-07与2019-12两次调整回溯叠加,起点均为2017-01)", 1),
    ("shrzgm", "v2a", "2018-07-01", "2018-08-31",
     "纳「存款类金融机构ABS」+「贷款核销」", 1),
    ("shrzgm", "v2b", "2018-09-01", "2019-08-31",
     "纳「地方政府专项债券」(2018-09 而非笼统7月)", 1),
    ("shrzgm", "v2c", "2019-09-01", "2019-11-30",
     "企业债券纳「交易所企业资产支持证券」", 1),
    ("shrzgm", "v3",  "2019-12-01", None,
     "纳「国债」+「地方一般债」,合并「政府债券」;唯一真不可比断点:v1a→v1b(2016-12→2017-01)", 1),
    ("m1_yoy", "v1", "2015-01-01", "2023-12-31",
     "旧口径(M1=流通中货币+单位活期存款,不含居民活期)", 1),
    ("m1_yoy", "v2", "2024-01-01", None,
     "新口径(2024-12公告调整,回溯至2024-01:纳居民活期存款)", 1),
    # 两融口径段(2026-09-21 TASK_007:两所→三所属同性质分项扩展,实体登记;数值连续非跳变)
    ("margin_balance", "v1", "2010-03-31", "2023-02-10",
     "两所口径(SSE+SZSE);NEEQ北交所融资融券2023-02-13开通前无该所数据", 1),
    ("margin_balance", "v2", "2023-02-13", None,
     "三所口径(+NEEQ);数值连续非可比性跳变(NEEQ首日融资余额365万元,占比趋近0),仅覆盖范围如实扩展", 1),
    ("margin_purchase", "v1", "2010-03-31", "2023-02-10",
     "两所口径(SSE+SZSE);NEEQ北交所融资融券2023-02-13开通前无该所数据", 1),
    ("margin_purchase", "v2", "2023-02-13", None,
     "三所口径(+NEEQ);数值连续非可比性跳变(NEEQ首日融资余额365万元,占比趋近0),仅覆盖范围如实扩展", 1),
    # float_cap 口径段(第17项定稿 2026-09-22: 2011-01-04 疑似口径切换, 实体登记供下游显式处理)
    ("float_cap", "v1", "2010-01-04", "2010-12-31",
     "总流通市值口径(A_FLOAT_CAP/TOTAL_CAP 占比 72.33%)", 1),
    ("float_cap", "v2", "2011-01-04", None,
     "疑「自由流通市值」口径切换:占比骤降至 33.05%,流通市值当日 −54.01%(18.92万亿→8.70万亿);下游跨 2010/2011 算占比须显式处理", 1),
]

DDL_INDICATOR_META = """
CREATE TABLE IF NOT EXISTS indicator_meta (
    indicator_id     VARCHAR PRIMARY KEY,
    raw_file         VARCHAR NOT NULL,
    freq             VARCHAR NOT NULL CHECK (freq IN ('D','M','Q')),
    sa_flag          INTEGER NOT NULL DEFAULT 0,
    methodology      VARCHAR,
    release_lag_days INTEGER NOT NULL DEFAULT 0,
    source           VARCHAR,
    description      VARCHAR
)
"""

DDL_OBSERVATION = """
CREATE TABLE IF NOT EXISTS observation (
    indicator_id      VARCHAR NOT NULL,
    period_date       DATE    NOT NULL,
    announcement_date DATE    NOT NULL,
    vintage_date      DATE    NOT NULL,
    value             DOUBLE  NOT NULL,
    status            VARCHAR NOT NULL DEFAULT 'initial'
                    CHECK (status IN ('initial','revised','final')),
    PRIMARY KEY (indicator_id, period_date, vintage_date)
)
"""

DDL_METHODOLOGY_VERSION = """
CREATE TABLE IF NOT EXISTS methodology_version (
    indicator_id VARCHAR NOT NULL,
    version      VARCHAR NOT NULL,
    valid_from   DATE,
    valid_to     DATE,
    change_desc  VARCHAR,
    verified     INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (indicator_id, version)
)
"""


def _announcement_date(freq: str, lag: int, period: date) -> date:
    """发布日近似: 日频=当日; 月/季频 = period 期末 + lag 天。

    关键口径(lag=0): 表示"期末当天发布",最典型是 PMI——
    统计局常规月当月最后一日 9:30 发布(官方发布日程表证据)。
    严禁把 lag=0 解释为次月1日: 2026-02 真实发布 3/4,次月1日=前视3天(已证伪)。
    """
    if freq == "D":
        return period
    period_end = period.replace(day=_cal.monthrange(period.year, period.month)[1])
    if freq == "Q":
        # 季末: 3/6/9/12 月最后一日
        q_end_month = {1: 3, 2: 6, 3: 9, 4: 12}[((period.month - 1) // 3) + 1]
        period_end = period.replace(month=q_end_month,
                                    day=_cal.monthrange(period.year, q_end_month)[1])
    if lag == 0:
        return period_end
    return period_end + timedelta(days=lag)


def _read_raw_csv(path: str) -> pd.DataFrame:
    """读原始 CSV,统一为 date(period) / value 两列。缺失列报错而不是静默丢弃。

    v2.0: 支持日期列别名(DATE_COL_ALIAS), 如 float_cap 的 TRADE_DATE → date。
    """
    if not os.path.exists(path):
        raise FileNotFoundError(f"原始数据文件缺失: {path}")
    df = pd.read_csv(path)
    for alias, std in DATE_COL_ALIAS.items():
        if alias in df.columns:
            df = df.rename(columns={alias: std})
    date_col = "date" if "date" in df.columns else "period_date"
    if date_col not in df.columns:
        raise ValueError(f"{path} 缺少日期列(date/period_date),实际列: {list(df.columns)}")
    value_cols = [c for c in df.columns if c not in (date_col, "period_date")]
    if not value_cols:
        raise ValueError(f"{path} 缺少值列")
    df = df.rename(columns={date_col: "period_date"})
    df["period_date"] = pd.to_datetime(df["period_date"]).dt.date
    return df[["period_date"] + value_cols]


def _migrate_indicator(con: duckdb.DuckDBPyConnection, ind: tuple,
                       raw_dir: str, vintage: date) -> int:
    """迁移单指标 CSV → observation,返回插入行数。支持多列源按 value_col 拆分。"""
    iid, raw_file, freq, _sa, _meth, lag, _src, value_col = ind[:8]
    path = os.path.join(raw_dir, raw_file)
    try:
        df = _read_raw_csv(path)
    except FileNotFoundError:
        return 0  # 数据文件未就绪(重建中),跳过,等齐后重跑补齐

    # 取值列: value_col 显式指定(多列源按列拆分); None=取文件唯一值列
    if value_col is not None:
        if value_col not in df.columns:
            raise ValueError(f"{raw_file} 缺列 {value_col!r},实际列: {list(df.columns)}")
        value = df[value_col]
        df = df[["period_date"]].copy()
        df["value"] = value
    else:
        if len(df.columns) > 2:
            raise ValueError(
                f"{raw_file} 多值列({list(df.columns[1:])}),INDICATORS 需指定 value_col 按列拆分")
        df = df.rename(columns={df.columns[1]: "value"})

    df["indicator_id"] = iid
    df["freq"] = freq
    df["lag"] = lag
    df = df.dropna(subset=["value"])
    df["value"] = df["value"].astype(float)
    df["announcement_date"] = df.apply(
        lambda r: _announcement_date(r["freq"], int(r["lag"]), r["period_date"]), axis=1)
    df["vintage_date"] = vintage
    df["status"] = "initial"
    df = df[["indicator_id", "period_date", "announcement_date", "vintage_date", "value", "status"]]

    con.execute("DELETE FROM observation WHERE indicator_id = ? AND vintage_date = ?",
                [iid, vintage])  # 同日重复初始化幂等: 先清当日批次再插
    con.register("_mig", df)
    con.execute("INSERT INTO observation SELECT indicator_id, period_date, announcement_date, "
                "vintage_date, value, status FROM _mig")
    con.unregister("_mig")
    return len(df)


def _fill_indicator_meta(con: duckdb.DuckDBPyConnection) -> None:
    for ind in INDICATORS:
        iid, raw_file, freq, sa, meth, lag, src, _vcol, _vrange = ind
        con.execute(
            "INSERT OR REPLACE INTO indicator_meta "
            "(indicator_id, raw_file, freq, sa_flag, methodology, release_lag_days, source, description) "
            "VALUES (?,?,?,?,?,?,?,?)", [iid, raw_file, freq, sa, meth, lag, src, meth])


def _fill_methodology_versions(con: duckdb.DuckDBPyConnection) -> None:
    for row in METHODOLOGY_VERSIONS:
        con.execute(
            "INSERT OR REPLACE INTO methodology_version "
            "(indicator_id, version, valid_from, valid_to, change_desc, verified) "
            "VALUES (?,?,?,?,?,?)", list(row))


def _rebuild_snapshot(con: duckdb.DuckDBPyConnection, snap_dir: str, vintage: date) -> str:
    """全量快照: 临时文件 + os.replace 原子替换,失败不留半成品。"""
    os.makedirs(snap_dir, exist_ok=True)
    final = os.path.join(snap_dir, f"{vintage.isoformat()}.parquet")
    fd, tmp = tempfile.mkstemp(suffix=".parquet", dir=snap_dir)
    os.close(fd)
    try:
        con.execute("COPY (SELECT * FROM observation) TO ? (FORMAT PARQUET)", [tmp])
        os.replace(tmp, final)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise
    return final


def _verify_migration(con: duckdb.DuckDBPyConnection, raw_dir: str) -> list:
    """反假通过自检: 行数核对(防 0 行迁移还报 ✅)。

    规则:
      - 原始数据目录 0 个文件 → FAIL(路径错/被清空)
      - REQUIRED 中任一已确认项文件缺失 → FAIL(已确认项不允许丢)
      - raw 文件存在但 observation 0 行 → FAIL(文件在却没迁进任何行)
      - observation 行数 < 源 CSV 数据行数 → FAIL(漏迁移/被截断)
    返回问题列表,空 = 全过。
    """
    problems = []
    present = [f for _i, f, *_ in INDICATORS
               if os.path.exists(os.path.join(raw_dir, f))]
    if not present:
        problems.append(f"原始数据目录 0/{len(INDICATORS)} 个文件存在,检查 --raw={raw_dir}")
        return problems

    for iid, raw_file, *_ in INDICATORS:
        if iid in REQUIRED and not os.path.exists(os.path.join(raw_dir, raw_file)):
            problems.append(f"{iid} 文件 {raw_file} 缺失(已确认项不允许丢)")

    for iid, raw_file, *_ in INDICATORS:
        path = os.path.join(raw_dir, raw_file)
        if not os.path.exists(path):
            continue
        try:
            src = _read_raw_csv(path)
        except Exception as e:  # noqa: BLE001 源损坏也要抓
            problems.append(f"{iid}: 读源 {raw_file} 失败: {e}")
            continue
        if len(src.columns) < 2:
            problems.append(f"{iid}: {raw_file} 无值列")
            continue
        # 行数核对: 按该指标 value_col 列的有效行数(多列源各列独立核对)
        ind = next(x for x in INDICATORS if x[0] == iid)
        vcol = ind[7] if len(ind) > 7 else None
        if vcol is not None:
            if vcol not in src.columns:
                problems.append(f"{iid}: {raw_file} 缺 value_col 列 {vcol!r}(实际 {list(src.columns)})")
                continue
            src_rows = int(src[vcol].notna().sum())
        else:
            if len(src.columns) > 2:
                problems.append(f"{iid}: {raw_file} 多值列({list(src.columns[1:])})但 INDICATORS 未指定 value_col")
                continue
            src_rows = int(src[src.columns[1]].notna().sum())
        db_rows = con.execute(
            "SELECT count(*) FROM observation WHERE indicator_id = ?", [iid]
        ).fetchone()[0]
        if db_rows == 0:
            problems.append(f"{iid}: 文件 {raw_file} 存在但迁入 0 行")
        elif db_rows < src_rows:
            problems.append(f"{iid}: 迁入 {db_rows} 行 < 源数据 {src_rows} 行(漏迁移?)")
        # 值域断言(发现B 2026-09-20): 行数核对验不了 value_col 取没取错列,
        # 取错列时值域必越界(如 cpi_yoy 误填 value_col=cpi_mom → 7.1→0.4)。
        # 对每个已迁入指标查 min/max, 越界即 FAIL。
        vrange = ind[8] if len(ind) > 8 else None
        if vrange is not None and db_rows > 0:
            lo, hi = vrange
            r = con.execute(
                "SELECT min(value), max(value) FROM observation WHERE indicator_id = ?", [iid]
            ).fetchone()
            vmin, vmax = float(r[0]), float(r[1])
            if vmin < lo or vmax > hi:
                problems.append(
                    f"{iid}: 值域越界 [{vmin:.4g}, {vmax:.4g}] ∉ [{lo}, {hi}] "
                    f"(value_col={vcol!r} 疑似取错列)"
                )
    # 同列断言(发现B-2 2026-09-20 用户审计): 值域重叠的同文件列取错, 值域断言抓不到。
    # 例: cpi_ytd 误取 cpi_yoy — 两者值域都是 (-5,15) → 放行, 但库内 cpi_ytd 变成 yoy 序列。
    # 取同一列 → 两条序列逐值必等, 此处 100% 抓死。注意"1月 ytd==yoy"恒等救不了(取错列时反而恒成立)。
    by_file: dict = {}
    for iid, raw_file, *_ in INDICATORS:
        by_file.setdefault(raw_file, []).append(iid)
    for raw_file, iids in by_file.items():
        if len(iids) < 2:
            continue
        seqs: dict = {}
        for iid in iids:
            rows = con.execute(
                "SELECT value FROM observation WHERE indicator_id = ? ORDER BY period_date", [iid]
            ).fetchall()
            if rows:
                seqs[iid] = [float(r[0]) for r in rows]
        keys = list(seqs)
        for a in range(len(keys)):
            for b in range(a + 1, len(keys)):
                ia, ib = keys[a], keys[b]
                sa, sb = seqs[ia], seqs[ib]
                if len(sa) == len(sb) and all(abs(x - y) < 1e-12 for x, y in zip(sa, sb)):
                    problems.append(
                        f"{ia}/{ib}: 同文件 {raw_file} 值序列逐值相同 → value_col 取了同一列"
                    )
    # 年度重置恒等断言(TASK_005 P3.2 2026-09-20): 对 *_ytd 与同前缀 *_yoy,
    # 每年 1 月两者必须精确相等(1-N月累计平均, 1月=单月)。
    # 值域/同列断言对 0.1 级单点错误免疫(例 2009-01 ppi_yoy=-3.4: 在值域内、
    # 同列断言不触发、软界 ±0.15 恰好放行), 此断言是唯一低成本自动拦截线。
    iid_set = {iid for iid, *_ in INDICATORS}
    for iid, _raw_file, *_ in INDICATORS:
        if not iid.endswith("_ytd"):
            continue
        yoy_id = iid[:-4] + "_yoy"
        if yoy_id not in iid_set:
            continue
        mism = con.execute(
            "SELECT count(*) FROM observation a JOIN observation b "
            "ON a.period_date = b.period_date "
            "WHERE a.indicator_id = ? AND b.indicator_id = ? "
            "AND month(a.period_date) = 1 AND abs(a.value - b.value) > 1e-9",
            [iid, yoy_id],
        ).fetchone()[0]
        if mism:
            problems.append(
                f"{iid}/{yoy_id}: 每年1月 累计!=当月 共 {mism} 期"
                f"(年度重置恒等破坏 → 疑似 0.1 级源污染)"
            )
    return problems


def main() -> int:
    ap = argparse.ArgumentParser(description="PIT 数据层初始化")
    ap.add_argument("--db", default=DB_DEFAULT)
    ap.add_argument("--raw", default=RAW_DEFAULT)
    ap.add_argument("--snapshots", default=SNAP_DEFAULT)
    ap.add_argument("--vintage", default=None, help="快照日期,默认今天")
    ap.add_argument("--check", action="store_true", help="只检查数据文件,不建库")
    args = ap.parse_args()

    if args.check:
        # 按指标计可用数(共享文件指标各自计数),不用 总数-缺失唯一文件 的近似
        ok = [iid for iid, raw_file, *_ in INDICATORS
              if os.path.exists(os.path.join(args.raw, raw_file))]
        missing = sorted({raw_file for _iid, raw_file, *_ in INDICATORS
                          if not os.path.exists(os.path.join(args.raw, raw_file))})
        print(f"可用指标: {len(ok)}/{len(INDICATORS)} ({', '.join(ok) or '无'})")
        if missing:
            print(f"缺失文件: {missing}")
        return 0

    os.makedirs(os.path.dirname(args.db), exist_ok=True)
    con = duckdb.connect(args.db)

    # 1) 建表(幂等)
    con.execute(DDL_INDICATOR_META)
    con.execute(DDL_OBSERVATION)
    con.execute(DDL_METHODOLOGY_VERSION)

    # 2) 元数据填充
    _fill_indicator_meta(con)
    _fill_methodology_versions(con)

    # 3) 迁移(逐指标,缺文件跳过,重跑可补齐)
    vintage = date.fromisoformat(args.vintage) if args.vintage else date.today()
    total = 0
    done, skipped = [], []
    for ind in INDICATORS:
        try:
            n = _migrate_indicator(con, ind, args.raw, vintage)
        except (ValueError, FileNotFoundError) as e:
            print(f"  !! {ind[0]}: {e}")
            skipped.append(ind[0])
            continue
        if n:
            done.append(f"{ind[0]}({n})")
            total += n
        else:
            skipped.append(ind[0])

    # 4) 快照
    snap = _rebuild_snapshot(con, args.snapshots, vintage)

    print(f"库: {args.db}")
    print(f"迁移: {', '.join(done) or '无'}")
    if skipped:
        print(f"跳过(文件未就绪): {', '.join(skipped)}")
    print(f"合计 {total} 行 | 快照: {snap}")

    # 5) 自检(反假通过): 行数核对 + 发布日口径断言(按 REQUIRED 逐项校验)
    # 依据 freq 分支: D 频 == period_date 当日; M/Q 频 == period 月末 + lag 天。
    # 注意不可用 lag==0 判别日频——PMI 是 M 频 + lag=0(月末发布口径)。
    problems = _verify_migration(con, args.raw)
    for iid in sorted(REQUIRED):
        row = con.execute(
            "SELECT release_lag_days, freq FROM indicator_meta WHERE indicator_id = ?", [iid]
        ).fetchone()
        if row is None or row[0] is None:
            problems.append(f"{iid}: indicator_meta 缺 release_lag_days,无法做发布日断言")
            continue
        lag = int(row[0])
        freq = str(row[1])
        if freq == "D":
            bad = con.execute(
                "SELECT count(*) FROM observation o WHERE indicator_id = ? "
                "AND o.announcement_date != o.period_date", [iid]
            ).fetchone()[0]
            label = "period 当日"
        elif freq == "M":
            bad = con.execute(
                "SELECT count(*) FROM observation o WHERE indicator_id = ? "
                "AND o.announcement_date != last_day(o.period_date) + ?::INTEGER",
                [iid, lag]
            ).fetchone()[0]
            label = f"period 月末 + {lag} 天"
        else:  # freq == "Q": 季末 = 季首 + 3月 - 1天, 与 _announcement_date 季末分支同口径
            # 注意: DATE_TRUNC 返回 TIMESTAMP, DuckDB 无 +(TIMESTAMP,INTEGER),
            # 必须先 ::DATE 再 + lag(否则 BinderException, 2026-09-25 qucoder 实测确认)
            bad = con.execute(
                "SELECT count(*) FROM observation o WHERE indicator_id = ? "
                "AND o.announcement_date != "
                "(DATE_TRUNC('quarter', o.period_date) + INTERVAL 3 MONTH - INTERVAL 1 DAY)::DATE "
                "+ ?::INTEGER",
                [iid, lag]
            ).fetchone()[0]
            label = f"period 季末 + {lag} 天"
        if bad:
            problems.append(f"{iid} 有 {bad} 行 announcement_date != {label}")
    if problems:
        print("!! 自检失败:")
        for p in problems:
            print(f"   - {p}")
        con.close()
        return 2
    print(f"自检: 行数核对 ✅ + 发布日口径 ✅ ({', '.join(sorted(REQUIRED))})")
    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
