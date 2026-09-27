from __future__ import annotations

from pynput.mouse import Button, Controller

from .base import InputBackend


class PynputBackend(InputBackend):
    def __init__(self):
        self.mouse = Controller()
        self._left_down = False

    def screen_size(self) -> tuple[int, int]:
        try:
            import tkinter as tk
            root = tk.Tk()
            root.withdraw()
            size = (root.winfo_screenwidth(), root.winfo_screenheight())
            root.destroy()
            return size
        except Exception:
            return (1920, 1080)

    def move(self, x: int, y: int) -> None:
        self.mouse.position = (x, y)

    def left_button(self, down: bool) -> None:
        if down == self._left_down:
            return
        (self.mouse.press if down else self.mouse.release)(Button.left)
        self._left_down = down

    def scroll(self, amount: int) -> None:
        if amount:
            self.mouse.scroll(0, amount)
