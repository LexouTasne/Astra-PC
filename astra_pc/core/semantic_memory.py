from __future__ import annotations

import json
import re
import sqlite3
import time
from pathlib import Path
from typing import Any

from astra_pc.ai.embeddings import EmbeddingClient


class SemanticMemory:
    """Local semantic memory with Ollama embeddings and lexical fallback."""

    def __init__(
        self,
        path: str | Path,
        embeddings: EmbeddingClient | None = None,
        max_scan: int = 1200,
    ):
        self.path = Path(path).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path, check_same_thread=False)
        self.embeddings = embeddings
        self.max_scan = max_scan
        self.db.execute(
            """CREATE TABLE IF NOT EXISTS semantic_memories(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts REAL NOT NULL,
                kind TEXT NOT NULL,
                text TEXT NOT NULL,
                metadata TEXT NOT NULL,
                embedding TEXT
            )"""
        )
        self.db.commit()

    def remember(
        self,
        text: str,
        *,
        kind: str = "memory",
        metadata: dict[str, Any] | None = None,
    ) -> int:
        text = text.strip()
        if not text:
            return -1
        vector = None
        if self.embeddings is not None:
            try:
                rows = self.embeddings.embed([text])
                if rows:
                    vector = json.dumps(rows[0])
            except Exception:
                vector = None
        cur = self.db.execute(
            """INSERT INTO semantic_memories(ts,kind,text,metadata,embedding)
               VALUES(?,?,?,?,?)""",
            (
                time.time(),
                kind,
                text,
                json.dumps(metadata or {}, ensure_ascii=False),
                vector,
            ),
        )
        self.db.commit()
        return int(cur.lastrowid)

    def search(self, query: str, limit: int = 6) -> list[dict[str, Any]]:
        rows = self.db.execute(
            """SELECT id,ts,kind,text,metadata,embedding
               FROM semantic_memories
               ORDER BY id DESC LIMIT ?""",
            (self.max_scan,),
        ).fetchall()
        if not rows:
            return []

        query_vec = None
        if self.embeddings is not None:
            try:
                vectors = self.embeddings.embed([query])
                query_vec = vectors[0] if vectors else None
            except Exception:
                query_vec = None

        qtokens = self._tokens(query)
        scored = []
        for mid, ts, kind, text, metadata, embedding in rows:
            semantic = 0.0
            if query_vec is not None and embedding:
                try:
                    semantic = EmbeddingClient.cosine(
                        query_vec,
                        [float(x) for x in json.loads(embedding)],
                    )
                except Exception:
                    semantic = 0.0

            ttokens = self._tokens(text)
            lexical = (
                len(qtokens & ttokens) / max(1, len(qtokens | ttokens))
                if qtokens else 0.0
            )
            score = semantic if query_vec is not None else lexical
            if query_vec is not None:
                score = semantic * 0.88 + lexical * 0.12
            if score <= 0:
                continue
            try:
                meta = json.loads(metadata)
            except Exception:
                meta = {}
            scored.append(
                {
                    "id": mid,
                    "ts": ts,
                    "kind": kind,
                    "text": text,
                    "metadata": meta,
                    "score": round(score, 4),
                }
            )

        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:limit]

    @staticmethod
    def _tokens(text: str) -> set[str]:
        return {
            x for x in re.findall(r"[\wÀ-ÿ]{2,}", text.lower())
            if x not in {"de", "da", "do", "e", "a", "o", "um", "uma", "the", "and"}
        }
