"""pg_conn.py — NAS quant-pg 连接封装 (2026-09-15 实测验证版)

用法:
    from pg_conn import pg
    rows = pg.query("SELECT * FROM factors WHERE trade_date > %s", ("2026-09-01",))
    pg.insert_many("factor_daily", ["trade_date", "code", "value"], rows)
    # 进程退出自动 close; 也可显式 pg.close()

设计要点 (对应实测结论):
  - keepalive 30s: 内核实测生效, 空闲连接不被中继/NAT 悄悄掐死
  - 单连接复用: 建连一次 2.9s, 复用查询 0.36s/笔 — 绝不每笔操作建连
  - 断线自愈: OperationalError/InterfaceError 时重建连接重试一次
  - insert_many 走 COPY 协议: 1000行 2.4s / 1万行 3.5s / 5万行 8.9s
    (对比 executemany 逐行=每行0.5s, execute_values 默认=1万行65s)
"""
import os
import atexit
from io import StringIO

import psycopg2
from psycopg2 import OperationalError, InterfaceError


def _esc(v):
    """COPY 文本格式转义"""
    if v is None:
        return "\\N"
    s = str(v)
    return (s.replace("\\", "\\\\")
             .replace("\t", "\\t")
             .replace("\n", "\\n")
             .replace("\r", "\\r"))


class PgConn:
    def __init__(self):
        self._conn = None

    @property
    def dsn(self):
        return dict(
            host=os.environ.get("QUANT_PG_HOST", "100.76.208.125"),
            port=int(os.environ.get("QUANT_PG_PORT", "5432")),
            user=os.environ.get("QUANT_PG_USER", "postgres"),
            password=os.environ.get("QUANT_PG_PASSWORD"),
            dbname=os.environ.get("QUANT_PG_DB", "quant"),
            connect_timeout=15,
            keepalives=1,
            keepalives_idle=30,       # 30s 空闲发探测 (实测内核生效)
            keepalives_interval=10,
            keepalives_count=6,
            application_name="quant-pipeline",
        )

    @property
    def conn(self):
        if self._conn is None or self._conn.closed:
            self._conn = psycopg2.connect(**self.dsn)
        return self._conn

    # ---------- 内部: 带一次重连重试的执行 ----------
    def _exec_retry(self, fn):
        for attempt in (1, 2):
            try:
                return fn(self.conn.cursor())
            except (OperationalError, InterfaceError):
                if attempt == 2:
                    raise
                self._conn = None    # 连接已死 -> 下次取 conn 时重建
        raise RuntimeError("unreachable")

    # ---------- 对外 API ----------
    def query(self, sql, params=None):
        """查询返回 list[tuple]"""
        cur = self._exec_retry(lambda c: (c.execute(sql, params), c)[1])
        return cur.fetchall()

    def execute(self, sql, params=None):
        """单条执行 + commit"""
        self._exec_retry(lambda c: c.execute(sql, params))
        self.conn.commit()

    def insert_many(self, table, columns, rows):
        """批量写入 (COPY 协议)。values 里 None -> NULL"""
        def _do(c):
            buf = StringIO()
            for row in rows:
                buf.write("\t".join(_esc(v) for v in row))
                buf.write("\n")
            buf.seek(0)
            c.copy_expert(f"COPY {table} ({','.join(columns)}) FROM STDIN", buf)

        self._exec_retry(_do)        # COPY 失败自动重连重试 (单事务, 失败即回滚, 重试安全)
        self.conn.commit()

    def close(self):
        if self._conn is not None and not self._conn.closed:
            self._conn.close()


pg = PgConn()
atexit.register(pg.close)
