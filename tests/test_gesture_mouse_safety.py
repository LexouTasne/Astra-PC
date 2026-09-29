from astra_pc.gestures.engine import GestureEngine
from astra_pc.vision.types import Hand, Point


CFG = {
    "pinch_threshold": 0.045,
    "click_release_threshold": 0.065,
    "right_pinch_threshold": 0.05,
    "drag_enabled": False,
    "transform_start_threshold": 0.06,
    "transform_start_frames": 2,
    "pinch_zoom_ratio": 0.08,
    "pinch_rotate_threshold_deg": 30,
    "pause_cooldown_ms": 900,
    "scroll_gain": 8,
    "scroll_deadzone": 0.007,
    "swipe_velocity": 1.25,
    "swipe_cooldown_ms": 700,
    "two_hand_zoom_threshold": 0.035,
    "two_hand_rotate_threshold_deg": 10,
}


def hand_with_pinch(distance: float) -> Hand:
    pts = [Point(0.5, 0.7, 0.0) for _ in range(21)]
    pts[0] = Point(0.5, 0.82, 0.0)
    pts[5] = Point(0.46, 0.62, 0.0)
    pts[6] = Point(0.5, 0.52, 0.0)
    pts[8] = Point(0.5, 0.32, 0.0)
    pts[9] = Point(0.54, 0.62, 0.0)
    pts[10] = Point(0.56, 0.45, 0.0)
    pts[12] = Point(0.56, 0.60, 0.0)
    pts[13] = Point(0.62, 0.62, 0.0)
    pts[14] = Point(0.62, 0.45, 0.0)
    pts[16] = Point(0.62, 0.60, 0.0)
    pts[17] = Point(0.68, 0.64, 0.0)
    pts[18] = Point(0.68, 0.45, 0.0)
    pts[20] = Point(0.68, 0.60, 0.0)
    pts[4] = Point(0.5 + distance, 0.32, 0.0)
    return Hand(tuple(pts), "Right")


def test_default_pinch_never_clicks_or_holds_mouse():
    engine = GestureEngine(dict(CFG))

    first = engine.update([hand_with_pinch(0.02)])
    second = engine.update([hand_with_pinch(0.02)])

    assert not first.left_click
    assert first.left_down is None
    assert not second.left_click
    assert second.left_down is None
    assert second.label == "transform-ready"


def test_transform_motion_never_becomes_drag():
    engine = GestureEngine(dict(CFG))
    engine.update([hand_with_pinch(0.02)])
    engine.update([hand_with_pinch(0.02)])

    moved = engine.update([hand_with_pinch(0.04)])

    assert moved.left_down is None
    assert not moved.left_click
    assert 1 <= moved.zoom_steps <= 3


def test_tracking_loss_never_leaves_mouse_down():
    engine = GestureEngine(dict(CFG))
    engine.update([hand_with_pinch(0.02)])
    engine.update([hand_with_pinch(0.02)])

    lost = engine.update([])

    assert lost.left_down is None
    assert lost.label == "no-hand"
