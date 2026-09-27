from __future__ import annotations

import os
import shutil
import subprocess

from .base import InputBackend


class YdotoolBackend(InputBackend):
    def __init__(self):
        if not shutil.which("ydotool"):
            raise RuntimeError("ydotool is required for native Wayland input")
        self._left_down = False

    def _run(self, *args: str) -> None:
        subprocess.run(["ydotool", *args], check=False,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

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

    def scroll(self, amount: int) -> None:
        if amount:
            self._run("mousewheel", str(amount))
