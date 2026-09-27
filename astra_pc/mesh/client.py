from __future__ import annotations

import hashlib
import json
import ssl
import urllib.request
import uuid
from dataclasses import dataclass
from typing import Any


class FingerprintMismatch(RuntimeError):
    pass


@dataclass(slots=True)
class MeshPeer:
    host: str
    port: int
    fingerprint: str
    token: str | None = None

    @property
    def base_url(self) -> str:
        return f"https://{self.host}:{self.port}"


class MeshHttpClient:
    """Minimal desktop client for pairing PC-to-PC or testing Android-compatible API."""

    def __init__(self, peer: MeshPeer, timeout: float = 15.0):
        self.peer = peer
        self.timeout = timeout

    def health(self) -> dict:
        return self._request("GET", "/v1/health")

    def pair(
        self,
        code: str,
        *,
        name: str,
        device_id: str | None = None,
        platform: str = "desktop",
    ) -> dict:
        return self._request(
            "POST",
            "/v1/pair",
            {
                "code": code,
                "name": name,
                "device_id": device_id or str(uuid.uuid4()),
                "platform": platform,
            },
            authenticated=False,
        )

    def ask(self, text: str) -> dict:
        return self._request("POST", "/v1/ask", {"text": text})

    def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        *,
        authenticated: bool = True,
    ) -> dict:
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE

        data = None
        headers = {"Content-Type": "application/json"}
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
        if authenticated and self.peer.token:
            headers["Authorization"] = f"Bearer {self.peer.token}"

        request = urllib.request.Request(
            self.peer.base_url + path,
            data=data,
            method=method,
            headers=headers,
        )
        with urllib.request.urlopen(request, timeout=self.timeout, context=context) as response:
            cert = response.fp.raw._sock.getpeercert(binary_form=True)  # type: ignore[attr-defined]
            actual = hashlib.sha256(cert).hexdigest()
            expected = self.peer.fingerprint.lower().replace(":", "")
            if actual.lower() != expected:
                raise FingerprintMismatch(
                    f"TLS fingerprint mismatch: expected {expected}, got {actual}"
                )
            return json.loads(response.read().decode("utf-8"))
