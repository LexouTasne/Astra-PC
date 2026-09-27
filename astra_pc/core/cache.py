from __future__ import annotations

import hashlib
import sqlite3
import time
from pathlib import Path


class ResponseCache:
    def __init__(self, path: str | Path, ttl: int = 86400):
        self.path = Path(path).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.ttl = ttl
        self.db = sqlite3.connect(self.path, check_same_thread=False)
        self.db.execute(
            """CREATE TABLE IF NOT EXISTS response_cache(
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                created REAL NOT NULL
            )"""
        )
        self.db.commit()

    @staticmethod
    def key(text: str, profile: str = "") -> str:
        raw = (profile + "\n" + " ".join(text.lower().split())).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()

    def get(self, key: str) -> str | None:
        row = self.db.execute(
            "SELECT value,created FROM response_cache WHERE key=?",
            (key,),
        ).fetchone()
        if not row:
            return None
        if time.time() - float(row[1]) > self.ttl:
            self.db.execute("DELETE FROM response_cache WHERE key=?", (key,))
            self.db.commit()
            return None
        return str(row[0])

    def put(self, key: str, value: str) -> None:
        self.db.execute(
            """INSERT INTO response_cache(key,value,created) VALUES(?,?,?)
               ON CONFLICT(key) DO UPDATE SET value=excluded.value, created=excluded.created""",
            (key, value, time.time()),
        )
        self.db.commit()
