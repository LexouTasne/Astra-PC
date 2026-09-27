from __future__ import annotations

import json
import os
import time
from pathlib import Path

from pynput import keyboard, mouse


class ActionRecorder:
    """Record local mouse/keyboard activity for explicit 'learn this' sessions."""

    def __init__(self, storage: str | Path | None = None):
        self.storage = Path(storage or (Path.home() / ".local" / "share" / "astra-pc" / "macros")).expanduser()
        self.storage.mkdir(parents=True, exist_ok=True)
        self.events: list[dict] = []
        self._started = 0.0
        self._stop = False

    def record(self, name: str, max_seconds: int = 120) -> Path:
        if os.getenv("WAYLAND_DISPLAY"):
            raise RuntimeError(
                "Global observation is restricted on many Wayland sessions. "
                "Use an X11 session or a compositor-specific capture backend."
            )

        self.events = []
        self._started = time.perf_counter()
        self._stop = False

        def stamp(kind: str, **data):
            self.events.append(
                {
                    "t": round(time.perf_counter() - self._started, 4),
                    "type": kind,
                    **data,
                }
            )

        def on_click(x, y, button, pressed):
            stamp("click", x=int(x), y=int(y), button=str(button), pressed=bool(pressed))

        def on_scroll(x, y, dx, dy):
            stamp("scroll", x=int(x), y=int(y), dx=int(dx), dy=int(dy))

        def on_press(key):
            if key == keyboard.Key.esc:
                self._stop = True
                return False
            stamp("key_down", key=self._key_name(key))

        def on_release(key):
            if key != keyboard.Key.esc:
                stamp("key_up", key=self._key_name(key))

        ml = mouse.Listener(on_click=on_click, on_scroll=on_scroll)
        kl = keyboard.Listener(on_press=on_press, on_release=on_release)
        ml.start()
        kl.start()

        deadline = time.monotonic() + max_seconds
        try:
            while not self._stop and time.monotonic() < deadline:
                time.sleep(0.05)
        finally:
            ml.stop()
            kl.stop()

        path = self.storage / f"{self._safe(name)}.json"
        path.write_text(json.dumps(self.events, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    @staticmethod
    def _key_name(key) -> str:
        try:
            return str(key.char)
        except Exception:
            return str(key).replace("Key.", "")

    @staticmethod
    def _safe(name: str) -> str:
        return "".join(c for c in name.strip().lower().replace(" ", "-") if c.isalnum() or c in "-_") or "macro"
