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


def _hand_scale(hand: Hand) -> float:
    # Robust palm-size estimate in normalized image coordinates.
    # The max() keeps synthetic/partial test hands compatible.
    wrist_to_middle = _dist(hand[0], hand[9])
    across_knuckles = _dist(hand[5], hand[17])
    return max(wrist_to_middle, across_knuckles, 1e-4)


def _scaled_threshold(hand: Hand, base: float, reference: float) -> float:
    scale = _hand_scale(hand)
    if scale <= 0.01:
        return base
    factor = scale / max(0.05, reference)
    factor = max(0.65, min(1.55, factor))
    return base * factor


def _open_palm(hand: Hand) -> bool:
    return all(
        _finger_extended(hand, tip, pip)
        for tip, pip in ((8, 6), (12, 10), (16, 14), (20, 18))
    )


class GestureEngine:
    """Deterministic gesture state machine with jitter-resistant motion gestures."""

    FEATURE_DEFAULTS = {
        "pointer": False,
        "click": False,
        "right_click": True,
        "scroll": True,
        "swipe": True,
        "zoom": True,
        "rotate": True,
        "drag": False,
    }

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self._features = dict(self.FEATURE_DEFAULTS)
        self._features["drag"] = bool(cfg.get("drag_enabled", False))

        self._pinching = False
        self._pinch_started = 0.0
        self._pinch_anchor: tuple[float, float] | None = None
        self._pinch_motion_max = 0.0
        self._left_armed = False
        self._left_open_frames = 0
        self._pinch_close_frames = 0
        self._dragging = False
        self._right_latched = False

        self._transforming = False
        self._transform_start_frames = 0
        self._transform_miss_frames = 0
        self._transform_distance: float | None = None
        self._transform_angle: float | None = None

        self._stable_finger_state: tuple[bool, bool, bool, bool] | None = None
        self._candidate_finger_state: tuple[bool, bool, bool, bool] | None = None
        self._candidate_finger_frames = 0
        self._pose_confirm_frames = max(
            1,
            int(cfg.get("pose_confirm_frames", 1)),
        )

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
        # Palm-pause was intentionally removed. Kept as a read-only
        # compatibility property for camera/debug UI.
        return False

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
            self._reset_transform()
            self._reset_two_hand()

    def set_paused(self, value: bool) -> None:
        # Compatibility no-op: gesture pausing is no longer a hand gesture.
        return

    def reset_tracking(self) -> None:
        self._right_latched = False
        self._stable_finger_state = None
        self._candidate_finger_state = None
        self._candidate_finger_frames = 0
        self._last_swipe_fire = 0.0
        self._reset_transient()
        self._reset_two_hand()

    def update(self, hands: list[Hand]) -> GestureOutput:
        if not hands:
            was_dragging = self._dragging
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

    def _stable_fingers(
        self,
        raw: tuple[bool, bool, bool, bool],
    ) -> tuple[bool, bool, bool, bool]:
        if self._stable_finger_state is None:
            self._stable_finger_state = raw
            self._candidate_finger_state = None
            self._candidate_finger_frames = 0
            return raw

        if raw == self._stable_finger_state:
            self._candidate_finger_state = None
            self._candidate_finger_frames = 0
            return self._stable_finger_state

        if raw != self._candidate_finger_state:
            self._candidate_finger_state = raw
            self._candidate_finger_frames = 1
            if self._candidate_finger_frames >= self._pose_confirm_frames:
                self._stable_finger_state = raw
                self._candidate_finger_state = None
                self._candidate_finger_frames = 0
            return self._stable_finger_state

        self._candidate_finger_frames += 1
        if self._candidate_finger_frames >= self._pose_confirm_frames:
            self._stable_finger_state = raw
            self._candidate_finger_state = None
            self._candidate_finger_frames = 0
        return self._stable_finger_state

    def _update_one_hand(self, hand: Hand) -> GestureOutput:
        now = time.monotonic()
        thumb, index, middle = hand[4], hand[8], hand[12]

        raw_fingers = (
            _finger_extended(hand, 8, 6),
            _finger_extended(hand, 12, 10),
            _finger_extended(hand, 16, 14),
            _finger_extended(hand, 20, 18),
        )
        index_up, middle_up, ring_up, pinky_up = self._stable_fingers(raw_fingers)

        # Right click: thumb + middle pinch, separated from the left-click pinch.
        hand_ref = float(self.cfg.get("reference_hand_scale", 0.20))
        right_distance = _dist(thumb, middle)
        right_on_threshold = _scaled_threshold(
            hand,
            float(self.cfg.get("right_pinch_threshold", 0.05)),
            hand_ref,
        )
        right_release_threshold = _scaled_threshold(
            hand,
            float(
                self.cfg.get(
                    "right_release_threshold",
                    self.cfg.get("click_release_threshold", 0.072),
                )
            ),
            hand_ref,
        )
        left_release_threshold = _scaled_threshold(
            hand,
            float(self.cfg.get("click_release_threshold", 0.065)),
            hand_ref,
        )
        right_on = right_distance <= right_on_threshold
        right_off = right_distance >= right_release_threshold
        index_separate = _dist(thumb, index) > left_release_threshold
        if self.feature_enabled("right_click"):
            if right_on and not self._right_latched and index_separate and middle_up:
                self._right_latched = True
                return GestureOutput(right_click=True, label="right-click")
            if right_off:
                self._right_latched = False
        else:
            self._right_latched = False

        pinch = _dist(thumb, index)
        pinch_on_threshold = _scaled_threshold(
            hand,
            float(self.cfg.get("pinch_threshold", 0.045)),
            hand_ref,
        )
        left_arm_threshold = _scaled_threshold(
            hand,
            float(self.cfg.get("click_arm_threshold", 0.095)),
            hand_ref,
        )
        pinch_on = pinch <= pinch_on_threshold
        pinch_off = pinch >= left_release_threshold
        out = GestureOutput()

        # Natural one-hand transform pose:
        # index extended, other three fingers folded, thumb free to pinch.
        pointer_pose = index_up and not middle_up and not ring_up and not pinky_up
        transform_enabled = (
            pointer_pose
            and (self.feature_enabled("zoom") or self.feature_enabled("rotate"))
        )

        # Old-style pinch transform: close thumb + index, then simply open/close
        # for zoom or twist the same pinch for rotation. No hold-to-enter mode.
        if self._transforming:
            if transform_enabled:
                self._transform_miss_frames = 0
                return self._update_pinch_transform(hand)

            self._transform_miss_frames += 1
            if self._transform_miss_frames < max(
                1,
                int(self.cfg.get("transform_release_frames", 3)),
            ):
                return GestureOutput(label="transform-hold")
            self._reset_transform()

        if transform_enabled:
            start_threshold = _scaled_threshold(
                hand,
                float(self.cfg.get("transform_start_threshold", 0.060)),
                hand_ref,
            )
            if pinch <= start_threshold:
                self._transform_start_frames += 1
                if self._transform_start_frames >= max(
                    1,
                    int(self.cfg.get("transform_start_frames", 2)),
                ):
                    self._transforming = True
                    self._transform_distance = max(
                        1e-4,
                        pinch / max(1e-4, _hand_scale(hand)),
                    )
                    self._transform_angle = math.degrees(
                        math.atan2(index.y - thumb.y, index.x - thumb.x)
                    )
                    self._transform_start_frames = 0
                    self._pinching = False
                    self._left_armed = False
                    self._left_open_frames = 0
                    self._pinch_close_frames = 0
                    out.label = "transform-ready"
                    return out
                out.label = "pinch-ready"
            else:
                self._transform_start_frames = 0
                out.label = "zoom-ready"
            # Zoom/rotation own this pose completely. They never share the
            # thumb-index pinch with Air Touch, click or drag.
            return out

        self._transform_start_frames = 0

        # Legacy click remains available only when zoom/rotation are disabled.
        # This keeps the pinch unambiguous while the transform gestures are on.
        if not self._pinching:
            if pointer_pose and pinch >= left_arm_threshold:
                self._left_open_frames += 1
                if self._left_open_frames >= max(
                    1,
                    int(self.cfg.get("click_arm_frames", 2)),
                ):
                    self._left_armed = True
            elif pinch_on:
                self._left_open_frames = 0
            elif not pointer_pose:
                self._left_open_frames = 0
                self._left_armed = False

        if (
            self.feature_enabled("click")
            and pinch_on
            and not self._pinching
            and self._left_armed
        ):
            self._pinch_close_frames += 1
            if self._pinch_close_frames >= max(
                1,
                int(self.cfg.get("click_close_frames", 2)),
            ):
                self._pinching = True
                self._pinch_started = now
                self._pinch_anchor = (index.x, index.y)
                self._pinch_motion_max = 0.0
                self._left_armed = False
                self._left_open_frames = 0
                self._pinch_close_frames = 0
                out.label = "pinch"
        elif not self._pinching:
            self._pinch_close_frames = 0

        if self._pinching:
            hold_ms = (now - self._pinch_started) * 1000.0
            click_min_ms = float(self.cfg.get("click_min_ms", 55))
            click_max_motion = float(self.cfg.get("click_max_motion", 0.028))

            if self._pinch_anchor is not None:
                motion_from_anchor = math.hypot(
                    index.x - self._pinch_anchor[0],
                    index.y - self._pinch_anchor[1],
                )
                self._pinch_motion_max = max(
                    self._pinch_motion_max,
                    motion_from_anchor,
                )

            if pinch_off:
                valid_click = (
                    self.feature_enabled("click")
                    and hold_ms >= click_min_ms
                    and self._pinch_motion_max <= click_max_motion
                )
                if valid_click:
                    out.left_click = True
                    out.label = "click"
                else:
                    out.label = "pinch-release"

                self._pinching = False
                self._pinch_anchor = None
                self._pinch_motion_max = 0.0

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

    def _update_pinch_transform(self, hand: Hand) -> GestureOutput:
        thumb, index = hand[4], hand[8]
        hand_scale = max(1e-4, _hand_scale(hand))
        distance = _dist(thumb, index) / hand_scale
        angle = math.degrees(math.atan2(index.y - thumb.y, index.x - thumb.x))

        if self._transform_distance is None:
            self._transform_distance = distance
        if self._transform_angle is None:
            self._transform_angle = angle

        base_distance = max(1e-4, self._transform_distance)
        distance_ratio = max(1e-4, distance / base_distance)
        angle_delta = angle - self._transform_angle
        while angle_delta > 180:
            angle_delta -= 360
        while angle_delta < -180:
            angle_delta += 360

        zoom_ratio = max(
            0.025,
            float(self.cfg.get("pinch_zoom_ratio", 0.065)),
        )
        rotate_deadzone = max(
            0.5,
            float(self.cfg.get("pinch_rotate_deadzone_deg", 1.0)),
        )
        max_rotate_degrees = max(
            1,
            int(self.cfg.get("rotate_max_degrees_per_frame", 12)),
        )
        max_zoom_steps = max(
            1,
            int(self.cfg.get("zoom_max_steps_per_frame", 3)),
        )

        out = GestureOutput(label="transform")

        if self.feature_enabled("zoom"):
            factor = 1.0 + zoom_ratio
            zoom_steps = 0
            if distance_ratio >= factor:
                zoom_steps = int(
                    math.log(distance_ratio) / math.log(factor)
                )
            elif distance_ratio <= 1.0 / factor:
                zoom_steps = -int(
                    math.log(1.0 / distance_ratio) / math.log(factor)
                )

            zoom_steps = max(
                -max_zoom_steps,
                min(max_zoom_steps, zoom_steps),
            )
            if zoom_steps:
                out.zoom_steps = zoom_steps
                # Consume only the emitted amount. Any remaining motion stays
                # accumulated for the next frame instead of being discarded.
                if zoom_steps > 0:
                    self._transform_distance *= factor ** zoom_steps
                else:
                    self._transform_distance /= factor ** (-zoom_steps)

        if (
            self.feature_enabled("rotate")
            and abs(angle_delta) >= rotate_deadzone
        ):
            # Rotation now has true degree semantics. Keep the sub-degree
            # remainder in the anchor so slow movement is not lost.
            degrees = math.trunc(angle_delta)
            degrees = max(
                -max_rotate_degrees,
                min(max_rotate_degrees, degrees),
            )
            if degrees:
                out.rotate_steps = degrees
                self._transform_angle += degrees
                while self._transform_angle > 180:
                    self._transform_angle -= 360
                while self._transform_angle < -180:
                    self._transform_angle += 360

        if out.zoom_steps and out.rotate_steps:
            out.label = "zoom-rotate"
        elif out.zoom_steps:
            out.label = "zoom-in" if out.zoom_steps > 0 else "zoom-out"
        elif out.rotate_steps:
            out.label = "rotate-right" if out.rotate_steps > 0 else "rotate-left"

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
        rotate_deadzone = max(
            0.5,
            float(self.cfg.get("two_hand_rotate_deadzone_deg", 1.0)),
        )
        zoom_score = (
            abs(distance_delta) / zoom_threshold
            if self.feature_enabled("zoom")
            else 0.0
        )
        rotate_score = (
            abs(angle_delta) / rotate_deadzone
            if self.feature_enabled("rotate")
            else 0.0
        )

        # Choose the dominant transform so zoom and rotate never fight.
        if zoom_score >= 1.0 and zoom_score >= rotate_score:
            out.zoom_steps = 1 if distance_delta > 0 else -1
            out.label = "zoom-in" if distance_delta > 0 else "zoom-out"
            self._two_hand_distance = distance
            self._two_hand_angle = angle
        elif rotate_score >= 1.0:
            degrees = math.trunc(angle_delta)
            limit = max(
                1,
                int(self.cfg.get("rotate_max_degrees_per_frame", 12)),
            )
            degrees = max(-limit, min(limit, degrees))
            if degrees:
                out.rotate_steps = degrees
                out.label = "rotate-right" if degrees > 0 else "rotate-left"
                self._two_hand_angle += degrees
                while self._two_hand_angle > 180:
                    self._two_hand_angle -= 360
                while self._two_hand_angle < -180:
                    self._two_hand_angle += 360
        else:
            # Slow baseline adaptation kills stationary-hand jitter without
            # swallowing deliberate motion.
            blend = 0.08
            self._two_hand_distance += distance_delta * blend
            self._two_hand_angle += angle_delta * blend

        return out

    def _reset_transform(self) -> None:
        self._transforming = False
        self._transform_start_frames = 0
        self._transform_miss_frames = 0
        self._transform_distance = None
        self._transform_angle = None

    def _reset_scroll(self) -> None:
        self._scroll_filtered_y = None
        self._scroll_last_y = None
        self._scroll_accum = 0.0
        self._scroll_direction = 0

    def _reset_two_hand(self) -> None:
        self._two_hand_distance = None
        self._two_hand_angle = None

    def _reset_transient(self) -> None:
        self._pinching = False
        self._pinch_anchor = None
        self._pinch_motion_max = 0.0
        self._left_armed = False
        self._left_open_frames = 0
        self._pinch_close_frames = 0
        self._dragging = False
        self._reset_transform()
        self._reset_scroll()
        self._swipe_history.clear()
        self._reset_two_hand()
