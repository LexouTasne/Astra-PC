from __future__ import annotations

import time
from pathlib import Path

import cv2

from astra_pc.config import AstraConfig
from astra_pc.gestures.context_mapper import GestureContextMapper
from astra_pc.gestures.engine import GestureEngine
from astra_pc.input.factory import create_input_backend
from astra_pc.perception.monitors import get_monitors
from astra_pc.voice.commands import CommandRouter
from astra_pc.vision.camera_source import open_first_camera


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
    ):
        self.config = config
        self.show_camera = show_camera
        self.dry_run = dry_run
        self.voice_model = voice_model
        self.tutorial = tutorial
        self.air_mouse = bool(air_mouse)
        self.drag = bool(drag)
        self.backend = None if dry_run else create_input_backend()
        self.router = CommandRouter()
        self.voice = None

        pointer = config.section("pointer")
        self.pointer_enabled = bool(
            pointer.get("enabled", False) or self.air_mouse or self.drag
        )
        self.smoothing = float(pointer["smoothing"])
        self.deadzone = float(pointer["deadzone_px"])
        self.margin = float(pointer["active_margin"])
        self._smooth_xy: tuple[float, float] | None = None
        self.actions = config.data.get("actions", {})
        self.context_mapper = GestureContextMapper(
            config.data.get("gesture_profiles", {})
        )
        self.screen_origin = (0, 0)

    def run(self) -> None:
        cam_cfg = self.config.section("camera")
        opened = open_first_camera(
            preferred=int(cam_cfg.get("index", 0)),
            width=int(cam_cfg.get("width", 640)),
            height=int(cam_cfg.get("height", 360)),
            fps=int(cam_cfg.get("target_fps", 30)),
            limit=int(cam_cfg.get("probe_limit", 16)),
        )
        if opened is None:
            raise RuntimeError(
                "camera_unavailable: no camera produced usable frames"
            )

        cap = opened.cap
        print(f"[camera] using index {opened.index}: {opened.source}")

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
            print(f"[input] {detail}")
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
            gestures.set_paused(False)
            self._smooth_xy = None

        self._start_voice_if_requested(gestures)

        print("Astra v0.8 gesture engine online.")
        print("Modo seguro: air-mouse OFF | drag OFF")
        print("Polegar+indicador = clique | indicador+medio = scroll")
        print("Polegar+medio = clique direito | palma aberta = pausar/retomar")
        if self.pointer_enabled:
            print("Air-mouse experimental ATIVO")
        if gesture_cfg.get("drag_enabled"):
            print("Drag experimental ATIVO")
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

                hands = tracker.process(frame)
                if had_hands and not hands and self.backend:
                    self.backend.failsafe_release()
                    self._smooth_xy = None
                had_hands = bool(hands)

                out = gestures.update(hands)
                label = out.label

                if out.pointer is not None and self.pointer_enabled:
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
                    self._dispatch_action("zoom_in" if out.zoom_steps > 0 else "zoom_out")

                if out.rotate_steps:
                    self._dispatch_action("rotate_right" if out.rotate_steps > 0 else "rotate_left")

                if out.swipe:
                    self._dispatch_action(f"swipe_{out.swipe}")

                if self.show_camera:
                    color = (0, 255, 0) if not gestures.paused else (0, 180, 255)
                    cv2.putText(
                        frame,
                        f"ASTRA 0.8 | {label} | {'PAUSED' if gestures.paused else 'ACTIVE'}",
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
            if self.backend:
                self.backend.failsafe_release()
                close = getattr(self.backend, "close", None)
                if callable(close):
                    close()
            tracker.close()
            cap.release()
            cv2.destroyAllWindows()
            print("Astra offline.")

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
