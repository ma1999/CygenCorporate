import asyncio
import os
import threading
import time
from dotenv import load_dotenv
from pathlib import Path
import mysql.connector
from mysql.connector import pooling

BASE_DIR = Path(__file__).resolve().parent.parent.parent
print(BASE_DIR)
ENV_FILE = BASE_DIR / ".env"

load_dotenv(ENV_FILE)


class DatabaseError(Exception):
    """Raised by the strict DB API (``fetch`` / ``transaction``) when the
    database is unreachable or a query fails."""


class Tx:
    """Sync helpers handed to ``Database.transaction`` callbacks."""

    def __init__(self, cur):
        self.cur = cur

    def rows(self, sql, params=()):
        self.cur.execute(sql, params)
        return self.cur.fetchall()

    def one(self, sql, params=()):
        self.cur.execute(sql, params)
        rows = self.cur.fetchall()
        return rows[0] if rows else None

    def run(self, sql, params=()):
        """Execute a write; returns lastrowid."""
        self.cur.execute(sql, params)
        return self.cur.lastrowid

    def many(self, sql, seq):
        if seq:
            self.cur.executemany(sql, seq)


class Database:
    """Async wrapper around mysql-connector-python using a thread pool.

    Uses MySQLConnectionPool so each query reuses an open TCP connection
    instead of opening a fresh one. This dramatically reduces latency when
    the DB is on a remote host (RTT × queries-per-request).
    """

    def __init__(self):
        self._config = {
            "host": os.getenv("DB_HOST", "127.0.0.1"),
            "port": int(os.getenv("DB_PORT", 3306)),
            "user": os.getenv("DB_USER", "root"),
            "password": os.getenv("DB_PASSWORD", ""),
            "database": os.getenv("DB_NAME", "corporate_cms"),
            "autocommit": True,
        }
        # pool size: enough to cover concurrent Flask requests plus the
        # plugin manager / schema sync. Tunable via DB_POOL_SIZE env var.
        pool_size = max(2, int(os.getenv("DB_POOL_SIZE", "8") or 8))
        try:
            self._pool = pooling.MySQLConnectionPool(
                pool_name="cms_pool",
                pool_size=pool_size,
                # False: closing a pooled connection must not cost a network round trip (cmd_reset_connection)
                # per query; every code path here is autocommit or restores it (see ``transaction``).
                pool_reset_session=False,
                **self._config,
            )
        except Exception as e:
            print(f"[DB] pool init failed, falling back to per-query connect: {e}")
            self._pool = None

    def _conn(self):
        if self._pool is None:
            return mysql.connector.connect(**self._config)
        # MySQLConnectionPool raises immediately when every connection is busy;
        # under a burst (e.g. a page rendering several API calls at once) wait
        # briefly for one to be returned instead of failing the request.
        deadline = time.monotonic() + float(os.getenv("DB_POOL_WAIT", "10") or 10)
        while True:
            try:
                return self._pool.get_connection()
            except pooling.PoolError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.01)

    async def query(self, sql: str, params: tuple = (), *, one: bool = False):
        def run():
            try:
                conn = self._conn()
            except Exception as e:
                print(f"[DB] connection error: {e}")
                return None
            try:
                cur = conn.cursor(dictionary=True)
                cur.execute(sql, params)
                rows = cur.fetchall()
                return (rows[0] if rows else None) if one else rows
            except Exception as e:
                print(f"[DB] query error: {e}")
                return None
            finally:
                try:
                    # pool connections must be returned, not closed
                    if self._pool is not None:
                        conn.close()  # returns to pool
                    else:
                        conn.close()
                except Exception:
                    pass

        return await asyncio.to_thread(run)

    async def execute(self, sql: str, params: tuple = ()) -> int:
        def run():
            try:
                conn = self._conn()
            except Exception as e:
                print(f"[DB] connection error: {e}")
                return -1
            try:
                cur = conn.cursor()
                cur.execute(sql, params)
                conn.commit()
                return cur.lastrowid
            except Exception as e:
                print(f"[DB] execute error: {e}")
                return -1
            finally:
                try:
                    if self._pool is not None:
                        conn.close()  # returns to pool
                    else:
                        conn.close()
                except Exception:
                    pass

        return await asyncio.to_thread(run)

    # ---------- strict API (raises instead of swallowing) ----------
    # ``query``/``execute`` above print the error and return None / -1, which
    # makes "DB is down" indistinguishable from "no rows". Code that must tell
    # the two apart (the public JSON API, transactional admin saves) uses the
    # methods below. The legacy methods are unchanged.
    async def fetch(self, sql: str, params: tuple = (), *, one: bool = False):
        """Like ``query`` but raises :class:`DatabaseError` on any failure."""

        def run():
            try:
                conn = self._conn()
            except Exception as e:
                raise DatabaseError(f"connection error: {e}") from e
            try:
                cur = conn.cursor(dictionary=True)
                cur.execute(sql, params)
                rows = cur.fetchall()
                return (rows[0] if rows else None) if one else rows
            except Exception as e:
                raise DatabaseError(f"query error: {e}") from e
            finally:
                try:
                    conn.close()  # returns the connection to the pool
                except Exception:
                    pass

        return await asyncio.to_thread(run)

    async def transaction(self, fn):
        """Run ``fn(tx)`` in a worker thread inside ONE transaction.

        ``tx`` is a :class:`Tx` (sync helpers). Commits when ``fn`` returns,
        rolls back and re-raises when it raises (``mysql.connector`` errors
        such as IntegrityError pass through unchanged so callers can show a
        precise message). Connection failures raise :class:`DatabaseError`.
        """

        def run():
            try:
                conn = self._conn()
            except Exception as e:
                raise DatabaseError(f"connection error: {e}") from e
            try:
                conn.autocommit = False
                cur = conn.cursor(dictionary=True)
                try:
                    result = fn(Tx(cur))
                    conn.commit()
                    return result
                except Exception:
                    try:
                        conn.rollback()
                    except Exception:
                        pass
                    raise
            finally:
                try:
                    conn.autocommit = True
                except Exception:
                    pass
                try:
                    conn.close()
                except Exception:
                    pass

        return await asyncio.to_thread(run)

    async def update_table(self, table: str, row_id: int, data: dict) -> bool:
        """Safe generic UPDATE by id."""
        if not data:
            return True
        sets = ", ".join(f"`{k}`=%s" for k in data)
        result = await self.execute(
            f"UPDATE `{table}` SET {sets} WHERE id=%s", (*data.values(), row_id)
        )
        return result >= 0

    # ---------- schema ----------
    def init_db(self) -> None:
        """Deprecated: use SchemaManager.sync() instead."""
        from .schema import SchemaManager

        SchemaManager(self._config).sync()


# Backwards-compatible alias
SCHEMA = ""
