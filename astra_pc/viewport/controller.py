from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
import threading

from astra_pc.input.base import InputBackend


class AstraViewport:
    """System-wide viewport controlled by Astra gestures.

    On KDE/Wayland, zoom is handled by KWin's workspace zoom effect rather than
    by the focused app, so it works even when the application has no zoom.
    Rotation targets the primary display through kscreen-doctor.
    """

    def __init__(self, backend: InputBackend | None, cfg: dict | None = None):
        self.backend = backend
        self.cfg = cfg or {}
        self._lock = threading.RLock()
        self._zoom_level = 1.0
        self._zoom_step = max(0.05, float(self.cfg.get("zoom_step", 0.18)))
        self._zoom_min = max(1.0, float(self.cfg.get("zoom_min", 1.0)))
        self._zoom_max = max(self._zoom_min, float(self.cfg.get("zoom_max", 5.0)))
        self._rotation_quadrants = 0
        self._primary_output: str | None = None
        self._zoom_prepared = False

    @property
    def zoom_level(self) -> float:
        return self._zoom_level

    @property
    def rotation_degrees(self) -> int:
        return (self._rotation_quadrants % 4) * 90

    def zoom(self, steps: int) -> bool:
        if not steps or self.backend is None:
            return False
        with self._lock:
            self._ensure_zoom_backend()
            direction = 1 if steps > 0 else -1
            changed = False
            for _ in range(abs(int(steps))):
                next_level = self._zoom_level * (
                    1.0 + self._zoom_step if direction > 0
                    else 1.0 / (1.0 + self._zoom_step)
                )
                next_level = max(self._zoom_min, min(self._zoom_max, next_level))
                if abs(next_level - self._zoom_level) < 1e-4:
                    continue

                # KDE workspace zoom: Meta+= / Meta+-. This is compositor-level,
                # not Ctrl+plus inside the focused application.
                self.backend.hotkey(["win", "+" if direction > 0 else "-"])
                self._zoom_level = next_level
                changed = True
            return changed

    def reset_zoom(self) -> bool:
        if self.backend is None:
            return False
        with self._lock:
            self.backend.hotkey(["win", "0"])
            self._zoom_level = 1.0
            return True

    def rotate(self, steps: int) -> bool:
        if not steps:
            return False
        with self._lock:
            self._rotation_quadrants = (self._rotation_quadrants + int(steps)) % 4
            return self._apply_rotation()

    def reset_rotation(self) -> bool:
        with self._lock:
            self._rotation_quadrants = 0
            return self._apply_rotation()

    def reset(self) -> None:
        try:
            self.reset_zoom()
        except Exception:
            pass
        try:
            self.reset_rotation()
        except Exception:
            pass

    def _ensure_zoom_backend(self) -> None:
        if self._zoom_prepared:
            return
        self._zoom_prepared = True

        if platform.system() != "Linux":
            return
        if shutil.which("kwriteconfig6"):
            try:
                subprocess.run(
                    [
                        "kwriteconfig6",
                        "--file", "kwinrc",
                        "--group", "Plugins",
                        "--key", "zoomEnabled",
                        "true",
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=1.0,
                    check=False,
                )
            except Exception:
                pass
        qdbus = shutil.which("qdbus6") or shutil.which("qdbus")
        if qdbus:
            try:
                subprocess.run(
                    [qdbus, "org.kde.KWin", "/KWin", "reconfigure"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=1.0,
                    check=False,
                )
            except Exception:
                pass

    def _apply_rotation(self) -> bool:
        if platform.system() != "Linux" or not shutil.which("kscreen-doctor"):
            return False

        output = self._primary_output or self._detect_primary_output()
        if not output:
            return False
        self._primary_output = output

        rotation = {
            0: "none",
            1: "right",
            2: "inverted",
            3: "left",
        }[self._rotation_quadrants % 4]
        try:
            p = subprocess.run(
                ["kscreen-doctor", f"output.{output}.rotation.{rotation}"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=2.0,
                check=False,
            )
            return p.returncode == 0
        except Exception:
            return False

    def _detect_primary_output(self) -> str | None:
        if platform.system() != "Linux" or not shutil.which("kscreen-doctor"):
            return None
        try:
            p = subprocess.run(
                ["kscreen-doctor", "-o"],
                capture_output=True,
                text=True,
                timeout=2.0,
                check=False,
            )
        except Exception:
            return None
        if p.returncode != 0:
            return None

        current_id = None
        first_id = None
        for raw in p.stdout.splitlines():
            line = raw.strip()
            m = re.match(r"Output:\s+(\S+)", line)
            if m:
                current_id = m.group(1)
                if first_id is None:
                    first_id = current_id
                continue
            if current_id and re.match(r"priority\s+1\b", line, re.I):
                return current_id
        return first_id
