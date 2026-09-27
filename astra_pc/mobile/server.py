from __future__ import annotations

import json
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


class MobileState:
    def __init__(self):
        self.latest: dict[str, Any] = {}
        self.updated = 0.0
        self.lock = threading.Lock()

    def update(self, payload: dict[str, Any]) -> None:
        with self.lock:
            self.latest = payload
            self.updated = time.time()

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            return {"updated": self.updated, "data": dict(self.latest)}


class MobileCompanionServer:
    """Tiny LAN sensor receiver. Requires a random token for writes."""

    def __init__(self, host: str = "0.0.0.0", port: int = 8766, token: str | None = None):
        self.host = host
        self.port = port
        self.token = token or secrets.token_urlsafe(18)
        self.state = MobileState()
        self.httpd: ThreadingHTTPServer | None = None

    def run(self) -> None:
        state = self.state
        token = self.token

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                if self.path != "/sensor":
                    self.send_error(404)
                    return
                if self.headers.get("X-Astra-Token") != token:
                    self.send_error(403)
                    return
                length = min(int(self.headers.get("Content-Length", "0")), 1_000_000)
                try:
                    payload = json.loads(self.rfile.read(length).decode("utf-8"))
                except Exception:
                    self.send_error(400)
                    return
                state.update(payload if isinstance(payload, dict) else {"value": payload})
                self.send_response(204)
                self.end_headers()

            def do_GET(self):
                if self.path == "/status":
                    body = json.dumps(state.snapshot()).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                self.send_error(404)

            def log_message(self, format, *args):
                return

        self.httpd = ThreadingHTTPServer((self.host, self.port), Handler)
        print(f"Astra mobile bridge listening on {self.host}:{self.port}")
        print("Sensor token:", self.token)
        self.httpd.serve_forever()

    def stop(self) -> None:
        if self.httpd:
            self.httpd.shutdown()
