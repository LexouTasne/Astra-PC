from __future__ import annotations

from pynput.keyboard import Controller as KeyboardController, Key
from pynput.mouse import Button, Controller as MouseController

from .base import InputBackend


class PynputBackend(InputBackend):
    def __init__(self):
        self.mouse = MouseController()
        self.keyboard = KeyboardController()
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

    def move_relative(self, dx: int, dy: int) -> None:
        if dx or dy:
            self.mouse.move(int(dx), int(dy))

    def left_button(self, down: bool) -> None:
        if down == self._left_down:
            return
        (self.mouse.press if down else self.mouse.release)(Button.left)
        self._left_down = down

    def left_click(self) -> None:
        self.mouse.click(Button.left, 1)
        self._left_down = False

    def right_click(self) -> None:
        self.mouse.click(Button.right, 1)

    def scroll(self, amount: int) -> None:
        if amount:
            self.mouse.scroll(0, amount)

    def hotkey(self, keys: list[str]) -> None:
        if not keys:
            return
        mapped = [self._key(k) for k in keys]
        for key in mapped:
            self.keyboard.press(key)
        for key in reversed(mapped):
            self.keyboard.release(key)

    def type_text(self, text: str) -> None:
        self.keyboard.type(text)

    @staticmethod
    def _key(name: str):
        aliases = {
            "ctrl": Key.ctrl,
            "alt": Key.alt,
            "shift": Key.shift,
            "win": Key.cmd,
            "cmd": Key.cmd,
            "tab": Key.tab,
            "enter": Key.enter,
            "esc": Key.esc,
            "space": Key.space,
            "backspace": Key.backspace,
            "delete": Key.delete,
            "up": Key.up,
            "down": Key.down,
            "left": Key.left,
            "right": Key.right,
        }
        return aliases.get(name.lower(), name)
