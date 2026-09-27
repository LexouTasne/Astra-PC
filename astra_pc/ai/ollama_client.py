from __future__ import annotations

import base64
import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import Iterable


class OllamaError(RuntimeError):
    pass


class OllamaClient:
    """Small stdlib-only Ollama client used by Astra's local multimodal brain."""

    def __init__(
        self,
        model: str = "qwen3-vl:2b-instruct",
        host: str = "http://127.0.0.1:11434",
        timeout: int = 180,
    ):
        self.model = model
        self.host = host.rstrip("/")
        self.timeout = timeout

    def available(self) -> bool:
        try:
            req = urllib.request.Request(self.host + "/api/tags")
            with urllib.request.urlopen(req, timeout=2) as response:
                return response.status == 200
        except Exception:
            return False

    def models(self) -> list[str]:
        try:
            data = self._request("/api/tags", None, method="GET")
            return [m.get("name", "") for m in data.get("models", [])]
        except Exception:
            return []

    def chat(
        self,
        prompt: str,
        *,
        images: Iterable[str | Path] = (),
        system: str | None = None,
        temperature: float = 0.2,
        num_ctx: int = 8192,
    ) -> str:
        messages: list[dict] = []
        if system:
            messages.append({"role": "system", "content": system})

        user: dict = {"role": "user", "content": prompt}
        encoded = [self._encode_image(Path(p)) for p in images]
        if encoded:
            user["images"] = encoded
        messages.append(user)

        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_ctx": num_ctx,
            },
        }
        data = self._request("/api/chat", payload)
        try:
            return str(data["message"]["content"]).strip()
        except Exception as exc:
            raise OllamaError(f"Unexpected Ollama response: {data!r}") from exc

    def pull(self, model: str | None = None) -> None:
        target = model or self.model
        payload = {"model": target, "stream": False}
        self._request("/api/pull", payload, timeout=3600)

    def _request(
        self,
        path: str,
        payload: dict | None,
        *,
        method: str = "POST",
        timeout: int | None = None,
    ) -> dict:
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self.host + path,
            data=body,
            method=method,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout or self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "ignore")
            raise OllamaError(f"Ollama HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise OllamaError(
                "Ollama is not reachable. Start it with 'ollama serve' or run installer.py."
            ) from exc

    @staticmethod
    def _encode_image(path: Path) -> str:
        if not path.exists():
            raise FileNotFoundError(path)
        return base64.b64encode(path.read_bytes()).decode("ascii")
