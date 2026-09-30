from __future__ import annotations

import json
import math
import urllib.request


class EmbeddingClient:
    def __init__(
        self,
        model: str = "qwen3-embedding:0.6b",
        host: str = "http://127.0.0.1:11434",
        timeout: int = 60,
        keep_alive: str | int | float = 0,
    ):
        self.model = model
        self.host = host.rstrip("/")
        self.timeout = timeout
        self.keep_alive = keep_alive

    def embed(self, texts: list[str]) -> list[list[float]]:
        payload = json.dumps(
            {"model": self.model, "input": texts, "keep_alive": self.keep_alive}
        ).encode("utf-8")
        req = urllib.request.Request(
            self.host + "/api/embed",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            data = json.loads(r.read().decode("utf-8"))
        return [[float(v) for v in row] for row in data.get("embeddings", [])]

    @staticmethod
    def cosine(a: list[float], b: list[float]) -> float:
        if not a or not b or len(a) != len(b):
            return 0.0
        dot = sum(x * y for x, y in zip(a, b))
        na = math.sqrt(sum(x * x for x in a))
        nb = math.sqrt(sum(y * y for y in b))
        if na == 0.0 or nb == 0.0:
            return 0.0
        return dot / (na * nb)
