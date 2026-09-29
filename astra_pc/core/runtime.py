from __future__ import annotations

import time
from pathlib import Path

import cv2

from astra_pc.config import AstraConfig
from astra_pc.gestures.context_mapper import GestureContextMapper
from astra_pc.gestures.control import GestureControlState, apply_gesture_control
from astra_pc.gestures.engine import GestureEngine
from astra_pc.input.factory import create_input_backend
from astra_pc.perception.monitors import get_monitors
from astra_pc.voice.commands import CommandRouter
from astra_pc.viewport.controller import AstraViewport
from astra_pc.vision.camera_source import open_camera_resilient


class AstraRuntime:
    def __init__(
        self,
        config: AstraConfig,
        show_camera: bool = False,
        dry_run: bool = False,
        voice_model: Path | None = None,
        tutorial: bool | None = None,
        air_mouse: bool = False,
        drag: bool = False,
        camera_source: str | int | None = None,
    ):
        self.config = config
        self.show_camera = show_camera
        self.dry_run = dry_run
        self.voice_model = voice_model
        self.tutorial = tutorial
        self.air_mouse = bool(air_mouse)
        self.drag = bool(drag)
        self.camera_source = camera_source
        self.backend = None
        self.router = CommandRouter()
        self.voice = None
        self.viewport = AstraViewport(
            None,
            config.data.get("viewport", {}),
        )

        pointer = config.section("pointer")
        self.pointer_enabled = bool(
            pointer.get("enabled", False) or self.air_mouse or self.drag
        )
        self.smoothing = float(pointer["smoothing"])
        self.deadzone = float(pointer["deadzone_px"])
        self.margin = float(pointer["active_margin"])
        self.air_touch_gain = float(pointer.get("relative_gain", 1.15))
        self.air_touch_deadzone = float(
            pointer.get("relative_deadzone", 0.0028)
        )
        self.air_touch_accel = float(pointer.get("relative_accel", 1.8))
        self.air_touch_max_step = int(
            pointer.get("relative_max_step_px", 82)
        )
        self.air_touch_jump_threshold = float(
            pointer.get("relative_jump_threshold", 0.11)
        )
        self._smooth_xy: tuple[float, float] | None = None
        self._air_touch_last: tuple[float, float] | None = None
        self._air_touch_missing = 0
        self.actions = config.data.get("actions", {})
        self.context_mapper = GestureContextMapper(
            config.data.get("gesture_profiles", {})
        )
        self.gesture_control = GestureControlState()
        self._gesture_system_enabled = True
        self._pointer_control_enabled = self.pointer_enabled
        self._gesture_control_signature = None
        self._next_control_sync = 0.0
        self.screen_origin = (0, 0)

    def _open_input_backend_resilient(self, timeout: float = 6.0):
        if self.dry_run:
            return None

        deadline = time.monotonic() + max(0.0, float(timeout))
        last_error = "input backend unavailable"
        attempt = 0

        while True:
            attempt += 1
            try:
                backend = create_input_backend()
                print(f"[input] AUTO_FOUND attempt={attempt}", flush=True)
                return backend
            except RuntimeError as exc:
                last_error = str(exc)
                if time.monotonic() >= deadline:
                    break
                print(
                    f"[input] waiting for Wayland backend ({attempt}): {last_error}",
                    flush=True,
                )
                time.sleep(0.45)

        raise RuntimeError(f"gesture_input_unavailable: {last_error}")

    def run(self) -> None:
        cam_cfg = self.config.section("camera")
        configured_source = (
            self.camera_source
            if self.camera_source not in (None, "")
            else cam_cfg.get("source")
        )
        opened = open_camera_resilient(
            preferred=int(cam_cfg.get("index", 0)),
            width=int(cam_cfg.get("width", 640)),
            height=int(cam_cfg.get("height", 360)),
            fps=int(cam_cfg.get("target_fps", 30)),
            limit=int(cam_cfg.get("probe_limit", 16)),
            configured_source=configured_source,
            auto_timeout=float(cam_cfg.get("auto_scan_seconds", 10.0)),
            manual_fallback=bool(cam_cfg.get("manual_fallback", True)),
        )
        if opened is None:
            raise RuntimeError(
                "camera_unavailable: no camera produced usable frames"
            )

        cap = opened.cap
        print(f"[camera] using index {opened.index}: {opened.source}")

        self.backend = self._open_input_backend_resilient(
            timeout=float(cam_cfg.get("input_recovery_seconds", 6.0))
        )
        self.viewport.backend = self.backend

        # Load MediaPipe only after a working camera exists. This avoids GPU/TFLite
        # initialization noise and latency when there is no usable video source.
        from astra_pc.vision.hands import HandTracker
        tracker = HandTracker(self.config.section("tracking"))
        gesture_cfg = dict(self.config.section("gestures"))
        gesture_cfg["drag_enabled"] = bool(
            gesture_cfg.get("drag_enabled", False) or self.drag
        )
        gestures = GestureEngine(gesture_cfg)

        monitors = get_monitors()
        if monitors:
            left = min(m.x for m in monitors)
            top = min(m.y for m in monitors)
            right = max(m.x + m.width for m in monitors)
            bottom = max(m.y + m.height for m in monitors)
            self.screen_origin = (left, top)
            screen_w, screen_h = (right - left, bottom - top)
        else:
            screen_w, screen_h = self.backend.screen_size() if self.backend else (1920, 1080)
        if self.backend is not None and hasattr(self.backend, "health"):
            ok_backend, detail = self.backend.health()
            print(f"[input] {detail}", flush=True)
            if not ok_backend:
                raise RuntimeError(f"gesture_input_unavailable: {detail}")

        from astra_pc.gestures.tutorial import (
            run_gesture_tutorial,
            tutorial_completed,
        )
        should_tutorial = (
            self.tutorial is True
            or (self.tutorial is None and not tutorial_completed())
        )
        if should_tutorial:
            completed = run_gesture_tutorial(
                cap,
                tracker,
                gestures,
                mirror=bool(cam_cfg.get("mirror", True)),
                backend=None,
                map_pointer=None,
                screen_w=screen_w,
                screen_h=screen_h,
            )
            if not completed:
                raise RuntimeError("gesture_tutorial_failed")
            # Tutorial consumes camera frames and may leave transient gesture state.
            self._smooth_xy = None

        self._sync_gesture_control(gestures, gesture_cfg, force=True)
        self._next_control_sync = time.monotonic() + 0.12

        # Prepare compositor-level zoom/output detection before the first hand
        # movement so the first pinch has no setup pause.
        try:
            self.viewport.prepare()
        except Exception as exc:
            print(f"[viewport] warmup warning: {exc}", flush=True)

        self._start_voice_if_requested(gestures)

        print(
            f"[viewport] ZOOM_GLOBAL {self.viewport.zoom_backend.upper()}",
            flush=True,
        )
        print(
            "[viewport] ROTATION360 "
            + (
                "READY"
                if self.viewport.continuous_rotation_ready
                else "UNAVAILABLE"
            ),
            flush=True,
        )
        print("[gestures] READY", flush=True)
        print("Astra gesture engine online.")
        print("Gestos: câmera validada, tracking ativo e fail-safe pronto")
        print("Pinça polegar+indicador = zoom global | gire a pinça = rotação 360°")
        print("Indicador+medio = scroll | polegar+medio = clique direito")
        print("Air Touch OFF | Drag OFF")
        print("Ctrl+C sai")

        target_dt = 1.0 / max(1, int(cam_cfg["target_fps"]))
        had_hands = False
        try:
            while True:
                started = time.perf_counter()
                ok, frame = cap.read()
                if not ok:
                    continue

                if bool(cam_cfg.get("mirror", True)):
                    frame = cv2.flip(frame, 1)

                now = time.monotonic()
                if now >= self._next_control_sync:
                    self._sync_gesture_control(gestures, gesture_cfg)
                    self._next_control_sync = now + 0.12

                if self._gesture_system_enabled:
                    hands = tracker.process(frame)
                else:
                    hands = []
                if had_hands and not hands and self.backend:
                    self.backend.failsafe_release()
                    self._smooth_xy = None
                    self._reset_air_touch()
                had_hands = bool(hands)

                out = gestures.update(hands)
                label = out.label

                if (
                    out.pointer is not None
                    and self._pointer_control_enabled
                    and out.label == "pointer"
                ):
                    self._air_touch_missing = 0
                    self._move_air_touch(out.pointer, screen_w, screen_h)
                else:
                    self._air_touch_missing += 1
                    if self._air_touch_missing >= 2:
                        self._reset_air_touch()

                if out.pointer is not None and out.label == "drag":
                    x, y = self._map_pointer(out.pointer, screen_w, screen_h)
                    if self.backend:
                        self.backend.move(x, y)

                if out.left_click and self.backend:
                    self.backend.left_click()

                if out.left_down is not None and self.backend:
                    self.backend.left_button(out.left_down)

                if out.right_click and self.backend:
                    self.backend.right_click()

                if out.scroll and self.backend:
                    self.backend.scroll(out.scroll)

                if out.zoom_steps:
                    self.viewport.zoom(out.zoom_steps)

                if out.rotate_steps:
                    rotate_steps = out.rotate_steps
                    if (
                        bool(cam_cfg.get("mirror", True))
                        and bool(
                            gesture_cfg.get(
                                "rotation_compensate_mirror",
                                True,
                            )
                        )
                    ):
                        rotate_steps = -rotate_steps
                    self.viewport.rotate(rotate_steps)

                if out.swipe:
                    self._dispatch_action(f"swipe_{out.swipe}")

                if self.show_camera:
                    color = (0, 255, 0)
                    cv2.putText(
                        frame,
                        f"ASTRA 0.8 | {label} | {'OFF' if not self._gesture_system_enabled else 'ACTIVE'}",
                        (18, 32),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.7,
                        color,
                        2,
                        cv2.LINE_AA,
                    )
                    for hand in hands:
                        for idx in (0, 4, 8, 12, 16, 20):
                            p = hand[idx]
                            cv2.circle(
                                frame,
                                (int(p.x * frame.shape[1]), int(p.y * frame.shape[0])),
                                5,
                                color,
                                -1,
                                cv2.LINE_AA,
                            )
                    cv2.putText(
                        frame,
                        f"hands: {len(hands)}",
                        (18, 60),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.55,
                        color,
                        1,
                        cv2.LINE_AA,
                    )
                    cv2.imshow("Astra-PC", frame)
                    if cv2.waitKey(1) & 0xFF in (ord("q"), 27):
                        break

                elapsed = time.perf_counter() - started
                if elapsed < target_dt:
                    time.sleep(target_dt - elapsed)
        except KeyboardInterrupt:
            pass
        finally:
            if self.voice:
                self.voice.stop()
            try:
                self.viewport.close()
            except Exception:
                pass
            if self.backend:
                self.backend.failsafe_release()
                close = getattr(self.backend, "close", None)
                if callable(close):
                    close()
            tracker.close()
            cap.release()
            cv2.destroyAllWindows()
            print("Astra offline.")

    def _sync_gesture_control(
        self,
        gestures: GestureEngine,
        gesture_cfg: dict,
        *,
        force: bool = False,
    ) -> None:
        snap = self.gesture_control.snapshot(force=force)
        overrides = dict(snap.get("overrides", {}))
        enabled = bool(snap.get("enabled", True))

        defaults = {
            "pointer": False,
            "click": False,
            "right_click": True,
            "scroll": True,
            "swipe": True,
            "zoom": True,
            "rotate": True,
            "drag": False,
        }
        for name, default in defaults.items():
            gestures.set_feature_enabled(name, bool(overrides.get(name, default)))

        pointer_enabled = False
        signature = (
            enabled,
            tuple(sorted((str(k), bool(v)) for k, v in overrides.items())),
        )
        changed = signature != self._gesture_control_signature

        if changed and self.backend:
            self.backend.failsafe_release()
            self._smooth_xy = None
            self._reset_air_touch()
        if changed:
            feature_text = ", ".join(
                f"{name}={'on' if value else 'off'}"
                for name, value in sorted(overrides.items())
            ) or "defaults"
            print(
                f"[gestures] control: system={'on' if enabled else 'off'} | "
                f"{feature_text}"
            )

        self._gesture_control_signature = signature
        self._gesture_system_enabled = enabled
        self._pointer_control_enabled = enabled and pointer_enabled

    def _dispatch_action(self, name: str) -> None:
        actions = self.context_mapper.actions(self.actions)
        keys = actions.get(name, [])
        if self.dry_run:
            if keys:
                print(f"[gesture] {name}: {'+'.join(keys)}")
            else:
                print(f"[gesture] {name}")
            return
        if self.backend and keys:
            self.backend.hotkey(list(keys))

    def _reset_air_touch(self) -> None:
        self._air_touch_last = None
        self._air_touch_missing = 0

    def _move_air_touch(
        self,
        normalized: tuple[float, float],
        w: int,
        h: int,
    ) -> None:
        if self.backend is None:
            return

        x, y = normalized
        previous = self._air_touch_last
        self._air_touch_last = (x, y)

        # First stable frame is a clutch/re-anchor point. Never teleport the
        # system cursor when the user raises the Air Touch pose.
        if previous is None:
            return

        dx_n = x - previous[0]
        dy_n = y - previous[1]
        motion = (dx_n * dx_n + dy_n * dy_n) ** 0.5

        # Ignore tiny involuntary tremor but still update the anchor above so
        # noise never accumulates into a delayed jump.
        if motion <= self.air_touch_deadzone:
            return

        # Tracking reacquisition occasionally produces one huge landmark jump.
        # Treat that as a fresh anchor rather than a mouse movement.
        if motion >= self.air_touch_jump_threshold:
            return

        # Slow precision near the deadzone, faster travel for deliberate hand
        # motion. This behaves like a touchpad rather than absolute eye/hand aim.
        normalized_speed = min(
            1.0,
            max(
                0.0,
                (motion - self.air_touch_deadzone)
                / max(0.001, 0.035 - self.air_touch_deadzone),
            ),
        )
        gain = self.air_touch_gain * (
            0.55 + self.air_touch_accel * normalized_speed
        )

        dx = int(round(dx_n * w * gain))
        dy = int(round(dy_n * h * gain))
        limit = max(8, self.air_touch_max_step)
        dx = max(-limit, min(limit, dx))
        dy = max(-limit, min(limit, dy))

        if abs(dx) <= 1:
            dx = 0
        if abs(dy) <= 1:
            dy = 0
        if not dx and not dy:
            return

        try:
            self.backend.move_relative(dx, dy)
        except NotImplementedError:
            # Compatibility fallback for third-party backends that only expose
            # absolute motion.
            self._smooth_xy = None
            target_x, target_y = self._map_pointer(normalized, w, h)
            self.backend.move(target_x, target_y)

    def _map_pointer(self, normalized: tuple[float, float], w: int, h: int) -> tuple[int, int]:
        x, y = normalized
        m = self.margin
        x = min(1.0, max(0.0, (x - m) / max(0.01, 1.0 - 2.0 * m)))
        y = min(1.0, max(0.0, (y - m) / max(0.01, 1.0 - 2.0 * m)))
        target = (x * (w - 1), y * (h - 1))

        if self._smooth_xy is None:
            self._smooth_xy = target
        else:
            sx, sy = self._smooth_xy
            a = self.smoothing
            nx = sx + (target[0] - sx) * a
            ny = sy + (target[1] - sy) * a
            if abs(nx - sx) < self.deadzone:
                nx = sx
            if abs(ny - sy) < self.deadzone:
                ny = sy
            self._smooth_xy = (nx, ny)

        ox, oy = self.screen_origin
        return int(self._smooth_xy[0] + ox), int(self._smooth_xy[1] + oy)

    def _start_voice_if_requested(self, gestures: GestureEngine) -> None:
        if self.voice_model is None:
            return

        from astra_pc.voice.vosk_engine import VoskVoiceEngine

        def on_text(text: str) -> None:
            control_message = apply_gesture_control(self.gesture_control, text)
            if control_message:
                print(f"[voice] {control_message}")
                return

            result = self.router.execute(text)
            if result.message == "pause_gestures":
                gestures.set_paused(True)
                print("[voice] gesture control paused")
            elif result.message == "resume_gestures":
                gestures.set_paused(False)
                print("[voice] gesture control resumed")
            else:
                print(f"[voice] {text} -> {result.message}")

        self.voice = VoskVoiceEngine(self.voice_model, on_text)
        self.voice.start()
