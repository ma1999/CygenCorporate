"""Declarative schema manager.

Tables and columns are declared as Python dicts. On startup the manager:
  1. creates the database if missing
  2. creates any missing tables (CREATE TABLE IF NOT EXISTS)
  3. adds any missing columns (ALTER TABLE ... ADD COLUMN)
so the app always boots without schema errors.
"""
import re

import mysql.connector

# ---------------------------------------------------------------------------
# Column definition helpers:  ("INT AUTO_INCREMENT PRIMARY KEY",) or dict form
# A column is:  name -> "SQL type/definition"
# A table is:   name -> {"columns": {...}, "engine": "InnoDB"}
# ---------------------------------------------------------------------------

CORE_TABLES = {
    "users": {
        "columns": {
            "id": "INT AUTO_INCREMENT PRIMARY KEY",
            "username": "VARCHAR(64) UNIQUE NOT NULL",
            "password_hash": "VARCHAR(255) NOT NULL",
            "role": "VARCHAR(32) NOT NULL DEFAULT 'editor'",
            "is_hidden": "TINYINT(1) DEFAULT 0",
            "created_at": "TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
        }
    },
    "roles": {
        "columns": {
            "id": "INT AUTO_INCREMENT PRIMARY KEY",
            "name": "VARCHAR(32) UNIQUE NOT NULL",
            "permissions": "JSON",
        }
    },
    "settings": {
        "columns": {
            "key": "VARCHAR(64) PRIMARY KEY",
            "value": "TEXT",
        }
    },
    "pages": {
        "columns": {
            "id": "INT AUTO_INCREMENT PRIMARY KEY",
            "slug": "VARCHAR(128) UNIQUE NOT NULL",
            "title": "VARCHAR(191)",
            "content": "MEDIUMTEXT",
            "is_default": "TINYINT(1) DEFAULT 0",
            "created_at": "TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
        }
    },
    "plugins": {
        "columns": {
            "id": "INT AUTO_INCREMENT PRIMARY KEY",
            "name": "VARCHAR(64) UNIQUE NOT NULL",
            "enabled": "TINYINT(1) DEFAULT 0",
        }
    },
    # old slugs of renamed entities (redirect support, GET /api/public/redirects)
    "slug_history": {
        "columns": {
            "id": "INT AUTO_INCREMENT PRIMARY KEY",
            "entity_type": "VARCHAR(40) NOT NULL",
            "old_slug": "VARCHAR(191) NOT NULL",
            "entity_id": "INT NOT NULL",
            "created_at": "TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
        }
    },
    # --- example model with default columns: products ---
    "products": {
        "columns": {
            "id": "INT AUTO_INCREMENT PRIMARY KEY",
            "title": "VARCHAR(191) NOT NULL",
            "slug": "VARCHAR(191) UNIQUE",
            "description": "MEDIUMTEXT",
            "price": "DECIMAL(15,2) DEFAULT 0",
            "stock": "INT DEFAULT 0",
            "status": "VARCHAR(20) DEFAULT 'published'",
            "created_at": "TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
        }
    },
    # --- example model: categories ---
    "categories": {
        "columns": {
            "id": "INT AUTO_INCREMENT PRIMARY KEY",
            "title": "VARCHAR(191) NULL DEFAULT NULL",
            "slug": "VARCHAR(191) UNIQUE",
            "parent_id": "INT DEFAULT NULL",
            "created_at": "TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
        }
    },
}


class SchemaManager:
    def __init__(self, config: dict):
        self._config = dict(config)
        self.tables: dict = {name: dict(spec) for name, spec in CORE_TABLES.items()}

    # ---------- registration API (used by models & plugins) ----------
    def register_table(self, name: str, columns: dict):
        """Register/merge a table definition. Plugins call this to add tables."""
        spec = self.tables.setdefault(name, {"columns": {}})
        spec["columns"].update(columns)

    def register_columns(self, table: str, columns: dict):
        """Register extra columns on an existing table. Plugins call this to
        add their own columns (name -> SQL definition)."""
        self.tables.setdefault(table, {"columns": {}})["columns"].update(columns)

    # ---------- sync ----------
    def _connect_no_db(self):
        cfg = dict(self._config)
        cfg.pop("database", None)
        return mysql.connector.connect(**cfg)

    def sync(self) -> None:
        """Create DB/tables/columns as needed. Never raises."""
        try:
            self._ensure_database()
            self._sync_tables()
            print("[Schema] synchronized OK")
        except Exception as e:
            print(f"[Schema] sync skipped/failed: {e}")

    def _ensure_database(self):
        conn = self._connect_no_db()
        try:
            cur = conn.cursor()
            db = self._config["database"]
            cur.execute(
                f"CREATE DATABASE IF NOT EXISTS `{db}` "
                "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            )
            conn.commit()
        finally:
            conn.close()

    def _sync_tables(self):
        conn = mysql.connector.connect(**self._config)
        try:
            cur = conn.cursor()
            for table, spec in self.tables.items():
                cols = spec["columns"]
                if not self._table_exists(cur, table):
                    col_sql = ",\n    ".join(
                        f"`{c}` {d}" if c != "key" else f"`key` {d}" for c, d in cols.items()
                    )
                    cur.execute(
                        f"CREATE TABLE IF NOT EXISTS `{table}` (\n    {col_sql}\n) "
                        "ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci"
                    )
                    print(f"[Schema] created table `{table}`")
                else:
                    existing = self._existing_columns(cur, table)
                    for col, definition in cols.items():
                        if col.lower() not in existing:
                            cur.execute(f"ALTER TABLE `{table}` ADD COLUMN `{col}` {definition}")
                            print(f"[Schema] added column `{table}.{col}`")
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def _table_exists(cur, table: str) -> bool:
        cur.execute(
            "SELECT COUNT(*) FROM information_schema.tables "
            "WHERE table_schema=DATABASE() AND table_name=%s",
            (table,),
        )
        return cur.fetchone()[0] > 0

    @staticmethod
    def _existing_columns(cur, table: str) -> set:
        cur.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema=DATABASE() AND table_name=%s",
            (table,),
        )
        return {row[0].lower() for row in cur.fetchall()}
