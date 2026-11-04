"""Small idempotent migration helpers for ``maybe_run_migration()`` hooks.

``SchemaManager`` can only create tables and add columns; indexes, type
changes and data back-fills live in plugins and use these helpers. Every
helper is safe to run any number of times and never drops anything.
"""
from __future__ import annotations

import mysql.connector


def connect(db):
    return mysql.connector.connect(**db._config)


def index_exists(cur, table: str, name: str) -> bool:
    cur.execute(
        "SELECT COUNT(*) FROM information_schema.statistics "
        "WHERE table_schema=DATABASE() AND table_name=%s AND index_name=%s",
        (table, name),
    )
    return cur.fetchone()[0] > 0


def column_exists(cur, table: str, column: str) -> bool:
    cur.execute(
        "SELECT COUNT(*) FROM information_schema.columns "
        "WHERE table_schema=DATABASE() AND table_name=%s AND column_name=%s",
        (table, column),
    )
    return cur.fetchone()[0] > 0


def table_exists(cur, table: str) -> bool:
    cur.execute(
        "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name=%s",
        (table,),
    )
    return cur.fetchone()[0] > 0


def ensure_index(cur, table: str, name: str, columns: str, unique: bool = False) -> bool:
    """``columns`` is the raw column list, e.g. ``"status, published_at"``.
    Returns True when the index was created, False if it already existed or
    could not be created (logged, never raised)."""
    if not table_exists(cur, table) or index_exists(cur, table, name):
        return False
    try:
        cur.execute(f"ALTER TABLE `{table}` ADD {'UNIQUE ' if unique else ''}INDEX `{name}` ({columns})")
        print(f"[migrate] added index {table}.{name}")
        return True
    except Exception as e:
        print(f"[migrate] index {table}.{name} skipped: {e}")
        return False


def run(db, fn) -> None:
    """Open a connection, call ``fn(cur)``, commit; swallow+print errors so a
    failed migration never prevents boot (same policy as SchemaManager)."""
    try:
        conn = connect(db)
    except Exception as e:
        print(f"[migrate] connection failed: {e}")
        return
    try:
        cur = conn.cursor()
        fn(cur)
        conn.commit()
    except Exception as e:
        print(f"[migrate] failed: {e}")
    finally:
        conn.close()


def seed_once(cur, flag: str, fn) -> bool:
    """Run ``fn(cur)`` only the first time (tracked by a ``settings`` flag key),
    so seeded defaults are never re-created after an admin deleted them."""
    cur.execute("SELECT 1 FROM settings WHERE `key`=%s", (flag,))
    if cur.fetchone():
        return False
    fn(cur)
    cur.execute(
        "INSERT INTO settings (`key`,`value`) VALUES (%s,'1') ON DUPLICATE KEY UPDATE `value`='1'", (flag,)
    )
    return True
