from __future__ import annotations

import platform
import shutil
import subprocess
import threading
import time
from pathlib import Path

from astra_pc.input.base import InputBackend


class AstraViewport:
    """Compositor-wide zoom and continuous rotation for Astra gestures.

    KDE/Wayland zoom is provided by KWin's workspace zoom effect.
    Continuous rotation is provided by Astra's KWin scripted effect, which
    transforms every EffectWindow and therefore does not depend on app support.
    """

    ROTATION_EFFECT_ID = "astra-rotation"

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

        self._rotation_degrees = 0
        self._rotation_effect_ready = False
        self._rotation_pending = 0
        self._rotation_reset_requested = False

        self._qdbus: str | None = None

        self._rotation_wake = threading.Event()
        self._rotation_stop = threading.Event()
        self._rotation_worker = threading.Thread(
            target=self._rotation_loop,
            name="astra-viewport-rotation",
            daemon=True,
        )
        self._rotation_worker.start()

    @property
    def zoom_level(self) -> float:
        return self._zoom_level

    @property
    def rotation_degrees(self) -> int:
        return self._rotation_degrees % 360

    @property
    def continuous_rotation_ready(self) -> bool:
        return self._rotation_effect_ready

    @property
    def zoom_backend(self) -> str:
        if self._kglobalaccel_zoom:
            return "global"
        if self.backend is not None:
            return "fallback"
        return "unavailable"

    def prepare(self) -> None:
        """Warm compositor hooks before the first hand gesture."""
        with self._lock:
            self._qdbus = shutil.which("qdbus6") or shutil.which("qdbus")
            self._ensure_zoom_backend()
            self._ensure_rotation_backend()

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

    def rotate(self, degrees: int) -> bool:
        """Rotate the visual desktop by signed integer degrees."""
        degrees = int(degrees)
        if not degrees:
            return False

        with self._lock:
            if not self._rotation_effect_ready:
                self._ensure_rotation_backend()
            self._rotation_degrees = (
                self._rotation_degrees + degrees
            ) % 360
            self._rotation_pending += degrees
            # GestureEngine already bounds the per-frame angular delta. Keep
            # the queued sum exact so 359° really means 359°, never 180°.
            self._rotation_wake.set()
            return self._rotation_effect_ready

    def reset_rotation(self) -> bool:
        with self._lock:
            if not self._rotation_effect_ready:
                self._ensure_rotation_backend()
            self._rotation_degrees = 0
            self._rotation_pending = 0
            self._rotation_reset_requested = True
            self._rotation_wake.set()
            return self._rotation_effect_ready

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
            # Force the compositor effect into the current session instead of
            # relying on the next KWin restart.
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

    def _rotation_source_dir(self) -> Path:
        package_root = Path(__file__).resolve().parents[1]
        bundled = (
            package_root
            / "assets"
            / "kwin"
            / self.ROTATION_EFFECT_ID
        )
        if (bundled / "metadata.json").exists():
            return bundled

        # Source-tree compatibility for development checkouts created before
        # the effect became package data.
        return (
            Path(__file__).resolve().parents[2]
            / "packaging"
            / "kwin"
            / self.ROTATION_EFFECT_ID
        )

    def _rotation_target_dir(self) -> Path:
        return (
            Path.home()
            / ".local"
            / "share"
            / "kwin"
            / "effects"
            / self.ROTATION_EFFECT_ID
        )

    def _ensure_rotation_backend(self) -> None:
        if self._rotation_effect_ready:
            return
        if platform.system() != "Linux":
            return

        qdbus = self._qdbus or shutil.which("qdbus6") or shutil.which("qdbus")
        self._qdbus = qdbus
        if not qdbus:
            return

        source = self._rotation_source_dir()
        if not (source / "metadata.json").exists():
            return

        target = self._rotation_target_dir()
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(source, target, dirs_exist_ok=True)
        except Exception:
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
                        f"{self.ROTATION_EFFECT_ID}Enabled",
                        "true",
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=1.0,
                    check=False,
                )
            except Exception:
                pass

        try:
            # Reload on every Astra start so repo updates become active without
            # a logout or KWin restart.
            subprocess.run(
                [
                    qdbus,
                    "org.kde.KWin",
                    "/Effects",
                    "org.kde.kwin.Effects.unloadEffect",
                    self.ROTATION_EFFECT_ID,
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=1.0,
                check=False,
            )
            subprocess.run(
                [
                    qdbus,
                    "org.kde.KWin",
                    "/Effects",
                    "org.kde.kwin.Effects.loadEffect",
                    self.ROTATION_EFFECT_ID,
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=1.0,
                check=False,
            )

            for _ in range(12):
                names = self._kwin_shortcut_names()
                if (
                    "AstraRotatePlus1" in names
                    and "AstraRotateMinus1" in names
                    and "AstraRotateReset" in names
                ):
                    self._rotation_effect_ready = True
                    break
                time.sleep(0.08)

            if self._rotation_effect_ready:
                self._invoke_kwin_shortcut("AstraRotateReset")
                self._rotation_degrees = 0
        except Exception:
            self._rotation_effect_ready = False

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

    def _invoke_kwin_shortcut(self, action: str) -> bool:
        if not self._qdbus:
            return False
        try:
            result = subprocess.run(
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
                timeout=0.8,
                check=False,
            )
            return result.returncode == 0
        except Exception:
            return False

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

    @staticmethod
    def _rotation_actions(delta: int) -> list[str]:
        if not delta:
            return []

        positive = delta > 0
        remaining = abs(int(delta))
        actions: list[str] = []
        for amount in (15, 5, 1):
            count, remaining = divmod(remaining, amount)
            suffix = "Plus" if positive else "Minus"
            actions.extend(
                [f"AstraRotate{suffix}{amount}"] * count
            )
        return actions

    def _rotation_loop(self) -> None:
        while not self._rotation_stop.is_set():
            self._rotation_wake.wait(0.25)
            self._rotation_wake.clear()
            if self._rotation_stop.is_set():
                return

            with self._lock:
                reset = self._rotation_reset_requested
                self._rotation_reset_requested = False
                delta = self._rotation_pending
                self._rotation_pending = 0

            if not self._rotation_effect_ready:
                continue

            if reset:
                self._invoke_kwin_shortcut("AstraRotateReset")
                continue

            for action in self._rotation_actions(delta):
                if self._rotation_stop.is_set():
                    return
                self._invoke_kwin_shortcut(action)

    def close(self) -> None:
        self._rotation_stop.set()
        self._rotation_wake.set()
        if self._rotation_worker.is_alive():
            self._rotation_worker.join(timeout=1.0)
