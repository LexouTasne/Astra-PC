from __future__ import annotations

import re
import time

from .ollama_client import OllamaClient


class ModelRouter:
    """Routes requests by modality/complexity without loading heavy models unnecessarily."""

    COMPLEX = re.compile(
        r"\b(analisa|analisar|compare|comparar|debug|corrige|corrigir|arquitetura|"
        r"planeje|planejar|refatore|refatorar|explique detalhadamente|reason|analyze)\b",
        re.I,
    )

    def __init__(
        self,
        text: OllamaClient,
        vision: OllamaClient,
        strong: OllamaClient | None = None,
    ):
        self.text = text
        self.vision = vision
        self.strong = strong
        self._model_names: list[str] = []
        self._models_checked_at = 0.0

    def choose(self, prompt: str, *, has_images: bool = False) -> OllamaClient:
        if has_images:
            return self.vision
        if self.strong is not None and self._complex(prompt) and self._installed(self.strong.model):
            return self.strong
        return self.text

    def _installed(self, model: str) -> bool:
        try:
            now = time.monotonic()
            if now - self._models_checked_at > 30.0:
                self._model_names = self.text.models()
                self._models_checked_at = now
            root = model.split(":")[0].lower()
            return any(root in name.lower() for name in self._model_names)
        except Exception:
            return False

    def _complex(self, prompt: str) -> bool:
        return len(prompt) > 650 or bool(self.COMPLEX.search(prompt))
