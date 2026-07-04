"""Native SQLite MCP Server."""
import sqlite3
from pathlib import Path
from typing import Dict, List, Optional
from .base import BaseMCPServer


class SQLiteServer(BaseMCPServer):
    def __init__(self, db_path: str = "./data/unified_context.db", read_only: bool = False):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.read_only = read_only

    def _connect(self):
        uri = f"file:{self.db_path}{'?mode=ro' if self.read_only else ''}"
        return sqlite3.connect(uri, uri=True, check_same_thread=False)

    def query(self, sql: str, params: List = None) -> dict:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.execute(sql, params or [])
            rows = [dict(r) for r in cur.fetchall()]
            return {"rows": rows, "count": len(rows)}

    def execute(self, sql: str, params: List = None) -> dict:
        if self.read_only:
            return {"error": "Database is read-only"}
        with self._connect() as conn:
            cur = conn.execute(sql, params or [])
            conn.commit()
            return {"rowcount": cur.rowcount, "lastrowid": cur.lastrowid}

    def list_tables(self) -> dict:
        result = self.query("SELECT name, type FROM sqlite_master WHERE type IN ('table','view') ORDER BY name")
        return {"tables": [r["name"] for r in result["rows"]], "count": result["count"]}

    def describe_table(self, table: str) -> dict:
        result = self.query(f"PRAGMA table_info({table})")
        return {"table": table, "columns": result["rows"]}

    def insert(self, table: str, data: Dict) -> dict:
        cols = ", ".join(data.keys())
        placeholders = ", ".join("?" * len(data))
        sql = f"INSERT INTO {table} ({cols}) VALUES ({placeholders})"
        return self.execute(sql, list(data.values()))
