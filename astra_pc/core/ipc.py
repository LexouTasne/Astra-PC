from __future__ import annotations

import json
import socket
from typing import Any


def daemon_request(
    payload: dict[str, Any],
    host: str = "127.0.0.1",
    port: int = 8765,
    timeout: float = 30.0,
) -> dict[str, Any]:
    with socket.create_connection((host, port), timeout=timeout) as sock:
        file = sock.makefile("rwb")
        file.write((json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8"))
        file.flush()
        line = file.readline()
        if not line:
            raise RuntimeError("Astra daemon closed the connection without a response.")
        return json.loads(line.decode("utf-8"))
