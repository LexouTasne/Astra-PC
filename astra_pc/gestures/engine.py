from __future__ import annotations

import collections
import math
import time
from dataclasses import dataclass

from astra_pc.vision.types import Hand, Point


@dataclass(slots=True)
class GestureOutput:
    pointer: tuple[float, float] | None = None
    left_down: bool | None = None
    left_click: bool = False
    right_click: bool = False
    scroll: int = 0
    zoom_steps: int = 0
    rotate_steps: int = 0
    swipe: str | None = None
    toggle_pause: bool = False
    label: str = "idle"


def _dist(a: Point, b: Point) -> float:
    return math.hypot(a.x - b.x, a.y - b.y)


def _finger_extended(hand: Hand, tip: int, pip: int) -> bool:
    """Rotation-tolerant finger extension test.

    Comparing distance from the wrist works when the hand is tilted/rotated,
    unlike a pure tip.y < pip.y check.
    """
    wrist = hand[0]
    tip_d = _dist(wrist, hand[tip])
    pip_d = _dist(wrist, hand[pip])
    return tip_d > pip_d * 1.10 + 0.004


def _center(hand: Hand) -> tuple[float, float]:
    ids = (0, 5, 9, 13, 17)
    return (
        sum(hand[i].x for i in ids) / len(ids),
        sum(hand[i].y for i in ids) / len(ids),
    )


def _open_palm(hand: Hand) -> bool:
    return all(
        _finger_extended(hand, tip, pip)
        for tip, pip in ((8, 6), (12, 10), (16, 14), (20, 18))
    )


class GestureEngine:
    """Deterministic gesture state machine with jitter-resistant motion gestures."""

    FEATURE_DEFAULTS = {
        "pointer": True,
        "click": True,
        "right_click": True,
        "scroll": True,
        "swipe": True,
        "zoom": True,
        "rotate": True,
        "pause": True,
        "drag": False,
    }

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self._features = dict(self.FEATURE_DEFAULTS)
        self._features["drag"] = bool(cfg.get("drag_enabled", False))

        self._pinching = False
        self._pinch_started = 0.0
        self._dragging = False
        self._paused = False

        self._last_pause_toggle = 0.0
        self._palm_started: float | None = None
        self._palm_latched = False

        self._right_latched = False

        self._scroll_filtered_y: float | None = None
        self._scroll_last_y: float | None = None
        self._scroll_accum = 0.0
        self._scroll_direction = 0

        self._two_hand_distance: float | None = None
        self._two_hand_angle: float | None = None

        self._swipe_history: collections.deque[tuple[float, float]] = collections.deque(maxlen=16)
        self._last_swipe_fire = 0.0

    @property
    def paused(self) -> bool:
        return self._paused

    def feature_enabled(self, name: str) -> bool:
        return bool(self._features.get(name, True))

    def set_feature_enabled(self, name: str, value: bool) -> None:
        if name not in self.FEATURE_DEFAULTS:
            return
        self._features[name] = bool(value)
        if name == "drag" and not value and self._dragging:
            self._dragging = False
        if name == "scroll" and not value:
            self._reset_scroll()
        if name == "swipe" and not value:
            self._swipe_history.clear()
        if name in {"zoom", "rotate"} and not value:
            self._reset_two_hand()

    def set_paused(self, value: bool) -> None:
        self._paused = bool(value)
        self._reset_transient()

    def reset_tracking(self) -> None:
        self._palm_started = None
        self._palm_latched = False
        self._right_latched = False
        self._reset_transient()
        self._reset_two_hand()

    def update(self, hands: list[Hand]) -> GestureOutput:
        if not hands:
            was_dragging = self._dragging
            self._palm_started = None
            self._palm_latched = False
            self._right_latched = False
            self._reset_transient()
            return GestureOutput(
                left_down=False if was_dragging else None,
                label="no-hand",
            )

        if len(hands) >= 2:
            out = self._update_two_hands(hands[0], hands[1])
            if out.label != "idle":
                return out
            self._reset_two_hand()
        else:
            self._reset_two_hand()

        return self._update_one_hand(hands[0])

    def _update_one_hand(self, hand: Hand) -> GestureOutput:
        now = time.monotonic()
        thumb, index, middle = hand[4], hand[8], hand[12]

        index_up = _finger_extended(hand, 8, 6)
        middle_up = _finger_extended(hand, 12, 10)
        ring_up = _finger_extended(hand, 16, 14)
        pinky_up = _finger_extended(hand, 20, 18)

        open_palm = index_up and middle_up and ring_up and pinky_up
        pause_hold = float(self.cfg.get("pause_hold_ms", 420)) / 1000.0
        if self.feature_enabled("pause") and open_palm:
            if self._palm_started is None:
                self._palm_started = now
            if not self._palm_latched and now - self._palm_started >= pause_hold:
                cooldown = float(self.cfg.get("pause_cooldown_ms", 900)) / 1000.0
                if now - self._last_pause_toggle >= cooldown:
                    self._palm_latched = True
                    self._paused = not self._paused
                    self._last_pause_toggle = now
                    self._reset_transient(keep_palm=True)
                    return GestureOutput(
                        toggle_pause=True,
                        left_down=False,
                        label="paused" if self._paused else "resumed",
                    )
        else:
            self._palm_started = None
            self._palm_latched = False

        if self._paused:
            return GestureOutput(label="paused")

        # Right click: thumb + middle pinch, separated from the left-click pinch.
        right_distance = _dist(thumb, middle)
        right_on = right_distance <= float(self.cfg.get("right_pinch_threshold", 0.05))
        index_separate = _dist(thumb, index) > float(
            self.cfg.get("click_release_threshold", 0.065)
        )
        if self.feature_enabled("right_click"):
            if right_on and not self._right_latched and index_separate:
                self._right_latched = True
                return GestureOutput(right_click=True, label="right-click")
            if not right_on:
                self._right_latched = False
        else:
            self._right_latched = False

        pinch = _dist(thumb, index)
        pinch_on = pinch <= float(self.cfg.get("pinch_threshold", 0.045))
        pinch_off = pinch >= float(self.cfg.get("click_release_threshold", 0.065))
        out = GestureOutput()

        pointer_pose = index_up and not middle_up and not ring_up and not pinky_up
        if pointer_pose and self.feature_enabled("pointer"):
            out.pointer = (index.x, index.y)
            out.label = "pointer"

        if self.feature_enabled("click") and pinch_on and not self._pinching:
            self._pinching = True
            self._pinch_started = now
            out.label = "pinch"

        if self._pinching:
            hold_ms = (now - self._pinch_started) * 1000.0
            drag_enabled = self.feature_enabled("drag")
            if drag_enabled and hold_ms >= float(self.cfg.get("drag_hold_ms", 350)):
                if not self._dragging:
                    out.left_down = True
                self._dragging = True
                out.pointer = (index.x, index.y)
                out.label = "drag"

            if pinch_off:
                if self._dragging:
                    out.left_down = False
                    out.label = "drop"
                else:
                    out.left_click = True
                    out.label = "click"
                self._pinching = False
                self._dragging = False

        scrolling = (
            self.feature_enabled("scroll")
            and index_up
            and middle_up
            and not ring_up
            and not pinky_up
            and not self._pinching
        )
        if scrolling:
            self._apply_scroll(hand, out)
        else:
            self._reset_scroll()

        swipe_pose = (
            self.feature_enabled("swipe")
            and index_up
            and middle_up
            and ring_up
            and not pinky_up
            and not self._pinching
        )
        if swipe_pose:
            self._apply_swipe(hand, out, now)
        else:
            self._swipe_history.clear()

        return out

    def _apply_scroll(self, hand: Hand, out: GestureOutput) -> None:
        # Use fingertips + MCPs so bending one finger does not flip direction.
        raw_y = (hand[5].y + hand[9].y + hand[8].y + hand[12].y) * 0.25
        alpha = min(1.0, max(0.05, float(self.cfg.get("scroll_smoothing", 0.45))))
        deadzone = max(0.0005, float(self.cfg.get("scroll_deadzone", 0.0025)))
        gain = max(1.0, float(self.cfg.get("scroll_gain", 45.0)))
        max_step = max(1, int(self.cfg.get("scroll_max_step", 4)))

        if self._scroll_filtered_y is None:
            self._scroll_filtered_y = raw_y
            self._scroll_last_y = raw_y
            self._scroll_accum = 0.0
            self._scroll_direction = 0
            out.label = "scroll-ready"
            return

        filtered = self._scroll_filtered_y + (raw_y - self._scroll_filtered_y) * alpha
        previous = self._scroll_last_y if self._scroll_last_y is not None else filtered
        delta = previous - filtered
        self._scroll_filtered_y = filtered
        self._scroll_last_y = filtered

        if abs(delta) < deadzone:
            out.label = "scroll-ready"
            return

        direction = 1 if delta > 0 else -1
        if self._scroll_direction and direction != self._scroll_direction:
            # Do not let accumulated jitter from the old direction leak into
            # the first real movement after the user reverses direction.
            self._scroll_accum = 0.0
        self._scroll_direction = direction
        self._scroll_accum += delta * gain

        if abs(self._scroll_accum) < 1.0:
            out.label = "scroll-up-ready" if direction > 0 else "scroll-down-ready"
            return

        steps = math.trunc(self._scroll_accum)
        steps = max(-max_step, min(max_step, steps))
        self._scroll_accum -= steps
        out.scroll = steps
        out.label = "scroll-up" if steps > 0 else "scroll-down"

    def _apply_swipe(self, hand: Hand, out: GestureOutput, now: float) -> None:
        cx, _ = _center(hand)
        self._swipe_history.append((now, cx))

        window = float(self.cfg.get("swipe_window_ms", 280)) / 1000.0
        while self._swipe_history and now - self._swipe_history[0][0] > window:
            self._swipe_history.popleft()
        if len(self._swipe_history) < 3:
            return

        t0, x0 = self._swipe_history[0]
        dt = max(1e-4, now - t0)
        dx = cx - x0
        velocity = dx / dt
        min_distance = float(self.cfg.get("swipe_distance", 0.11))
        min_velocity = float(self.cfg.get("swipe_velocity", 0.6))
        cooldown = float(self.cfg.get("swipe_cooldown_ms", 700)) / 1000.0

        if (
            abs(dx) >= min_distance
            and abs(velocity) >= min_velocity
            and now - self._last_swipe_fire >= cooldown
        ):
            out.swipe = "right" if dx > 0 else "left"
            out.label = f"swipe-{out.swipe}"
            self._last_swipe_fire = now
            self._swipe_history.clear()

    def _update_two_hands(self, a: Hand, b: Hand) -> GestureOutput:
        if self._paused:
            return GestureOutput(label="paused")

        # Two-hand transforms require two open hands. Accidental second-hand
        # detections no longer steal pointer/click gestures.
        if not (_open_palm(a) and _open_palm(b)):
            return GestureOutput(label="idle")

        ac = _center(a)
        bc = _center(b)
        dx = bc[0] - ac[0]
        dy = bc[1] - ac[1]
        distance = math.hypot(dx, dy)
        angle = math.degrees(math.atan2(dy, dx))
        out = GestureOutput(label="two-hand-ready")

        if self._two_hand_distance is None:
            self._two_hand_distance = distance
        if self._two_hand_angle is None:
            self._two_hand_angle = angle

        distance_delta = distance - self._two_hand_distance
        angle_delta = angle - self._two_hand_angle
        while angle_delta > 180:
            angle_delta -= 360
        while angle_delta < -180:
            angle_delta += 360

        zoom_threshold = max(0.001, float(self.cfg.get("two_hand_zoom_threshold", 0.035)))
        rotate_threshold = max(1.0, float(self.cfg.get("two_hand_rotate_threshold_deg", 10.0)))
        zoom_score = (
            abs(distance_delta) / zoom_threshold if self.feature_enabled("zoom") else 0.0
        )
        rotate_score = (
            abs(angle_delta) / rotate_threshold if self.feature_enabled("rotate") else 0.0
        )

        # Choose the dominant transform so zoom and rotate never fire together.
        if zoom_score >= 1.0 and zoom_score >= rotate_score:
            out.zoom_steps = 1 if distance_delta > 0 else -1
            out.label = "zoom-in" if distance_delta > 0 else "zoom-out"
            self._two_hand_distance = distance
            self._two_hand_angle = angle
        elif rotate_score >= 1.0:
            out.rotate_steps = 1 if angle_delta > 0 else -1
            out.label = "rotate-right" if angle_delta > 0 else "rotate-left"
            self._two_hand_distance = distance
            self._two_hand_angle = angle
        else:
            # Slow baseline adaptation kills stationary-hand jitter without
            # swallowing deliberate motion.
            blend = 0.08
            self._two_hand_distance += distance_delta * blend
            self._two_hand_angle += angle_delta * blend

        return out

    def _reset_scroll(self) -> None:
        self._scroll_filtered_y = None
        self._scroll_last_y = None
        self._scroll_accum = 0.0
        self._scroll_direction = 0

    def _reset_two_hand(self) -> None:
        self._two_hand_distance = None
        self._two_hand_angle = None

    def _reset_transient(self, *, keep_palm: bool = False) -> None:
        self._pinching = False
        self._dragging = False
        self._reset_scroll()
        self._swipe_history.clear()
        self._reset_two_hand()
        if not keep_palm:
            self._palm_started = None
