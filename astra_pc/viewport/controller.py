from __future__ import annotations

import platform
import shutil
import subprocess
import threading
import time
from pathlib import Path

from astra_pc.input.base import InputBackend


class AstraViewport:
    """Compositor-wide zoom with a non-blocking, session-owned lifecycle."""

    def __init__(self, backend: InputBackend | None, cfg: dict | None = None):
        self.backend = backend
        self.cfg = cfg or {}
        self._lock = threading.RLock()

        self._zoom_level = 1.0
        self._zoom_step = max(0.025, float(self.cfg.get("zoom_step", 0.075)))
        self._zoom_min = max(1.0, float(self.cfg.get("zoom_min", 1.0)))
        self._zoom_max = max(self._zoom_min, float(self.cfg.get("zoom_max", 6.0)))
        self._zoom_prepared = False
        self._kglobalaccel_zoom = False
        self._qdbus: str | None = None

        # Gesture thread only updates these counters. All KDE/ydotool work runs
        # in one worker so camera tracking can never be blocked by zoom I/O.
        self._zoom_pending = 0
        self._zoom_reset_requested = False
        self._zoom_reset_done = threading.Event()
        self._zoom_reset_done.set()
        self._zoom_wake = threading.Event()
        self._zoom_stop = threading.Event()
        self._zoom_worker = threading.Thread(
            target=self._zoom_loop,
            name="astra-viewport-zoom",
            daemon=True,
        )
        self._zoom_worker.start()

        self._closed = False

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
            self._remove_legacy_rotation_effect()
            self._ensure_zoom_backend()

        # Every gesture session starts from a known 100% zoom.
        self.reset_zoom(wait=True)

    def zoom(self, steps: int) -> bool:
        """Queue zoom without ever touching KDE/input from the camera thread."""
        steps = int(steps)
        if not steps or self._closed:
            return False

        try:
            with self._lock:
                # Clamp the queue: deliberate motion is preserved, jitter or a
                # stalled compositor can never build an unbounded backlog.
                self._zoom_pending = max(
                    -6,
                    min(6, self._zoom_pending + steps),
                )
                self._zoom_wake.set()
            return True
        except Exception as exc:
            print(f"[viewport] zoom queue warning: {exc}", flush=True)
            return False

    def reset_zoom(self, *, wait: bool = False) -> bool:
        """Return the compositor to 100%, optionally waiting for completion."""
        if self._closed and not wait:
            return False

        try:
            with self._lock:
                self._zoom_pending = 0
                self._zoom_reset_requested = True
                self._zoom_reset_done.clear()
                self._zoom_wake.set()

            if wait:
                self._zoom_reset_done.wait(timeout=1.4)
            return True
        except Exception as exc:
            print(f"[viewport] reset warning: {exc}", flush=True)
            return False

    def reset(self) -> None:
        self.reset_zoom(wait=True)

    def _zoom_loop(self) -> None:
        # 20 Hz maximum output rate is far more than enough for smooth KWin
        # zoom and avoids spawning an external process for every camera frame.
        min_interval = 0.05
        last_action = 0.0

        while not self._zoom_stop.is_set():
            self._zoom_wake.wait(0.25)
            self._zoom_wake.clear()
            if self._zoom_stop.is_set():
                break

            while not self._zoom_stop.is_set():
                with self._lock:
                    reset = self._zoom_reset_requested
                    if reset:
                        self._zoom_reset_requested = False
                        self._zoom_pending = 0
                        step = 0
                    elif self._zoom_pending:
                        step = 1 if self._zoom_pending > 0 else -1
                        self._zoom_pending -= step
                    else:
                        break

                elapsed = time.monotonic() - last_action
                if elapsed < min_interval:
                    time.sleep(min_interval - elapsed)

                try:
                    if reset:
                        try:
                            self._apply_zoom_action(0)
                            with self._lock:
                                self._zoom_level = 1.0
                        finally:
                            self._zoom_reset_done.set()
                    else:
                        changed = self._apply_one_zoom_step(step)
                        if not changed:
                            with self._lock:
                                self._zoom_pending = 0
                except Exception as exc:
                    # Zoom must NEVER tear down gestures/camera.
                    print(f"[viewport] zoom worker warning: {exc}", flush=True)
                    with self._lock:
                        self._zoom_pending = 0
                finally:
                    last_action = time.monotonic()

    def _apply_one_zoom_step(self, direction: int) -> bool:
        with self._lock:
            current = self._zoom_level
            next_level = current * (
                1.0 + self._zoom_step
                if direction > 0
                else 1.0 / (1.0 + self._zoom_step)
            )
            next_level = max(self._zoom_min, min(self._zoom_max, next_level))
            if abs(next_level - current) < 1e-4:
                return False

        if not self._apply_zoom_action(direction):
            return False

        with self._lock:
            self._zoom_level = next_level
        return True

    def _apply_zoom_action(self, direction: int) -> bool:
        try:
            self._ensure_zoom_backend()
            action = {
                1: "view_zoom_in",
                -1: "view_zoom_out",
                0: "view_actual_size",
            }[1 if direction > 0 else -1 if direction < 0 else 0]

            if self._kglobalaccel_zoom and self._qdbus:
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
                    timeout=0.7,
                    check=False,
                )
                if result.returncode == 0:
                    return True
                self._kglobalaccel_zoom = False

            if self.backend is not None:
                keys = ["win", "0"]
                if direction > 0:
                    keys = ["win", "+"]
                elif direction < 0:
                    keys = ["win", "-"]
                self.backend.hotkey(keys)
                return True
        except Exception as exc:
            print(f"[viewport] zoom action warning: {exc}", flush=True)
        return False

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
            except Exception as exc:
                print(f"[viewport] KWin config warning: {exc}", flush=True)

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

            names = self._kwin_shortcut_names()
            self._kglobalaccel_zoom = (
                "view_zoom_in" in names
                and "view_zoom_out" in names
                and "view_actual_size" in names
            )
        except Exception as exc:
            self._kglobalaccel_zoom = False
            print(f"[viewport] KGlobalAccel warning: {exc}", flush=True)

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
                timeout=0.8,
                check=False,
            )
            return result.stdout if result.returncode == 0 else ""
        except Exception:
            return ""

    def _remove_legacy_rotation_effect(self) -> None:
        if platform.system() != "Linux":
            return

        effect_id = "astra-rotation"
        qdbus = self._qdbus
        if qdbus:
            try:
                subprocess.run(
                    [
                        qdbus,
                        "org.kde.KWin",
                        "/Effects",
                        "org.kde.kwin.Effects.unloadEffect",
                        effect_id,
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=0.8,
                    check=False,
                )
            except Exception:
                pass

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
                        f"{effect_id}Enabled",
                        "false",
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=0.8,
                    check=False,
                )
            except Exception:
                pass

        try:
            legacy = (
                Path.home()
                / ".local"
                / "share"
                / "kwin"
                / "effects"
                / effect_id
            )
            shutil.rmtree(legacy, ignore_errors=True)
        except Exception:
            pass

    def close(self) -> None:
        if self._closed:
            return

        # Zoom is session-scoped: NEVER leave the desktop magnified after Astra
        # gestures stop, error, or the GUI exits.
        try:
            self.reset_zoom(wait=True)
        except Exception:
            pass

        self._closed = True
        self._zoom_stop.set()
        self._zoom_wake.set()
        if self._zoom_worker.is_alive():
            self._zoom_worker.join(timeout=1.0)
