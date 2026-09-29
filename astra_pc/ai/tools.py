from __future__ import annotations

import time
import webbrowser
from dataclasses import dataclass

from astra_pc.input.factory import create_input_backend
from astra_pc.perception.monitors import get_monitors, virtual_bounds


@dataclass(slots=True)
class ToolResult:
    ok: bool
    message: str


class DesktopTools:
    """Small, explicit tool surface for Astra's visual agent."""

    def __init__(self):
        self.backend = create_input_backend()
        self.monitors = get_monitors()
        x, y, width, height = virtual_bounds(self.monitors)
        if width > 0 and height > 0:
            self.origin_x, self.origin_y = x, y
            self.width, self.height = width, height
        else:
            self.origin_x = self.origin_y = 0
            self.width, self.height = self.backend.screen_size()

    def desktop_geometry(self) -> dict:
        return {
            "origin_x": self.origin_x,
            "origin_y": self.origin_y,
            "width": self.width,
            "height": self.height,
            "monitors": [m.as_dict() for m in self.monitors],
        }

    def _screen_to_desktop(self, x: int, y: int) -> tuple[int, int]:
        sx = min(max(int(x), 0), self.width - 1)
        sy = min(max(int(y), 0), self.height - 1)
        return self.origin_x + sx, self.origin_y + sy

    def release_all(self) -> None:
        try:
            self.backend.failsafe_release()
        except Exception:
            pass

    def execute(self, action: dict) -> ToolResult:
        name = str(action.get("action", "")).lower()

        if name == "move":
            sx = int(action.get("x", 0))
            sy = int(action.get("y", 0))
            x, y = self._screen_to_desktop(sx, sy)
            self.backend.move(x, y)
            return ToolResult(True, f"moved screenshot {sx},{sy} -> desktop {x},{y}")

        if name == "click":
            sx = int(action.get("x", 0))
            sy = int(action.get("y", 0))
            x, y = self._screen_to_desktop(sx, sy)
            self.backend.move(x, y)
            self.backend.left_click()
            return ToolResult(True, f"clicked screenshot {sx},{sy} -> desktop {x},{y}")

        if name == "right_click":
            sx = int(action.get("x", 0))
            sy = int(action.get("y", 0))
            x, y = self._screen_to_desktop(sx, sy)
            self.backend.move(x, y)
            self.backend.right_click()
            return ToolResult(True, f"right-clicked screenshot {sx},{sy} -> desktop {x},{y}")

        if name == "type":
            value = str(action.get("text", ""))
            self.backend.type_text(value)
            return ToolResult(True, f"typed {len(value)} characters")

        if name == "key_down":
            key = str(action.get("key", "")).strip().lower()
            if not key:
                return ToolResult(False, "missing key")
            self.backend.key_down(key)
            return ToolResult(True, f"key down: {key}")

        if name == "key_up":
            key = str(action.get("key", "")).strip().lower()
            if not key:
                return ToolResult(False, "missing key")
            self.backend.key_up(key)
            return ToolResult(True, f"key up: {key}")

        if name == "hotkey":
            keys = action.get("keys", [])
            if not isinstance(keys, list) or not keys:
                return ToolResult(False, "invalid hotkey")
            allowed = {
                "ctrl", "alt", "shift", "win", "cmd", "tab", "enter", "esc",
                "space", "backspace", "delete", "up", "down", "left", "right",
                "a", "c", "v", "x", "f", "l", "t", "w", "+", "-", "[", "]",
            }
            keys = [str(k).lower() for k in keys]
            if any(k not in allowed for k in keys):
                return ToolResult(False, "hotkey contains a key outside Astra's allowlist")
            self.backend.hotkey(keys)
            return ToolResult(True, "hotkey " + "+".join(keys))

        if name == "scroll":
            amount = int(action.get("amount", 0))
            amount = max(-12, min(12, amount))
            self.backend.scroll(amount)
            return ToolResult(True, f"scrolled {amount}")

        if name == "open_url":
            url = str(action.get("url", ""))
            if not url.startswith(("https://", "http://")):
                return ToolResult(False, "only http/https URLs are allowed")
            webbrowser.open(url)
            return ToolResult(True, f"opened {url}")

        if name == "wait":
            seconds = max(0.0, min(5.0, float(action.get("seconds", 1.0))))
            time.sleep(seconds)
            return ToolResult(True, f"waited {seconds:.1f}s")

        if name == "done":
            return ToolResult(True, str(action.get("message", "done")))

        return ToolResult(False, f"unknown action: {name}")
