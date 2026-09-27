from __future__ import annotations

import json
import secrets
import threading
import time
from pathlib import Path


class PairingManager:
    def __init__(self, path: str | Path):
        self.path = Path(path).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def create(self, ttl_seconds: int = 300) -> dict:
        code = f"{secrets.randbelow(1_000_000):06d}"
        data = {
            "code": code,
            "expires_at": time.time() + max(30, ttl_seconds),
            "used": False,
        }
        with self._lock:
            self.path.write_text(json.dumps(data), encoding="utf-8")
        return dict(data)

    def verify(self, code: str) -> bool:
        with self._lock:
            if not self.path.exists():
                return False
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
            except Exception:
                return False
            if data.get("used") or time.time() > float(data.get("expires_at", 0)):
                return False
            if not secrets.compare_digest(str(data.get("code", "")), str(code).strip()):
                return False
            data["used"] = True
            self.path.write_text(json.dumps(data), encoding="utf-8")
            return True
