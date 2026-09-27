from __future__ import annotations

import hashlib
import http.client
import hmac
import json
import ssl
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
    """Pinned-TLS client for desktop-to-desktop Mesh operations."""

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

        conn = http.client.HTTPSConnection(
            self.peer.host,
            self.peer.port,
            timeout=self.timeout,
            context=context,
        )
        try:
            conn.connect()
            sock = conn.sock
            if sock is None:
                raise RuntimeError("TLS socket was not created.")
            cert = sock.getpeercert(binary_form=True)
            actual = hashlib.sha256(cert).hexdigest()
            expected = self.peer.fingerprint.lower().replace(":", "")
            if not hmac.compare_digest(actual.lower(), expected):
                raise FingerprintMismatch(
                    f"TLS fingerprint mismatch: expected {expected}, got {actual}"
                )

            body = None
            headers = {"Accept": "application/json"}
            if payload is not None:
                body = json.dumps(payload).encode("utf-8")
                headers["Content-Type"] = "application/json"
            if authenticated and self.peer.token:
                headers["Authorization"] = f"Bearer {self.peer.token}"

            conn.request(method, path, body=body, headers=headers)
            response = conn.getresponse()
            raw = response.read()
            text = raw.decode("utf-8", "replace")
            if response.status >= 400:
                raise RuntimeError(
                    f"Astra Mesh HTTP {response.status}: {text[:1000]}"
                )
            return json.loads(text) if text else {}
        finally:
            conn.close()
