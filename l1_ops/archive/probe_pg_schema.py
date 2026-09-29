#!/usr/bin/env python3
"""查 l1_observation 表结构与 09-24 两融现状(只读)"""
import os, psycopg2

dsn = os.environ.get("L1_PG_DSN", "host=100.76.208.125 port=5432 user=postgres "
                     "dbname=quant connect_timeout=20")
conn = psycopg2.connect(dsn)
cur = conn.cursor()

print("=== 1. 表结构 ===")
cur.execute("""
  SELECT column_name, data_type, is_nullable, column_default
  FROM information_schema.columns
  WHERE table_name='l1_observation' ORDER BY ordinal_position
""")
for r in cur.fetchall():
    print(f"  {r[0]:20s} {r[1]:25s} null={r[2]:3s} default={r[3]}")

print()
print("=== 2. 约束/索引 ===")
cur.execute("""
  SELECT indexname, indexdef FROM pg_indexes WHERE tablename='l1_observation'
""")
for r in cur.fetchall():
    print(f"  {r[0]}\n    {r[1]}")

print()
print("=== 3. status 取值分布 ===")
cur.execute("SELECT status, count(*) FROM l1_observation GROUP BY status")
for r in cur.fetchall():
    print(f"  {r[0]}: {r[1]}")

print()
print("=== 4. 09-24 两融现存行(含全部 vintage) ===")
cur.execute("""
  SELECT indicator_id, period_date, vintage_date, value, status
  FROM l1_observation
  WHERE indicator_id IN ('margin_balance','margin_purchase') AND period_date='2026-09-24'
  ORDER BY indicator_id, vintage_date
""")
for r in cur.fetchall():
    print(f"  {r[0]:16s} {r[1]} vin={r[2]} value={float(r[3]):>18,.0f} status={r[4]}")

print()
print("=== 5. 其它指标是否也用了同一交易日(检查有无同类残缺) ===")
cur.execute("""
  SELECT indicator_id, period_date, value, vintage_date
  FROM l1_observation
  WHERE period_date IN ('2026-09-23','2026-09-24')
    AND indicator_id NOT IN ('margin_balance','margin_purchase')
  ORDER BY period_date, indicator_id
""")
for r in cur.fetchall():
    print(f"  {r[0]:16s} {r[1]} value={float(r[2]):>18,.3f} vin={r[3]}")

conn.close()
