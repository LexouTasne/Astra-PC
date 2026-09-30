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
    """Small stdlib-only Ollama client tuned for low latency."""

    def __init__(
        self,
        model: str,
        host: str = "http://127.0.0.1:11434",
        timeout: int = 180,
        keep_alive: str | int | float = -1,
    ):
        self.model = model
        self.host = host.rstrip("/")
        self.timeout = timeout
        self.keep_alive = self._normalize_keep_alive(keep_alive)

    @staticmethod
    def _normalize_keep_alive(value: str | int | float) -> str | int | float:
        """Ollama accepts duration strings (5m) or numeric keep-alive values.

        Older Astra configs stored -1 as the string "-1". Newer Ollama parses
        strings as Go durations, where "-1" is invalid because it has no unit.
        Convert plain numeric strings to JSON numbers while preserving values
        such as "5m", "30s" and "1h".
        """
        if isinstance(value, (int, float)):
            return value
        text = str(value).strip()
        try:
            if text and all(ch in "+-0123456789" for ch in text):
                return int(text)
            if text.count(".") == 1 and all(
                ch in "+-.0123456789" for ch in text
            ):
                return float(text)
        except ValueError:
            pass
        return text or -1

    def available(self) -> bool:
        try:
            with urllib.request.urlopen(self.host + "/api/tags", timeout=2) as response:
                return response.status == 200
        except Exception:
            return False

    def models(self) -> list[str]:
        try:
            data = self._request("/api/tags", None, method="GET")
            return [m.get("name", "") for m in data.get("models", [])]
        except Exception:
            return []

    def preload(self) -> None:
        """Load the model into memory and keep it hot."""
        payload = {
            "model": self.model,
            "prompt": "",
            "stream": False,
            "keep_alive": self.keep_alive,
        }
        self._request("/api/generate", payload, timeout=self.timeout)

    def chat(
        self,
        prompt: str,
        *,
        images: Iterable[str | Path] = (),
        system: str | None = None,
        temperature: float = 0.2,
        num_ctx: int = 4096,
        num_predict: int = 120,
        think: bool | str | None = False,
        format: str | dict | None = None,
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
            "keep_alive": self.keep_alive,
            "options": {
                "temperature": temperature,
                "num_ctx": num_ctx,
                "num_predict": num_predict,
                "top_k": 20,
                "top_p": 0.9,
            },
        }
        if think is not None:
            payload["think"] = think
        if format is not None:
            payload["format"] = format
        data = self._request("/api/chat", payload)
        try:
            return str(data["message"]["content"]).strip()
        except Exception as exc:
            raise OllamaError(f"Unexpected Ollama response: {data!r}") from exc

    def chat_stream(
        self,
        prompt: str,
        *,
        images: Iterable[str | Path] = (),
        system: str | None = None,
        temperature: float = 0.15,
        num_ctx: int = 3072,
        num_predict: int = 96,
        think: bool | str | None = False,
    ):
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
            "stream": True,
            "keep_alive": self.keep_alive,
            "options": {
                "temperature": temperature,
                "num_ctx": num_ctx,
                "num_predict": num_predict,
                "top_k": 20,
                "top_p": 0.9,
            },
        }
        if think is not None:
            payload["think"] = think

        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self.host + "/api/chat",
            data=body,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                for raw in response:
                    if not raw.strip():
                        continue
                    data = json.loads(raw.decode("utf-8"))
                    message = data.get("message") or {}
                    piece = str(message.get("content") or "")
                    if piece:
                        yield piece
                    if data.get("done"):
                        break
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "ignore")
            raise OllamaError(f"Ollama HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise OllamaError(
                "Ollama is not reachable. Start it with 'ollama serve' or run installer.py."
            ) from exc

    def pull(self, model: str | None = None) -> None:
        target = model or self.model
        self._request("/api/pull", {"model": target, "stream": False}, timeout=3600)

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
