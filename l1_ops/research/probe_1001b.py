#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""10-01 扩源边界实测②: 长区间/历史深度/性能 — 只读"""
import json, time
import pandas as pd
import akshare as ak

out = {}

# 1. bond_china_yield 长区间(分段测)
for (s, e, tag) in [("20090101", "20091231", "2009全年"),
                    ("20150101", "20151231", "2015全年"),
                    ("20250101", "20251231", "2025全年")]:
    t0 = time.time()
    try:
        df = ak.bond_china_yield(start_date=s, end_date=e)
        aaa = df[df["曲线名称"] == "中债中短期票据收益率曲线(AAA)"]
        out[f"bond_{tag}"] = {"rows": len(df), "aaa_rows": len(aaa),
                              "sec": round(time.time()-t0, 1),
                              "dates": [str(aaa["日期"].min()), str(aaa["日期"].max())],
                              "10y_nonnull": int(aaa["10年"].notna().sum()),
                              "10y_head": None if aaa.empty else float(aaa["10年"].dropna().iloc[0]),
                              "10y_tail": None if aaa.empty else float(aaa["10年"].dropna().iloc[-1])}
    except Exception as ex:
        out[f"bond_{tag}"] = {"ERR": f"{type(ex).__name__}: {ex}"}

# 2. repo_rate_hist FDR007 历史非空起点
for (s, e, tag) in [("20060101", "20081231", "2006-2008"),
                    ("20140101", "20141231", "2014"),
                    ("20180101", "20181231", "2018")]:
    try:
        df = ak.repo_rate_hist(start_date=s, end_date=e)
        nn = df["FDR007"].notna().sum()
        out[f"repo_{tag}"] = {"rows": len(df), "fdr007_nonnull": int(nn),
                              "fdr007_min": None if nn == 0 else float(df["FDR007"].min()),
                              "fdr007_max": None if nn == 0 else float(df["FDR007"].max())}
    except Exception as ex:
        out[f"repo_{tag}"] = {"ERR": f"{type(ex).__name__}: {ex}"}

# 3. LPR 有效起点(LPR1Y 非空)
df = ak.macro_china_lpr()
nn = df[df["LPR1Y"].notna()]
out["lpr"] = {"rows": len(df), "valid_rows": len(nn),
              "start": str(nn["TRADE_DATE"].min()), "end": str(nn["TRADE_DATE"].max()),
              "tail3": nn.tail(3)[["TRADE_DATE", "LPR1Y", "LPR5Y"]].to_dict("records")}

# 4. 中债曲线可用起点(2008 试)
try:
    df = ak.bond_china_yield(start_date="20080101", end_date="20080131")
    aaa = df[df["曲线名称"] == "中债中短期票据收益率曲线(AAA)"]
    out["bond_2008"] = {"rows": len(df), "aaa_rows": len(aaa),
                        "dates": [str(aaa["日期"].min()), str(aaa["日期"].max())] if len(aaa) else []}
except Exception as ex:
    out["bond_2008"] = {"ERR": f"{type(ex).__name__}: {ex}"}

print(json.dumps(out, ensure_ascii=False, indent=1, default=str))
