import time

from astra_pc.gestures.engine import GestureEngine
from astra_pc.vision.types import Hand, Point


CFG = {
    "pinch_threshold": 0.045,
    "click_release_threshold": 0.065,
    "right_pinch_threshold": 0.05,
    "drag_enabled": False,
    "drag_hold_ms": 350,
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
    # index up, others down
    pts[6] = Point(0.5, 0.52, 0.0)
    pts[8] = Point(0.5, 0.32, 0.0)
    pts[10] = Point(0.56, 0.45, 0.0)
    pts[12] = Point(0.56, 0.60, 0.0)
    pts[14] = Point(0.62, 0.45, 0.0)
    pts[16] = Point(0.62, 0.60, 0.0)
    pts[18] = Point(0.68, 0.45, 0.0)
    pts[20] = Point(0.68, 0.60, 0.0)
    pts[4] = Point(0.5 + distance, 0.32, 0.0)
    return Hand(tuple(pts), "Right")


def test_default_pinch_never_holds_left_button():
    engine = GestureEngine(dict(CFG))
    down = engine.update([hand_with_pinch(0.02)])
    assert down.left_down is None
    assert not down.left_click

    released = engine.update([hand_with_pinch(0.09)])
    assert released.left_click
    assert released.left_down is None


def test_default_drag_remains_disabled_even_after_long_hold():
    engine = GestureEngine(dict(CFG))
    engine.update([hand_with_pinch(0.02)])
    engine._pinch_started = time.monotonic() - 2.0
    held = engine.update([hand_with_pinch(0.02)])
    assert held.label != "drag"
    assert held.left_down is None


def test_tracking_loss_releases_experimental_drag():
    cfg = dict(CFG)
    cfg["drag_enabled"] = True
    engine = GestureEngine(cfg)
    engine.update([hand_with_pinch(0.02)])
    engine._pinch_started = time.monotonic() - 1.0
    dragging = engine.update([hand_with_pinch(0.02)])
    assert dragging.label == "drag"
    assert dragging.left_down is True

    lost = engine.update([])
    assert lost.left_down is False
    assert lost.label == "no-hand"
