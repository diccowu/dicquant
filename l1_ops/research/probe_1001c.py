#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""10-01 扩源边界实测③: DR007 精确起点 + bond 增量性能"""
import json, time
import pandas as pd
import akshare as ak

out = {}

# DR007 FDR007 精确起点: 2014-01~2016-12 逐段
for (s, e, tag) in [("20141201", "20151231", "2014.12-2015"),
                    ("20160101", "20161231", "2016"),
                    ("20170101", "20171231", "2017")]:
    try:
        df = ak.repo_rate_hist(start_date=s, end_date=e)
        nn = df[df["FDR007"].notna()]
        out[f"repo_{tag}"] = {"rows": len(df), "fdr007_nonnull": len(nn),
                              "start": str(nn["date"].min()) if len(nn) else None,
                              "end": str(nn["date"].max()) if len(nn) else None,
                              "min": float(nn["FDR007"].min()) if len(nn) else None,
                              "max": float(nn["FDR007"].max()) if len(nn) else None}
    except Exception as ex:
        out[f"repo_{tag}"] = {"ERR": f"{type(ex).__name__}: {ex}"}

# bond_china_yield 增量性能: 最近 30 天
t0 = time.time()
try:
    df = ak.bond_china_yield(start_date="20260901", end_date="20260930")
    aaa = df[df["曲线名称"] == "中债中短期票据收益率曲线(AAA)"]
    out["bond_recent30"] = {"sec": round(time.time()-t0, 1), "aaa_rows": len(aaa),
                            "dates": [str(aaa["日期"].min()), str(aaa["日期"].max())],
                            "10y_nonnull": int(aaa["10年"].notna().sum()),
                            "10y_tail": float(aaa["10年"].dropna().iloc[-1])}
except Exception as ex:
    out["bond_recent30"] = {"ERR": f"{type(ex).__name__}: {ex}"}

print(json.dumps(out, ensure_ascii=False, indent=1, default=str))
