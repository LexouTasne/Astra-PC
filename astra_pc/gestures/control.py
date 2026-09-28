from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

from astra_pc.paths import data_dir


FEATURE_LABELS = {
    "pointer": "cursor por gestos",
    "click": "clique por gestos",
    "right_click": "clique direito por gestos",
    "scroll": "scroll por gestos",
    "swipe": "swipe por gestos",
    "zoom": "zoom por gestos",
    "rotate": "rotação por gestos",
    "pause": "pausa por palma",
    "drag": "arrastar por gestos",
}


class GestureControlState:
    def __init__(self, path: Path | None = None):
        self.path = path or (data_dir() / "gesture-control.json")
        self._mtime = -1.0
        self._cache = {"enabled": True, "overrides": {}}

    def _read(self, force: bool = False) -> dict:
        try:
            mtime = self.path.stat().st_mtime
        except FileNotFoundError:
            self._cache = {"enabled": True, "overrides": {}}
            self._mtime = -1.0
            return dict(self._cache)

        if not force and mtime == self._mtime:
            return {
                "enabled": bool(self._cache.get("enabled", True)),
                "overrides": dict(self._cache.get("overrides", {})),
            }

        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            payload = {}
        overrides = payload.get("overrides", {})
        if not isinstance(overrides, dict):
            overrides = {}
        self._cache = {
            "enabled": bool(payload.get("enabled", True)),
            "overrides": {
                str(k): bool(v)
                for k, v in overrides.items()
                if str(k) in FEATURE_LABELS
            },
        }
        self._mtime = mtime
        return {
            "enabled": self._cache["enabled"],
            "overrides": dict(self._cache["overrides"]),
        }

    def snapshot(self, force: bool = False) -> dict:
        return self._read(force=force)

    def enabled(self) -> bool:
        return bool(self._read().get("enabled", True))

    def feature(self, name: str, default: bool) -> bool:
        state = self._read()
        return bool(state.get("overrides", {}).get(name, default))

    def _write(self, payload: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self._mtime = -1.0
        self._read(force=True)

    def set_enabled(self, value: bool) -> dict:
        state = self._read()
        state["enabled"] = bool(value)
        self._write(state)
        return state

    def set_feature(self, name: str, value: bool) -> dict:
        if name not in FEATURE_LABELS:
            raise ValueError(f"unknown gesture feature: {name}")
        state = self._read()
        overrides = dict(state.get("overrides", {}))
        overrides[name] = bool(value)
        state["overrides"] = overrides
        self._write(state)
        return state


def _norm(text: str) -> str:
    value = unicodedata.normalize("NFKD", text.casefold())
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return " ".join(value.split())


def parse_gesture_control(text: str) -> tuple[str, str | None, bool | None] | None:
    q = _norm(text)
    gesture_words = (
        "gesto", "gestos", "scroll", "rolagem", "air mouse", "cursor",
        "clique", "zoom", "rotacao", "swipe", "arrastar", "drag", "palma",
    )
    if not any(word in q for word in gesture_words):
        return None

    if any(word in q for word in ("status", "quais", "como estao", "como tao", "ligados", "ativos")):
        return ("status", None, None)

    enable = bool(re.search(r"\b(ativa|ativar|ative|liga|ligar|ligue|habilita|habilitar|retoma|retomar)\b", q))
    disable = bool(
        re.search(
            r"\b(desativa|desativar|desative|desliga|desligar|desligue|pausar|bloqueia|bloquear)\b",
            q,
        )
        or re.search(r"^pausa\s+(?:os\s+|o\s+|a\s+)?(?:gestos|controle)", q)
    )
    if enable == disable:
        return None
    value = enable

    if "clique direito" in q:
        return ("feature", "right_click", value)
    if "air mouse" in q or "cursor" in q or "mouse por gesto" in q or "mouse pelos gestos" in q:
        return ("feature", "pointer", value)
    if "scroll" in q or "rolagem" in q:
        return ("feature", "scroll", value)
    if "arrastar" in q or re.search(r"\bdrag\b", q):
        return ("feature", "drag", value)
    if "zoom" in q:
        return ("feature", "zoom", value)
    if "rotacao" in q or "girar" in q:
        return ("feature", "rotate", value)
    if "swipe" in q:
        return ("feature", "swipe", value)
    if "palma" in q or "pausa por gesto" in q:
        return ("feature", "pause", value)
    if "clique" in q:
        return ("feature", "click", value)
    if "gesto" in q or "gestos" in q:
        return ("system", None, value)
    return None


def apply_gesture_control(state: GestureControlState, text: str) -> str | None:
    intent = parse_gesture_control(text)
    if intent is None:
        return None

    kind, feature, value = intent
    if kind == "status":
        snap = state.snapshot(force=True)
        overrides = snap.get("overrides", {})
        parts = ["ligado" if snap.get("enabled", True) else "desligado"]
        for name in ("scroll", "pointer", "click", "right_click", "zoom", "rotate", "swipe", "drag"):
            if name in overrides:
                parts.append(f"{FEATURE_LABELS[name]} {'ligado' if overrides[name] else 'desligado'}")
        return "Gestos: " + "; ".join(parts) + "."

    if kind == "system":
        state.set_enabled(bool(value))
        return "Controle por gestos ativado." if value else "Controle por gestos desativado."

    if kind == "feature" and feature is not None:
        state.set_feature(feature, bool(value))
        label = FEATURE_LABELS[feature]
        return f"{label.capitalize()} {'ativado' if value else 'desativado'}."

    return None
