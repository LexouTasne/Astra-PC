from __future__ import annotations

import os
import platform
import subprocess
import time
from dataclasses import dataclass, asdict
from typing import Any


@dataclass(slots=True)
class DesktopContext:
    ts: float
    os: str
    session: str
    active_window: str
    active_process: str
    cwd: str
    profile: str = "default"

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class ContextEngine:
    """Cheap context refresh. No screenshots or LLM calls are done here."""

    def __init__(self, profile: str = "default"):
        self.profile = profile
        self.current = self.refresh()

    def refresh(self) -> DesktopContext:
        system = platform.system()
        session = "windows"
        if system == "Linux":
            session = "wayland" if os.getenv("WAYLAND_DISPLAY") else "x11"

        title, process = self._active_window()
        self.current = DesktopContext(
            ts=time.time(),
            os=system,
            session=session,
            active_window=title,
            active_process=process,
            cwd=os.getcwd(),
            profile=self.profile,
        )
        return self.current

    def _active_window(self) -> tuple[str, str]:
        system = platform.system()

        if system == "Windows":
            try:
                import ctypes
                from ctypes import wintypes

                user32 = ctypes.windll.user32
                hwnd = user32.GetForegroundWindow()
                length = user32.GetWindowTextLengthW(hwnd)
                buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buf, length + 1)

                pid = wintypes.DWORD()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                return buf.value, str(pid.value)
            except Exception:
                return "", ""

        if system == "Linux":
            if os.getenv("XDG_CURRENT_DESKTOP", "").lower().find("kde") >= 0:
                try:
                    p = subprocess.run(
                        ["qdbus", "org.kde.KWin", "/KWin", "activeWindow"],
                        capture_output=True,
                        text=True,
                        timeout=0.3,
                    )
                    if p.returncode == 0:
                        return p.stdout.strip(), "kwin"
                except Exception:
                    pass

            if os.getenv("DISPLAY"):
                try:
                    wid = subprocess.check_output(
                        ["xdotool", "getactivewindow"],
                        text=True,
                        timeout=0.3,
                    ).strip()
                    title = subprocess.check_output(
                        ["xdotool", "getwindowname", wid],
                        text=True,
                        timeout=0.3,
                    ).strip()
                    pid = subprocess.check_output(
                        ["xdotool", "getwindowpid", wid],
                        text=True,
                        timeout=0.3,
                    ).strip()
                    return title, pid
                except Exception:
                    pass

        return "", ""
