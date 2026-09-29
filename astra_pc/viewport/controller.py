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
        self._rotation_scope = str(
            self.cfg.get("rotation_scope", "all")
        ).strip().lower()
        self._primary_output: str | None = None
        self._active_outputs: list[str] = []
        self._zoom_prepared = False
        self._qdbus: str | None = None
        self._kglobalaccel_zoom = False

        self._rotation_pending: int | None = None
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
        return (self._rotation_quadrants % 4) * 90

    def prepare(self) -> None:
        """Warm compositor hooks before the first hand gesture."""
        with self._lock:
            self._ensure_zoom_backend()
            if platform.system() == "Linux" and shutil.which("kscreen-doctor"):
                primary, outputs = self._detect_outputs()
                self._primary_output = primary
                self._active_outputs = outputs

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

                # KWin workspace zoom: call KGlobalAccel directly when
                # available; synthetic Meta shortcuts are only a fallback.
                self._invoke_global_zoom(direction)
                self._zoom_level = next_level
                changed = True
            return changed

    def reset_zoom(self) -> bool:
        if self.backend is None:
            return False
        with self._lock:
            self._invoke_global_zoom(0)
            self._zoom_level = 1.0
            return True

    def rotate(self, steps: int) -> bool:
        if not steps:
            return False
        with self._lock:
            self._rotation_quadrants = (
                self._rotation_quadrants + int(steps)
            ) % 4
            self._rotation_pending = self._rotation_quadrants
            self._rotation_wake.set()
            return True

    def reset_rotation(self) -> bool:
        with self._lock:
            self._rotation_quadrants = 0
            self._rotation_pending = 0
            self._rotation_wake.set()
            return True

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
                subprocess.run(
                    [
                        "kwriteconfig6",
                        "--file", "kwinrc",
                        "--group", "Effect-zoom",
                        "--key", "ZoomFactor",
                        str(1.0 + self._zoom_step),
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=1.0,
                    check=False,
                )
            except Exception:
                pass
        qdbus = shutil.which("qdbus6") or shutil.which("qdbus")
        self._qdbus = qdbus
        if qdbus:
            try:
                subprocess.run(
                    [qdbus, "org.kde.KWin", "/KWin", "reconfigure"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=1.0,
                    check=False,
                )
                names = subprocess.run(
                    [
                        qdbus,
                        "org.kde.kglobalaccel",
                        "/component/kwin",
                        "org.kde.kglobalaccel.Component.shortcutNames",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=1.0,
                    check=False,
                )
                output = names.stdout if names.returncode == 0 else ""
                self._kglobalaccel_zoom = (
                    "view_zoom_in" in output
                    and "view_zoom_out" in output
                )
            except Exception:
                self._kglobalaccel_zoom = False

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

    def _rotation_loop(self) -> None:
        while not self._rotation_stop.is_set():
            self._rotation_wake.wait(0.25)
            self._rotation_wake.clear()
            if self._rotation_stop.is_set():
                return

            with self._lock:
                pending = self._rotation_pending
                self._rotation_pending = None

            if pending is None:
                continue
            self._apply_rotation_value(pending)

    def _apply_rotation(self) -> bool:
        return self._apply_rotation_value(self._rotation_quadrants)

    def _apply_rotation_value(self, quadrant: int) -> bool:
        if platform.system() != "Linux" or not shutil.which("kscreen-doctor"):
            return False

        if not self._active_outputs:
            primary, outputs = self._detect_outputs()
            self._primary_output = primary
            self._active_outputs = outputs

        if self._rotation_scope == "all":
            targets = list(self._active_outputs)
        else:
            targets = [self._primary_output] if self._primary_output else []

        targets = [item for item in targets if item]
        if not targets:
            return False

        rotation = {
            0: "none",
            1: "right",
            2: "inverted",
            3: "left",
        }[int(quadrant) % 4]
        try:
            cmd = ["kscreen-doctor"] + [
                f"output.{output}.rotation.{rotation}"
                for output in targets
            ]
            p = subprocess.run(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=2.0,
                check=False,
            )
            return p.returncode == 0
        except Exception:
            return False

    def close(self) -> None:
        self._rotation_stop.set()
        self._rotation_wake.set()
        if self._rotation_worker.is_alive():
            self._rotation_worker.join(timeout=1.0)


    def _detect_outputs(self) -> tuple[str | None, list[str]]:
        if platform.system() != "Linux" or not shutil.which("kscreen-doctor"):
            return None, []
        try:
            p = subprocess.run(
                ["kscreen-doctor", "-o"],
                capture_output=True,
                text=True,
                timeout=2.0,
                check=False,
            )
        except Exception:
            return None, []
        if p.returncode != 0:
            return None, []

        current_id = None
        first_id = None
        primary = None
        outputs: list[str] = []

        for raw in p.stdout.splitlines():
            line = raw.strip()
            m = re.match(r"Output:\s+(\S+)", line)
            if m:
                current_id = m.group(1)
                if first_id is None:
                    first_id = current_id

                lowered = line.lower()
                if "disabled" not in lowered and current_id not in outputs:
                    outputs.append(current_id)
                if re.search(r"\bpriority\s+1\b", line, re.I):
                    primary = current_id
                continue

            if current_id and re.search(r"\bpriority\s+1\b", line, re.I):
                primary = current_id

        return primary or first_id, outputs

    def _detect_primary_output(self) -> str | None:
        primary, _outputs = self._detect_outputs()
        return primary
