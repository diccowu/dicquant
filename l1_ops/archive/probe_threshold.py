#!/usr/bin/env python3
"""用数据定连续性阈值: 对比 ①逐日pct ②相对20日滚动中位数偏离, 找全历史零误报的阈值"""
import pandas as pd

DAILY = "/mnt/c/new_tdx64/PYPlugins/user/data/raw_data/macro_margin_ad_daily.csv"
dl = pd.read_csv(DAILY)
dl["date"] = dl["date"].astype(str)

for col in ["margin_balance", "margin_purchase"]:
    s = dl[col].astype(float)
    pct = s.pct_change().abs()
    med20 = s.rolling(20, min_periods=5).median()
    dev20 = (s / med20 - 1).abs()
    print(f"\n{'='*66}\n{col}\n{'='*66}")
    print("  ① |逐日 pct|            " + "  ".join(
        f">{t:.0%}:{int((pct>t).sum())}" for t in [0.10, 0.20, 0.30, 0.40]))
    print("  ② |相对20日中位偏离|    " + "  ".join(
        f">{t:.0%}:{int((dev20>t).sum())}" for t in [0.10, 0.20, 0.30, 0.40]))
    print("  ②' 同上但限 2015 年后  " + "  ".join(
        f">{t:.0%}:{int((dev20[dl.date>='2015-01-01']>t).sum())}" for t in [0.10, 0.20, 0.30, 0.40]))
    # 找出 ② 各阈值下的具体日期(看是否可解释)
    for t in [0.20, 0.30, 0.40]:
        idx = dev20[dev20 > t].index
        if len(idx):
            print(f"    偏{ t:.0%} 超限日: " + ", ".join(
                f"{dl.date[i]}({dev20[i]*100:.0f}%)" for i in idx[:6]))
    # 事故检测能力: 用残缺态值替换 09-24 会怎样
    i = dl.index[dl.date == "2026-09-24"][0]
    fake = s.copy(); fake[i] = 1350506223746.0
    fmed = fake.rolling(20, min_periods=5).median()
    fdev = (fake / fmed - 1).abs()
    print(f"  ★ 残缺态(09-24=1.35e12) 检出: pct={pct[i]*100:.0f}% "
          f"dev20={fdev[i]*100:.0f}%  (阈值20%→{'抓得住' if fdev[i]>0.2 else '漏'} / "
          f"40%→{'抓得住' if fdev[i]>0.4 else '漏'})")
