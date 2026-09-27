from __future__ import annotations

import hashlib
import json
import secrets
import threading
import time
from pathlib import Path


DEFAULT_ANDROID_SCOPES = [
    "assistant.ask",
    "context.read",
    "sensor.write",
    "clipboard.push",
    "camera.snapshot",
    "notifications.receive",
]


class DeviceRegistry:
    def __init__(self, path: str | Path):
        self.path = Path(path).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._data = self._load()

    def _load(self) -> dict:
        if not self.path.exists():
            return {"devices": {}}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("devices"), dict):
                return data
        except Exception:
            pass
        return {"devices": {}}

    def _save(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    @staticmethod
    def _hash(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def pair(
        self,
        device_id: str,
        name: str,
        platform: str,
        scopes: list[str] | None = None,
    ) -> tuple[str, dict]:
        token = secrets.token_urlsafe(32)
        now = time.time()
        entry = {
            "device_id": device_id,
            "name": name[:100],
            "platform": platform[:50],
            "scopes": sorted(set(scopes or DEFAULT_ANDROID_SCOPES)),
            "token_hash": self._hash(token),
            "paired_at": now,
            "last_seen": now,
            "revoked": False,
        }
        with self._lock:
            self._data["devices"][device_id] = entry
            self._save()
        public = {k: v for k, v in entry.items() if k != "token_hash"}
        return token, public

    def authenticate(self, token: str) -> dict | None:
        if not token:
            return None
        digest = self._hash(token)
        with self._lock:
            for entry in self._data["devices"].values():
                if entry.get("revoked"):
                    continue
                if secrets.compare_digest(str(entry.get("token_hash", "")), digest):
                    entry["last_seen"] = time.time()
                    self._save()
                    return dict(entry)
        return None

    def has_scope(self, device: dict, scope: str) -> bool:
        return scope in set(device.get("scopes", []))

    def list_public(self) -> list[dict]:
        with self._lock:
            return [
                {k: v for k, v in entry.items() if k != "token_hash"}
                for entry in self._data["devices"].values()
            ]

    def revoke(self, device_id: str) -> bool:
        with self._lock:
            entry = self._data["devices"].get(device_id)
            if not entry:
                return False
            entry["revoked"] = True
            self._save()
            return True
