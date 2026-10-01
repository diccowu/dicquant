#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""10-01 L1 扩源: 6 个新源接口实测(只读, 不落库) — 列名/值域/历史深度/发布节奏"""
import json, struct, urllib.request
from datetime import date
import pandas as pd
import akshare as ak

L = []
def p(*a):
    s = " ".join(str(x) for x in a)
    L.append(s)
    print(s, flush=True)

p("# akshare", ak.__version__)

def probe(name, fn):
    p("")
    p("=" * 60)
    p(f"## {name}")
    try:
        r = fn()
        p(json.dumps(r, ensure_ascii=False, default=str, indent=1)[:5000])
    except Exception as e:
        p(f"!! ERR {type(e).__name__}: {e}")

# 1 DR007
def f1():
    df = ak.repo_rate_hist(start_date="20260920", end_date="20260930")
    return {"cols": list(df.columns), "rows": len(df), "tail": df.tail(3).to_dict("records")}
probe("repo_rate_hist (DR007)", f1)

# 2 Shibor all
def f2():
    df = ak.macro_china_shibor_all()
    return {"cols": list(df.columns), "rows": len(df), "tail": df.tail(2).to_dict("records")}
probe("macro_china_shibor_all", f2)

# 3 LPR
def f3():
    df = ak.macro_china_lpr()
    return {"cols": list(df.columns), "rows": len(df),
            "head": df.head(2).to_dict("records"), "tail": df.tail(3).to_dict("records")}
probe("macro_china_lpr", f3)

# 4 bond_china_yield
def f4():
    df = ak.bond_china_yield(start_date="20260925", end_date="20260930")
    return {"cols": list(df.columns), "rows": len(df),
            "curves": sorted(df["曲线名称"].unique().tolist()) if "曲线名称" in df.columns else None,
            "tail": df.tail(3).to_dict("records")}
probe("bond_china_yield", f4)

# 5 FRED NBCNBIS
def f5():
    url = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=NBCNBIS"
    raw = urllib.request.urlopen(url, timeout=60).read().decode()
    lines = [l for l in raw.strip().split("\n") if l.strip()]
    return {"header": lines[0], "n": len(lines) - 1, "first": lines[1], "last": lines[-1]}
probe("FRED NBCNBIS", f5)

# 6 sh880001.day
def f6():
    pth = "/mnt/c/new_tdx64/vipdoc/sh/lday/sh880001.day"
    data = open(pth, "rb").read()
    n = len(data) // 32
    recs = []
    for i in range(max(0, n - 3), n):
        d, o, h, l, c, amt, vol, _ = struct.unpack("<iiiiifii", data[i * 32:(i + 1) * 32])
        recs.append({"date": d, "close": c / 100.0, "amount": amt, "vol": vol})
    return {"n": n, "size": len(data), "tail": recs}
probe("sh880001.day", f6)

with open("/root/l1_ops/research/probe_1001.txt", "w") as fh:
    fh.write("\n".join(L))
p("")
p(">> written /root/l1_ops/research/probe_1001.txt")
