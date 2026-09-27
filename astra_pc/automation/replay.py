from __future__ import annotations

import json
import os
import time
from pathlib import Path

from pynput import keyboard, mouse


class ActionReplayer:
    def __init__(self):
        self.mouse = mouse.Controller()
        self.keyboard = keyboard.Controller()

    def replay(self, path: str | Path, speed: float = 1.0) -> None:
        if os.getenv("WAYLAND_DISPLAY"):
            raise RuntimeError(
                "Macro replay through pynput is not reliable on native Wayland. "
                "Use X11 or convert the macro to Astra skills."
            )

        events = json.loads(Path(path).read_text(encoding="utf-8"))
        last = 0.0
        for event in events:
            now = float(event.get("t", last))
            delay = max(0.0, (now - last) / max(0.1, speed))
            if delay:
                time.sleep(delay)
            last = now
            self._apply(event)

    def _apply(self, event: dict) -> None:
        kind = event.get("type")
        if kind == "click":
            self.mouse.position = (int(event["x"]), int(event["y"]))
            button = mouse.Button.left if "left" in event.get("button", "") else mouse.Button.right
            if event.get("pressed"):
                self.mouse.press(button)
            else:
                self.mouse.release(button)
        elif kind == "scroll":
            self.mouse.scroll(int(event.get("dx", 0)), int(event.get("dy", 0)))
        elif kind in {"key_down", "key_up"}:
            key = self._key(event.get("key", ""))
            if key is None:
                return
            (self.keyboard.press if kind == "key_down" else self.keyboard.release)(key)

    @staticmethod
    def _key(name: str):
        aliases = {
            "ctrl": keyboard.Key.ctrl,
            "ctrl_l": keyboard.Key.ctrl_l,
            "ctrl_r": keyboard.Key.ctrl_r,
            "alt": keyboard.Key.alt,
            "alt_l": keyboard.Key.alt_l,
            "alt_r": keyboard.Key.alt_r,
            "shift": keyboard.Key.shift,
            "shift_l": keyboard.Key.shift_l,
            "shift_r": keyboard.Key.shift_r,
            "enter": keyboard.Key.enter,
            "tab": keyboard.Key.tab,
            "space": keyboard.Key.space,
            "backspace": keyboard.Key.backspace,
            "esc": keyboard.Key.esc,
        }
        if name in aliases:
            return aliases[name]
        return name if len(name) == 1 else None
