from __future__ import annotations

import os
import platform
import shutil
import subprocess

from astra_pc.perception.monitors import get_monitors

from .base import Skill, SkillResult


class WindowsSkill(Skill):
    name = "windows"
    description = "Move, snap, maximize and minimize the active desktop window."

    def execute(self, action: str, args: dict) -> SkillResult:
        system = platform.system()
        if system == "Windows":
            return self._windows(action, args)
        if system == "Linux":
            return self._linux(action, args)
        return SkillResult(False, "Window control is unsupported on this OS.")

    def _windows(self, action: str, args: dict) -> SkillResult:
        import ctypes
        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return SkillResult(False, "No active window.")

        if action == "window_maximize":
            user32.ShowWindow(hwnd, 3)
            return SkillResult(True, "Window maximized.")
        if action == "window_minimize":
            user32.ShowWindow(hwnd, 6)
            return SkillResult(True, "Window minimized.")

        monitors = get_monitors()
        if not monitors:
            return SkillResult(False, "Monitor geometry unavailable.")

        target = int(args.get("monitor", 0))
        target = max(0, min(target, len(monitors) - 1))
        m = monitors[target]

        if action == "window_snap_left":
            user32.MoveWindow(hwnd, m.x, m.y, m.width // 2, m.height, True)
            return SkillResult(True, "Window snapped left.")
        if action == "window_snap_right":
            user32.MoveWindow(hwnd, m.x + m.width // 2, m.y, m.width // 2, m.height, True)
            return SkillResult(True, "Window snapped right.")
        if action == "window_move_monitor":
            user32.MoveWindow(hwnd, m.x + 40, m.y + 40, int(m.width * 0.75), int(m.height * 0.75), True)
            return SkillResult(True, f"Window moved to monitor {target}.")

        return SkillResult(False, f"Unknown window action: {action}")

    def _linux(self, action: str, args: dict) -> SkillResult:
        if action in {"window_maximize", "window_minimize"} and shutil.which("xdotool"):
            mode = "windowmaximize" if action == "window_maximize" else "windowminimize"
            p = subprocess.run(
                ["sh", "-lc", f"xdotool getactivewindow {mode}"],
                capture_output=True,
                text=True,
            )
            return SkillResult(p.returncode == 0, action)

        if not shutil.which("wmctrl"):
            return SkillResult(False, "wmctrl is required for Linux window placement.")

        p = subprocess.run(["xdotool", "getactivewindow"], capture_output=True, text=True) if shutil.which("xdotool") else None
        if not p or p.returncode != 0:
            return SkillResult(False, "Could not identify active window.")
        wid = p.stdout.strip()

        monitors = get_monitors()
        if not monitors:
            return SkillResult(False, "Monitor geometry unavailable.")
        target = max(0, min(int(args.get("monitor", 0)), len(monitors) - 1))
        m = monitors[target]

        if action == "window_snap_left":
            geom = f"0,{m.x},{m.y},{m.width // 2},{m.height}"
        elif action == "window_snap_right":
            geom = f"0,{m.x + m.width // 2},{m.y},{m.width // 2},{m.height}"
        elif action == "window_move_monitor":
            geom = f"0,{m.x + 40},{m.y + 40},{int(m.width * 0.75)},{int(m.height * 0.75)}"
        else:
            return SkillResult(False, f"Unknown window action: {action}")

        result = subprocess.run(["wmctrl", "-i", "-r", wid, "-e", geom], capture_output=True, text=True)
        return SkillResult(result.returncode == 0, action)
