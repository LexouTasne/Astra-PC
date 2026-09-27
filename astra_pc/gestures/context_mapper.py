from __future__ import annotations

import time

from astra_pc.core.context import ContextEngine


class GestureContextMapper:
    """Selects gesture bindings using the active-window title without an LLM."""

    def __init__(self, profiles: dict, refresh_s: float = 0.6):
        self.profiles = profiles
        self.refresh_s = refresh_s
        self.context = ContextEngine()
        self._last = 0.0
        self._title = ""

    def actions(self, defaults: dict) -> dict:
        now = time.monotonic()
        if now - self._last >= self.refresh_s:
            try:
                self._title = self.context.refresh().active_window.lower()
            except Exception:
                self._title = ""
            self._last = now

        merged = dict(defaults)
        for profile in self.profiles.values():
            matches = [str(x).lower() for x in profile.get("match", [])]
            if any(x and x in self._title for x in matches):
                merged.update(profile.get("actions", {}))
                break
        return merged
