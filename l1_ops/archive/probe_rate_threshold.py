#!/usr/bin/env python3
"""阈值实测: treasury_y1/y10, us10y 收益率序列的连续性分布
收益率接近 0 → 相对偏离会失真, 同时测 相对20日中位偏离 和 绝对bp变动
"""
import pandas as pd

D = "/mnt/c/new_tdx64/PYPlugins/user/data/raw_data"

def report(name, s, is_rate=True):
    s = s.astype(float)
    med20 = s.rolling(20, min_periods=5).median()
    rel = (s / med20 - 1).abs()
    abs_bp = (s.diff().abs() * 100)   # 变动的百分点 *100 → bp 差
    mature = pd.Series(True, index=s.index)
    print(f"\n=== {name} (n={len(s)}) ===")
    print(f"  值域: {s.min():.4f} ~ {s.max():.4f} | 末日 {s.index[-1]}")
    print(f"  相对20日中位偏离: p50={rel.quantile(.5)*100:.2f}% p99={rel.quantile(.99)*100:.2f}% "
          f"max={rel.max()*100:.2f}% | >10%:{int((rel>.10).sum())} >15%:{int((rel>.15).sum())} "
          f">20%:{int((rel>.20).sum())} >30%:{int((rel>.30).sum())} >40%:{int((rel>.40).sum())}")
    print(f"  绝对bp变动(日): p50={abs_bp.quantile(.5):.2f}bp p99={abs_bp.quantile(.99):.2f}bp "
          f"max={abs_bp.max():.2f}bp | >10bp:{int((abs_bp>10).sum())} >20bp:{int((abs_bp>20).sum())} "
          f">50bp:{int((abs_bp>50).sum())}")
    # 相对偏离超限日期(看可解释性)
    for t in [0.15, 0.20]:
        idx = rel[rel > t].index
        if len(idx):
            print(f"    相对>{t:.0%} 日期: " + ", ".join(f"{d}({rel[d]*100:.0f}%)" for d in idx[:8]))


d = pd.read_csv(f"{D}/macro_treasury_ad_primary.csv", dtype=str)
d["date"] = pd.to_datetime(d["date"])
report("treasury_y1", d.set_index("date")["y1"])
report("treasury_y10", d.set_index("date")["y10"])

u = pd.read_csv(f"{D}/macro_us10y_primary.csv", dtype=str)
u["date"] = pd.to_datetime(u["date"])
report("us10y", u.set_index("date")["us10y"])