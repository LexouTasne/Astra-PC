from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any


class SessionMemory:
    """Small local SQLite memory for recent Astra context and routines."""

    def __init__(self, path: str | Path):
        self.path = Path(path).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path, check_same_thread=False)
        self.db.execute(
            """CREATE TABLE IF NOT EXISTS events(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts REAL NOT NULL,
                kind TEXT NOT NULL,
                data TEXT NOT NULL
            )"""
        )
        self.db.execute(
            """CREATE TABLE IF NOT EXISTS kv(
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated REAL NOT NULL
            )"""
        )
        self.db.commit()

    def add(self, kind: str, data: dict[str, Any]) -> None:
        self.db.execute(
            "INSERT INTO events(ts, kind, data) VALUES(?,?,?)",
            (time.time(), kind, json.dumps(data, ensure_ascii=False)),
        )
        self.db.commit()

    def recent(self, limit: int = 20) -> list[dict[str, Any]]:
        rows = self.db.execute(
            "SELECT ts, kind, data FROM events ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        out = []
        for ts, kind, data in reversed(rows):
            try:
                payload = json.loads(data)
            except Exception:
                payload = {"raw": data}
            out.append({"ts": ts, "kind": kind, "data": payload})
        return out

    def set(self, key: str, value: Any) -> None:
        self.db.execute(
            """INSERT INTO kv(key,value,updated) VALUES(?,?,?)
               ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated=excluded.updated""",
            (key, json.dumps(value, ensure_ascii=False), time.time()),
        )
        self.db.commit()

    def get(self, key: str, default: Any = None) -> Any:
        row = self.db.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
        if not row:
            return default
        try:
            return json.loads(row[0])
        except Exception:
            return default
