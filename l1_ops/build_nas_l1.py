#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
L1 数据层建库与迁移: DuckDB(pit.db 权威源) → NAS PostgreSQL(quant-pg 主库)

职责(本脚本只做一次性建库+迁移, 不做日常更新):
  1. 建 3 表: l1_indicator_meta / l1_observation / l1_methodology_version (幂等 IF NOT EXISTS)
  2. COPY 协议批量迁移(高延迟链路必须用 COPY, 见 quant-pg.md 实测)
  3. 迁移后验证: 行数 / NULL / 值域 / meta 一致 / 发布日口径抽样

用法:
  python build_nas_l1.py            # 建表+迁移+验证
  python build_nas_l1.py --verify   # 仅验证(不迁移)
"""
import sys, io, argparse, os

import duckdb
import psycopg2

DUCKDB_PATH = '/mnt/c/new_tdx64/PYPlugins/user/data/pit/pit.db'
PG = dict(host='100.76.208.125', port=5432, user='postgres',
          password=os.environ.get('QUANT_PG_PASSWORD'), dbname='quant', connect_timeout=20)

DDL = [
    """CREATE TABLE IF NOT EXISTS l1_indicator_meta (
        indicator_id     TEXT PRIMARY KEY,
        raw_file         TEXT NOT NULL,
        freq             CHAR(1) NOT NULL,
        sa_flag          SMALLINT NOT NULL DEFAULT 0,
        methodology      TEXT,
        release_lag_days INTEGER NOT NULL DEFAULT 0,
        source           TEXT,
        description      TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS l1_observation (
        indicator_id      TEXT NOT NULL,
        period_date       DATE NOT NULL,
        announcement_date DATE NOT NULL,
        vintage_date      DATE NOT NULL,
        value             DOUBLE PRECISION NOT NULL,
        status            TEXT NOT NULL DEFAULT 'initial',
        PRIMARY KEY (indicator_id, period_date, vintage_date)
    )""",
    """CREATE TABLE IF NOT EXISTS l1_methodology_version (
        indicator_id TEXT NOT NULL,
        version      TEXT NOT NULL,
        valid_from   DATE,
        valid_to     DATE,
        change_desc  TEXT,
        verified     SMALLINT NOT NULL DEFAULT 0,
        PRIMARY KEY (indicator_id, version)
    )""",
]

TABLES = {
    'l1_indicator_meta':
        "SELECT indicator_id, raw_file, freq, sa_flag, methodology, "
        "release_lag_days, source, description FROM indicator_meta",
    'l1_observation':
        "SELECT indicator_id, period_date, announcement_date, vintage_date, "
        "value, status FROM observation",
    'l1_methodology_version':
        "SELECT indicator_id, version, valid_from, valid_to, change_desc, "
        "verified FROM methodology_version",
}


def pg_connect():
    return psycopg2.connect(**PG)


def copy_in(cur, table, rows):
    """COPY FROM STDIN 批量写 (rows 为可迭代的行元组序列)"""
    buf = io.StringIO()
    for r in rows:
        buf.write('\t'.join('\\N' if v is None else str(v) for v in r) + '\n')
    buf.seek(0)
    cur.copy_expert(
        f"COPY {table} FROM STDIN WITH (FORMAT text, NULL '\\N')", buf)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--verify', action='store_true', help='仅验证,不迁移')
    args = ap.parse_args()

    con = duckdb.connect(DUCKDB_PATH, read_only=True)
    pg = pg_connect()
    pg.autocommit = False
    cur = pg.cursor()

    if not args.verify:
        print('[1/3] 建表 ...')
        for d in DDL:
            cur.execute(d)
        pg.commit()
        cur.execute("SELECT tablename FROM pg_tables WHERE schemaname='public' "
                    "AND tablename LIKE 'l1_%' ORDER BY tablename")
        print('      已建:', [r[0] for r in cur.fetchall()])

        print('[2/3] 迁移 (COPY 协议) ...')
        for t, sql in TABLES.items():
            cur.execute(f"TRUNCATE {t}")
            rows = con.execute(sql).fetchall()
            copy_in(cur, t, rows)
            pg.commit()
            cur.execute(f"SELECT count(*) FROM {t}")
            print(f'      {t}: 迁入 {len(rows)} 行, 库内 {cur.fetchone()[0]} 行')

    print('[3/3] 验证 ...')
    ok = True

    # 3.1 行数逐表核对
    for t, sql in TABLES.items():
        d_n = con.execute(f"SELECT count(*) FROM ({sql}) ").fetchone()[0]
        cur.execute(f"SELECT count(*) FROM {t}")
        p_n = cur.fetchone()[0]
        flag = 'OK' if d_n == p_n else 'MISMATCH'
        ok &= (d_n == p_n)
        print(f'      {t}: DuckDB {d_n} vs PG {p_n} [{flag}]')

    # 3.2 NULL value 必须为 0 (PIT 红线零填充)
    cur.execute('SELECT count(*) FROM l1_observation WHERE value IS NULL')
    n_null = cur.fetchone()[0]
    ok &= (n_null == 0)
    print(f'      value NULL: {n_null} [{"OK" if n_null == 0 else "FAIL"}]')

    # 3.3 指标数 + 逐指标行数抽样
    cur.execute('SELECT count(*) FROM l1_indicator_meta')
    n_meta = cur.fetchone()[0]
    ok &= (n_meta == 18)
    print(f'      indicator_meta: {n_meta} 项 [{"OK" if n_meta == 18 else "FAIL"}]')
    cur.execute('SELECT count(DISTINCT indicator_id) FROM l1_observation')
    n_obs_ind = cur.fetchone()[0]
    ok &= (n_obs_ind == 18)
    print(f'      observation 覆盖指标: {n_obs_ind}/18 [{"OK" if n_obs_ind == 18 else "FAIL"}]')

    # 3.4 发布日口径抽样 (pmi 月末 lag=0 / cpi 月末+14 / m2 月末+17)
    # 注: period_date 锚点约定按源文件而异 —— pmi 用月初(2026-07-01),
    #     cpi/m2 用月末(2026-07-31); announcement_date 语义一致(发布日)
    checks = [
        ("SELECT announcement_date::text FROM l1_observation "
         "WHERE indicator_id='pmi' AND period_date='2026-07-01'",
         '2026-07-31', 'pmi 月末 lag=0'),
        ("SELECT announcement_date::text FROM l1_observation "
         "WHERE indicator_id='cpi_yoy' AND period_date='2026-07-31'",
         '2026-08-14', 'cpi 月末+14'),
        ("SELECT announcement_date::text FROM l1_observation "
         "WHERE indicator_id='m2_yoy' AND period_date='2026-07-31'",
         '2026-08-17', 'm2 月末+17'),
    ]
    for sql, expect, label in checks:
        cur.execute(sql)
        got = cur.fetchone()
        got = got[0] if got else None
        f = 'OK' if got == expect else 'FAIL'
        ok &= (got == expect)
        print(f'      {label}: {got} [期望 {expect}] [{f}]')

    # 3.5 值域抽样 (4 个新指标)
    for ind, lo, hi in [('float_cap', 6.0e8, 5.3e9), ('hs300_pe_ttm', 8.5, 20.5),
                        ('usdcny', 6.0, 8.8), ('oil', 9.0, 144.0)]:
        cur.execute(f"SELECT min(value), max(value) FROM l1_observation "
                    f"WHERE indicator_id='{ind}'")
        mn, mx = cur.fetchone()
        f = 'OK' if (mn is not None and lo <= mn and mx <= hi) else 'FAIL'
        ok &= (f == 'OK')
        print(f'      {ind} 值域: {mn:.4g} ~ {mx:.4g} [界 {lo:.4g}~{hi:.4g}] [{f}]')

    cur.execute("SELECT pg_size_pretty(pg_database_size('quant'))")
    print('      库大小:', cur.fetchone()[0])

    con.close()
    pg.close()
    print('\n结论:', 'ALL PASS ✅' if ok else 'FAIL ❌')
    return 0 if ok else 2


if __name__ == '__main__':
    sys.exit(main())
