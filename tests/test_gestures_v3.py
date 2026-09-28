import math
import time

from astra_pc.gestures.engine import GestureEngine
from astra_pc.vision.types import Hand, Point


CFG = {
    "pinch_threshold": 0.052,
    "click_release_threshold": 0.072,
    "right_pinch_threshold": 0.056,
    "right_release_threshold": 0.074,
    "reference_hand_scale": 0.20,
    "drag_enabled": False,
    "transform_hold_ms": 200,
    "pinch_zoom_ratio": 0.10,
    "pinch_rotate_threshold_deg": 45.0,
    "pose_confirm_frames": 1,
    "pause_hold_ms": 300,
    "pause_cooldown_ms": 600,
    "scroll_gain": 58.0,
    "scroll_deadzone": 0.0018,
    "scroll_smoothing": 0.62,
    "scroll_max_step": 5,
    "swipe_velocity": 0.48,
    "swipe_distance": 0.085,
    "swipe_window_ms": 240,
    "swipe_cooldown_ms": 360,
    "two_hand_zoom_threshold": 0.02,
    "two_hand_rotate_threshold_deg": 6.0,
}


def pointer_hand(thumb_distance: float, angle_deg: float = 0.0) -> Hand:
    pts = [Point(0.5, 0.72, 0.0) for _ in range(21)]
    pts[0] = Point(0.5, 0.84, 0.0)

    pts[5] = Point(0.44, 0.64, 0.0)
    pts[6] = Point(0.44, 0.52, 0.0)
    pts[8] = Point(0.44, 0.28, 0.0)

    pts[9] = Point(0.52, 0.64, 0.0)
    pts[10] = Point(0.52, 0.50, 0.0)
    pts[12] = Point(0.52, 0.67, 0.0)

    pts[13] = Point(0.60, 0.66, 0.0)
    pts[14] = Point(0.60, 0.52, 0.0)
    pts[16] = Point(0.60, 0.69, 0.0)

    pts[17] = Point(0.68, 0.68, 0.0)
    pts[18] = Point(0.68, 0.55, 0.0)
    pts[20] = Point(0.68, 0.71, 0.0)

    index = pts[8]
    angle = math.radians(angle_deg)
    pts[4] = Point(
        index.x + math.cos(angle) * thumb_distance,
        index.y + math.sin(angle) * thumb_distance,
        0.0,
    )
    return Hand(tuple(pts), "Right")


def test_quick_pinch_stays_click():
    engine = GestureEngine(dict(CFG))
    engine.update([pointer_hand(0.02)])
    out = engine.update([pointer_hand(0.10)])
    assert out.left_click
    assert out.label == "click"


def test_long_pinch_opens_transform_mode_then_zooms():
    engine = GestureEngine(dict(CFG))
    engine.update([pointer_hand(0.02)])
    engine._pinch_started = time.monotonic() - 0.5

    armed = engine.update([pointer_hand(0.10)])
    assert armed.label == "transform-ready"
    assert not armed.left_click

    zoom = engine.update([pointer_hand(0.13)])
    assert zoom.zoom_steps == 1
    assert zoom.label == "zoom-in"


def test_pinch_transform_rotates_only_after_deliberate_twist():
    engine = GestureEngine(dict(CFG))
    engine.update([pointer_hand(0.02)])
    engine._pinch_started = time.monotonic() - 0.5
    engine.update([pointer_hand(0.10)])

    small = engine.update([pointer_hand(0.10, 20.0)])
    assert small.rotate_steps == 0

    rotated = engine.update([pointer_hand(0.10, 55.0)])
    assert rotated.rotate_steps == 1
    assert rotated.label == "rotate-right"


def test_explicit_drag_disables_transform_conflict():
    cfg = dict(CFG)
    cfg["drag_enabled"] = True
    engine = GestureEngine(cfg)
    engine.update([pointer_hand(0.02)])
    engine._pinch_started = time.monotonic() - 0.5
    out = engine.update([pointer_hand(0.02)])
    assert out.label == "drag"
    assert out.left_down is True
