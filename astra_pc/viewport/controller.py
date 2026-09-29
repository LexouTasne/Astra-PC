from __future__ import annotations

import platform
import shutil
import subprocess
import threading
import time

from astra_pc.input.base import InputBackend


class AstraViewport:
    """Compositor-wide zoom for Astra gestures.

    KDE/Wayland uses KWin's workspace zoom effect so the gesture acts above
    applications instead of relying on each app's own Ctrl+plus behavior.
    """

    def __init__(self, backend: InputBackend | None, cfg: dict | None = None):
        self.backend = backend
        self.cfg = cfg or {}
        self._lock = threading.RLock()

        self._zoom_level = 1.0
        self._zoom_step = max(0.025, float(self.cfg.get("zoom_step", 0.065)))
        self._zoom_min = max(1.0, float(self.cfg.get("zoom_min", 1.0)))
        self._zoom_max = max(
            self._zoom_min,
            float(self.cfg.get("zoom_max", 6.0)),
        )
        self._zoom_prepared = False
        self._kglobalaccel_zoom = False
        self._qdbus: str | None = None

    @property
    def zoom_level(self) -> float:
        return self._zoom_level

    @property
    def zoom_backend(self) -> str:
        if self._kglobalaccel_zoom:
            return "global"
        if self.backend is not None:
            return "fallback"
        return "unavailable"

    def prepare(self) -> None:
        with self._lock:
            self._qdbus = shutil.which("qdbus6") or shutil.which("qdbus")
            self._ensure_zoom_backend()

    def zoom(self, steps: int) -> bool:
        if not steps:
            return False

        with self._lock:
            self._ensure_zoom_backend()
            direction = 1 if steps > 0 else -1
            changed = False

            for _ in range(abs(int(steps))):
                next_level = self._zoom_level * (
                    1.0 + self._zoom_step
                    if direction > 0
                    else 1.0 / (1.0 + self._zoom_step)
                )
                next_level = max(
                    self._zoom_min,
                    min(self._zoom_max, next_level),
                )
                if abs(next_level - self._zoom_level) < 1e-4:
                    continue

                self._invoke_global_zoom(direction)
                self._zoom_level = next_level
                changed = True

            return changed

    def reset_zoom(self) -> bool:
        with self._lock:
            self._ensure_zoom_backend()
            self._invoke_global_zoom(0)
            self._zoom_level = 1.0
            return True

    def reset(self) -> None:
        try:
            self.reset_zoom()
        except Exception:
            pass

    def _ensure_zoom_backend(self) -> None:
        if self._zoom_prepared:
            return
        self._zoom_prepared = True

        if platform.system() != "Linux":
            return

        kwrite = shutil.which("kwriteconfig6")
        if kwrite:
            try:
                subprocess.run(
                    [
                        kwrite,
                        "--file",
                        "kwinrc",
                        "--group",
                        "Plugins",
                        "--key",
                        "zoomEnabled",
                        "true",
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=1.0,
                    check=False,
                )
                subprocess.run(
                    [
                        kwrite,
                        "--file",
                        "kwinrc",
                        "--group",
                        "Effect-zoom",
                        "--key",
                        "ZoomFactor",
                        str(1.0 + self._zoom_step),
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=1.0,
                    check=False,
                )
            except Exception:
                pass

        qdbus = self._qdbus or shutil.which("qdbus6") or shutil.which("qdbus")
        self._qdbus = qdbus
        if not qdbus:
            return

        try:
            subprocess.run(
                [
                    qdbus,
                    "org.kde.KWin",
                    "/Effects",
                    "org.kde.kwin.Effects.loadEffect",
                    "zoom",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=1.0,
                check=False,
            )
            subprocess.run(
                [qdbus, "org.kde.KWin", "/KWin", "reconfigure"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=1.0,
                check=False,
            )

            for _ in range(5):
                names = self._kwin_shortcut_names()
                if (
                    "view_zoom_in" in names
                    and "view_zoom_out" in names
                ):
                    self._kglobalaccel_zoom = True
                    break
                time.sleep(0.06)
        except Exception:
            self._kglobalaccel_zoom = False

    def _kwin_shortcut_names(self) -> str:
        if not self._qdbus:
            return ""
        try:
            result = subprocess.run(
                [
                    self._qdbus,
                    "org.kde.kglobalaccel",
                    "/component/kwin",
                    "org.kde.kglobalaccel.Component.shortcutNames",
                ],
                capture_output=True,
                text=True,
                timeout=1.0,
                check=False,
            )
            return result.stdout if result.returncode == 0 else ""
        except Exception:
            return ""

    def _invoke_global_zoom(self, direction: int) -> None:
        action = {
            1: "view_zoom_in",
            -1: "view_zoom_out",
            0: "view_actual_size",
        }[1 if direction > 0 else -1 if direction < 0 else 0]

        if self._kglobalaccel_zoom and self._qdbus:
            try:
                subprocess.Popen(
                    [
                        self._qdbus,
                        "org.kde.kglobalaccel",
                        "/component/kwin",
                        "org.kde.kglobalaccel.Component.invokeShortcut",
                        action,
                    ],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
                return
            except Exception:
                self._kglobalaccel_zoom = False

        if self.backend is not None:
            keys = ["win", "0"]
            if direction > 0:
                keys = ["win", "+"]
            elif direction < 0:
                keys = ["win", "-"]
            self.backend.hotkey(keys)

    def close(self) -> None:
        return
