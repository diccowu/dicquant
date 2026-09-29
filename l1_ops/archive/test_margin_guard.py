#!/usr/bin/env python3
"""实测: collect_margin 返回的 prim(同日多行) 能否通过 guard"""
import importlib.util, sys
from datetime import date

spec = importlib.util.spec_from_file_location("l1u", "/root/l1_ops/l1_update.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

print("=== collect_margin(since=2026-09-23) ===")
prim, daily = m.collect_margin(date(2026, 9, 23))
print(f"prim 行数={len(prim)}")
if len(prim):
    print(prim[["date", "exchange", "margin_trade_balance", "purchase_amt"]].to_string())
print(f"\ndaily 行数={len(daily)}")
if len(daily):
    print(daily.to_string())

print()
print("=== guard(prim, ...) 实测(模拟主流程调用) ===")
try:
    m.guard(prim, "macro_margin_ad_daily.csv", [], {}, "date")
    print(">>> guard PASSED")
except Exception as e:
    print(f">>> guard RAISED: {type(e).__name__}: {e}")

print()
print("=== guard(daily, ...) 对照 ===")
try:
    m.guard(daily, "daily", ["margin_balance", "margin_purchase"],
            {"margin_balance": (0.0, 5e12), "margin_purchase": (0.0, 1e13)}, "date")
    print(">>> guard(daily) PASSED")
except Exception as e:
    print(f">>> guard(daily) RAISED: {type(e).__name__}: {e}")
