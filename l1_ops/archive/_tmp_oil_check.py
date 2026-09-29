# -*- coding: utf-8 -*-
"""临时脚本：第19项 oil(FRED布伦特) 终检独立抽查（跑完即删）"""
import csv
from collections import defaultdict
from datetime import date

D = r"C:\new_tdx64\PYPlugins\user\data\raw_data\brent_fred_daily.csv"
M = r"C:\new_tdx64\PYPlugins\user\data\raw_data\macro_oil_monthly.csv"

drows = list(csv.reader(open(D, encoding="utf-8")))
dhdr, dbody = drows[0], [r for r in drows[1:] if r and r[0]]
dd = [r[0] for r in dbody]
dv = [float(r[1]) for r in dbody]
d2v = dict(zip(dd, dv))

print("== 1. 日频结构 ==")
print(f"header: {dhdr} | 行: {len(dbody)} | 区间: {dd[0]}~{dd[-1]}")
print(f"唯一: {len(dd)==len(set(dd))} | 单调: {dd==sorted(dd)} | 空值: {sum(1 for v in dv if v!=v)}")

print("\n== 2. 日频锚点 5/5 ==")
for d, e in [("1998-12-10", 9.10), ("2008-07-03", 143.95), ("2020-04-20", 17.36),
             ("2022-03-08", 133.18), ("2026-09-22", 114.89)]:
    got = d2v.get(d)
    print(f"{d}: {got} (期望 {e}) {'✓' if got is not None and abs(got-e) < 1e-9 else '✗'}")
print(f"日频值域: [{min(dv)}, {max(dv)}] (声明 [9.10, 143.95])")

print("\n== 3. 月频结构 ==")
mrows = list(csv.reader(open(M, encoding="utf-8")))
mhdr, mbody = mrows[0], [r for r in mrows[1:] if r and r[0]]
ym = [r[0] for r in mbody]
mavg = {r[0]: float(r[1]) for r in mbody}
myoy = {r[0]: float(r[2]) for r in mbody}
print(f"header: {mhdr} | 行: {len(mbody)} | 区间: {ym[0]}~{ym[-1]}")
print(f"月均值域: [{min(mavg.values())}, {max(mavg.values())}] (声明 [9.83, 132.72])")
yv = list(myoy.values())
print(f"同比域: [{min(yv)}, {max(yv)}] (声明 [-74.2%, 252.6%])")
ymn = min(myoy, key=myoy.get); ymx = max(myoy, key=myoy.get)
print(f"同比极值落点: min {myoy[ymn]:.1f}%@{ymn} | max {myoy[ymx]:.1f}%@{ymx}")

print("\n== 4. 独立重算: 月均值=自然月交易日均值 (抽 3 月) ==")
by_month = defaultdict(list)
for d, v in zip(dd, dv):
    by_month[d[:7]].append(v)
for ym_ in ["2015-06", "2020-04", "2026-08"]:
    calc = sum(by_month[ym_]) / len(by_month[ym_])
    got = mavg.get(ym_ + "-01") or mavg.get(ym_)
    print(f"{ym_}: 独立重算={calc:.4f} vs 文件={got} {'✓' if abs(calc-got) < 5e-4 else '✗'} (交易日 {len(by_month[ym_])} 日)")

print("\n== 5. 独立重算: 同比=月均值 yoy (抽 2 月) ==")
for ym_ in ["2021-04", "2020-04"]:
    cur = mavg.get(ym_ + "-01") or mavg.get(ym_)
    y, m = map(int, ym_.split("-"))
    py, pm = (y - 1, m) if m > 12 else (y - 1, m)
    prev_ym = f"{y-1:04d}-{m:02d}"
    prev = mavg.get(prev_ym + "-01") or mavg.get(prev_ym)
    if prev:
        calc = (cur / prev - 1) * 100
        got = myoy.get(ym_ + "-01") or myoy.get(ym_)
        print(f"{ym_}: 重算={calc:.4f}% vs 文件={got}% {'✓' if abs(calc-got) < 1e-6 else '✗'}")

print("\n== 6. 起始策略: 月频 473→461 (丢前 12 月) ==")
first_daily_ym, last_daily_ym = dd[0][:7], dd[-1][:7]
print(f"日频覆盖: {first_daily_ym} ~ {last_daily_ym} = 月数对齐检查; 月频起点 {ym[0]} (声明 1988-05 = 日频起点+12月)")

print("\n== 7. 末月不完整月提示 ==")
print(f"日频最新 {dd[-1]} / 月频末月 {ym[-1]} → 末月均值将随新月更新 (使用须知①)")
print("DONE")
