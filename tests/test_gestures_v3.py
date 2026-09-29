import math

from astra_pc.gestures.engine import GestureEngine
from astra_pc.vision.types import Hand, Point


CFG = {
    "pinch_threshold": 0.052,
    "click_release_threshold": 0.072,
    "right_pinch_threshold": 0.056,
    "right_release_threshold": 0.074,
    "reference_hand_scale": 0.20,
    "drag_enabled": False,
    "transform_start_threshold": 0.060,
    "transform_start_frames": 2,
    "pinch_zoom_ratio": 0.08,
    "pinch_rotate_threshold_deg": 30.0,
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


def enter_transform(engine: GestureEngine, distance: float = 0.02):
    first = engine.update([pointer_hand(distance)])
    second = engine.update([pointer_hand(distance)])
    assert first.label == "pinch-ready"
    assert second.label == "transform-ready"


def test_direct_pinch_enters_transform_without_hold():
    engine = GestureEngine(dict(CFG))
    enter_transform(engine)
    assert engine._transforming


def test_opening_pinch_zooms_in():
    engine = GestureEngine(dict(CFG))
    enter_transform(engine)

    out = engine.update([pointer_hand(0.04)])

    assert out.zoom_steps == 1
    assert out.label == "zoom-in"


def test_closing_pinch_zooms_out_after_opening():
    engine = GestureEngine(dict(CFG))
    enter_transform(engine)

    first = engine.update([pointer_hand(0.04)])
    assert first.zoom_steps == 1

    second = engine.update([pointer_hand(0.025)])
    assert second.zoom_steps == -1
    assert second.label == "zoom-out"


def test_twisting_same_pinch_rotates():
    engine = GestureEngine(dict(CFG))
    enter_transform(engine)

    small = engine.update([pointer_hand(0.02, 15.0)])
    assert small.rotate_steps == 0

    rotated = engine.update([pointer_hand(0.02, 35.0)])
    assert rotated.rotate_steps == 1
    assert rotated.label in {"rotate-right", "zoom-rotate"}


def test_zoom_and_rotation_can_fire_independently():
    engine = GestureEngine(dict(CFG))
    enter_transform(engine)

    out = engine.update([pointer_hand(0.04, 35.0)])

    assert out.zoom_steps == 1
    assert out.rotate_steps == 1
    assert out.label == "zoom-rotate"


def test_pointer_and_drag_are_off_by_default():
    engine = GestureEngine(dict(CFG))
    result = engine.update([pointer_hand(0.12)])

    assert result.pointer is None
    assert result.left_down is None
