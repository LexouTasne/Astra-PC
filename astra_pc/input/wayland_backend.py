from __future__ import annotations

import os
import shutil
import subprocess

from .base import InputBackend


_KEYCODES = {
    "ctrl": 29,
    "shift": 42,
    "alt": 56,
    "win": 125,
    "tab": 15,
    "enter": 28,
    "esc": 1,
    "space": 57,
    "+": 13,
    "-": 12,
    "[": 26,
    "]": 27,
}


class YdotoolBackend(InputBackend):
    def __init__(self):
        if not shutil.which("ydotool"):
            raise RuntimeError("ydotool is required for native Wayland input")
        self._left_down = False

    def _run(self, *args: str) -> None:
        subprocess.run(
            ["ydotool", *args],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def screen_size(self) -> tuple[int, int]:
        raw = os.getenv("ASTRA_SCREEN_SIZE", "1920x1080").lower().split("x", 1)
        return int(raw[0]), int(raw[1])

    def move(self, x: int, y: int) -> None:
        self._run("mousemove", "--absolute", str(x), str(y))

    def left_button(self, down: bool) -> None:
        if down == self._left_down:
            return
        self._run("click", "0x40" if down else "0x80", "0x110")
        self._left_down = down

    def right_click(self) -> None:
        self._run("click", "0xC1")

    def scroll(self, amount: int) -> None:
        if amount:
            self._run("mousewheel", str(amount))

    def hotkey(self, keys: list[str]) -> None:
        sequence = []
        for key in keys:
            code = _KEYCODES.get(key.lower())
            if code is None:
                return
            sequence.append(f"{code}:1")
        for key in reversed(keys):
            code = _KEYCODES.get(key.lower())
            if code is not None:
                sequence.append(f"{code}:0")
        if sequence:
            self._run("key", *sequence)
