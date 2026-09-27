from __future__ import annotations

import time
import webbrowser
from dataclasses import dataclass

from astra_pc.input.factory import create_input_backend


@dataclass(slots=True)
class ToolResult:
    ok: bool
    message: str


class DesktopTools:
    """Small, explicit tool surface for Astra's visual agent."""

    def __init__(self):
        self.backend = create_input_backend()
        self.width, self.height = self.backend.screen_size()

    def execute(self, action: dict) -> ToolResult:
        name = str(action.get("action", "")).lower()

        if name == "click":
            x = int(action.get("x", 0))
            y = int(action.get("y", 0))
            x = min(max(x, 0), self.width - 1)
            y = min(max(y, 0), self.height - 1)
            self.backend.move(x, y)
            self.backend.left_button(True)
            self.backend.left_button(False)
            return ToolResult(True, f"clicked {x},{y}")

        if name == "right_click":
            x = int(action.get("x", 0))
            y = int(action.get("y", 0))
            x = min(max(x, 0), self.width - 1)
            y = min(max(y, 0), self.height - 1)
            self.backend.move(x, y)
            self.backend.right_click()
            return ToolResult(True, f"right-clicked {x},{y}")

        if name == "type":
            value = str(action.get("text", ""))
            self.backend.type_text(value)
            return ToolResult(True, f"typed {len(value)} characters")

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
