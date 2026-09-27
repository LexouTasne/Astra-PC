from __future__ import annotations

import math
import time
from dataclasses import dataclass

from astra_pc.vision.hands import Hand, Point


@dataclass(slots=True)
class GestureOutput:
    pointer: tuple[float, float] | None = None
    left_down: bool | None = None
    scroll: int = 0
    toggle_pause: bool = False
    label: str = "idle"


def _dist(a: Point, b: Point) -> float:
    return math.hypot(a.x - b.x, a.y - b.y)


def _finger_up(hand: Hand, tip: int, pip: int) -> bool:
    return hand[tip].y < hand[pip].y


class GestureEngine:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self._pinching = False
        self._pinch_started = 0.0
        self._dragging = False
        self._paused = False
        self._last_pause_toggle = 0.0
        self._last_scroll_y: float | None = None

    @property
    def paused(self) -> bool:
        return self._paused

    def update(self, hand: Hand) -> GestureOutput:
        now = time.monotonic()
        thumb, index, middle = hand[4], hand[8], hand[12]

        index_up = _finger_up(hand, 8, 6)
        middle_up = _finger_up(hand, 12, 10)
        ring_up = _finger_up(hand, 16, 14)
        pinky_up = _finger_up(hand, 20, 18)

        open_palm = index_up and middle_up and ring_up and pinky_up
        if open_palm:
            cooldown = float(self.cfg["pause_cooldown_ms"]) / 1000.0
            if now - self._last_pause_toggle >= cooldown:
                self._paused = not self._paused
                self._last_pause_toggle = now
                self._reset()
                return GestureOutput(toggle_pause=True, left_down=False, label="pause")

        if self._paused:
            return GestureOutput(label="paused")

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

        return out

    def _reset(self) -> None:
        self._pinching = False
        self._dragging = False
        self._last_scroll_y = None
