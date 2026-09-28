from __future__ import annotations

import math
import time
from dataclasses import dataclass

from astra_pc.vision.types import Hand, Point


@dataclass(slots=True)
class GestureOutput:
    pointer: tuple[float, float] | None = None
    left_down: bool | None = None
    right_click: bool = False
    scroll: int = 0
    zoom_steps: int = 0
    rotate_steps: int = 0
    swipe: str | None = None
    toggle_pause: bool = False
    label: str = "idle"


def _dist(a: Point, b: Point) -> float:
    return math.hypot(a.x - b.x, a.y - b.y)


def _finger_up(hand: Hand, tip: int, pip: int) -> bool:
    return hand[tip].y < hand[pip].y


def _center(hand: Hand) -> tuple[float, float]:
    ids = (0, 5, 9, 13, 17)
    return (
        sum(hand[i].x for i in ids) / len(ids),
        sum(hand[i].y for i in ids) / len(ids),
    )


class GestureEngine:
    """Deterministic low-latency gesture state machine."""

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self._pinching = False
        self._pinch_started = 0.0
        self._dragging = False
        self._paused = False
        self._last_pause_toggle = 0.0
        self._palm_latched = False
        self._last_scroll_y: float | None = None
        self._right_latched = False
        self._two_hand_distance: float | None = None
        self._two_hand_angle: float | None = None
        self._last_swipe_x: float | None = None
        self._last_swipe_t: float | None = None
        self._last_swipe_fire = 0.0

    @property
    def paused(self) -> bool:
        return self._paused

    def set_paused(self, value: bool) -> None:
        self._paused = bool(value)
        self._reset_transient()

    def update(self, hands: list[Hand]) -> GestureOutput:
        if not hands:
            self._last_scroll_y = None
            self._reset_two_hand()
            return GestureOutput(label="no-hand")

        if len(hands) >= 2:
            out = self._update_two_hands(hands[0], hands[1])
            if out.label != "idle":
                return out
        else:
            self._reset_two_hand()

        return self._update_one_hand(hands[0])

    def _update_one_hand(self, hand: Hand) -> GestureOutput:
        now = time.monotonic()
        thumb, index, middle = hand[4], hand[8], hand[12]

        index_up = _finger_up(hand, 8, 6)
        middle_up = _finger_up(hand, 12, 10)
        ring_up = _finger_up(hand, 16, 14)
        pinky_up = _finger_up(hand, 20, 18)

        open_palm = index_up and middle_up and ring_up and pinky_up
        if open_palm and not self._palm_latched:
            cooldown = float(self.cfg["pause_cooldown_ms"]) / 1000.0
            if now - self._last_pause_toggle >= cooldown:
                self._palm_latched = True
                self._paused = not self._paused
                self._last_pause_toggle = now
                self._reset_transient()
                return GestureOutput(
                    toggle_pause=True,
                    left_down=False,
                    label="paused" if self._paused else "resumed",
                )
        elif not open_palm:
            self._palm_latched = False

        if self._paused:
            return GestureOutput(label="paused")

        # Right click: thumb + middle pinch while index is not pinching.
        right_distance = _dist(thumb, middle)
        right_on = right_distance <= float(self.cfg["right_pinch_threshold"])
        if right_on and not self._right_latched and _dist(thumb, index) > float(self.cfg["click_release_threshold"]):
            self._right_latched = True
            return GestureOutput(right_click=True, label="right-click")
        if not right_on:
            self._right_latched = False

        pinch = _dist(thumb, index)
        pinch_on = pinch <= float(self.cfg["pinch_threshold"])
        pinch_off = pinch >= float(self.cfg["click_release_threshold"])
        out = GestureOutput()

        if index_up and not middle_up:
            out.pointer = (index.x, index.y)
            out.label = "pointer"

        if pinch_on and not self._pinching:
            self._pinching = True
            self._pinch_started = now
            out.left_down = True
            out.pointer = (index.x, index.y)
            out.label = "pinch"

        if self._pinching:
            hold_ms = (now - self._pinch_started) * 1000.0
            if hold_ms >= float(self.cfg["drag_hold_ms"]):
                self._dragging = True
                out.left_down = True
                out.pointer = (index.x, index.y)
                out.label = "drag"
            if pinch_off:
                out.left_down = False
                out.label = "drop" if self._dragging else "click"
                self._pinching = False
                self._dragging = False

        scrolling = index_up and middle_up and not ring_up and not pinky_up and not self._pinching
        if scrolling:
            y = (index.y + middle.y) * 0.5
            if self._last_scroll_y is not None:
                dy = self._last_scroll_y - y
                if abs(dy) >= float(self.cfg["scroll_deadzone"]):
                    out.scroll = int(round(dy * float(self.cfg["scroll_gain"])))
                    if out.scroll == 0:
                        out.scroll = 1 if dy > 0 else -1
            self._last_scroll_y = y
            out.label = "scroll"
        else:
            self._last_scroll_y = None

        # Three-finger horizontal swipe. Chosen to avoid conflicting with two-finger scroll.
        swipe_pose = index_up and middle_up and ring_up and not pinky_up and not self._pinching
        if swipe_pose:
            cx, _ = _center(hand)
            if self._last_swipe_x is not None and self._last_swipe_t is not None:
                dt = max(1e-4, now - self._last_swipe_t)
                vx = (cx - self._last_swipe_x) / dt
                cooldown = float(self.cfg["swipe_cooldown_ms"]) / 1000.0
                if abs(vx) >= float(self.cfg["swipe_velocity"]) and now - self._last_swipe_fire >= cooldown:
                    out.swipe = "right" if vx > 0 else "left"
                    out.label = f"swipe-{out.swipe}"
                    self._last_swipe_fire = now
            self._last_swipe_x = cx
            self._last_swipe_t = now
        else:
            self._last_swipe_x = None
            self._last_swipe_t = None

        return out

    def _update_two_hands(self, a: Hand, b: Hand) -> GestureOutput:
        if self._paused:
            return GestureOutput(label="paused")

        ac = _center(a)
        bc = _center(b)
        dx = bc[0] - ac[0]
        dy = bc[1] - ac[1]
        distance = math.hypot(dx, dy)
        angle = math.degrees(math.atan2(dy, dx))

        out = GestureOutput(label="two-hand")

        if self._two_hand_distance is not None:
            delta = distance - self._two_hand_distance
            threshold = float(self.cfg["two_hand_zoom_threshold"])
            if abs(delta) >= threshold:
                out.zoom_steps = 1 if delta > 0 else -1
                out.label = "zoom-in" if delta > 0 else "zoom-out"
                self._two_hand_distance = distance
        else:
            self._two_hand_distance = distance

        if self._two_hand_angle is not None:
            delta_angle = angle - self._two_hand_angle
            while delta_angle > 180:
                delta_angle -= 360
            while delta_angle < -180:
                delta_angle += 360
            threshold_deg = float(self.cfg["two_hand_rotate_threshold_deg"])
            if abs(delta_angle) >= threshold_deg:
                out.rotate_steps = 1 if delta_angle > 0 else -1
                out.label = "rotate-right" if delta_angle > 0 else "rotate-left"
                self._two_hand_angle = angle
        else:
            self._two_hand_angle = angle

        return out

    def _reset_two_hand(self) -> None:
        self._two_hand_distance = None
        self._two_hand_angle = None

    def _reset_transient(self) -> None:
        self._pinching = False
        self._dragging = False
        self._last_scroll_y = None
        self._last_swipe_x = None
        self._last_swipe_t = None
        self._reset_two_hand()
