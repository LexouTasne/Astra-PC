from astra_pc.gestures.engine import GestureEngine
from astra_pc.vision.types import Hand, Point


CFG = {
    "pause_cooldown_ms": 0,
    "right_pinch_threshold": 0.04,
    "click_release_threshold": 0.07,
    "pinch_threshold": 0.045,
    "drag_hold_ms": 220,
    "scroll_deadzone": 0.007,
    "scroll_gain": 8.0,
    "swipe_cooldown_ms": 500,
    "swipe_velocity": 1.0,
    "two_hand_zoom_threshold": 0.025,
    "two_hand_rotate_threshold_deg": 7.0,
}


def open_hand():
    pts = [Point(0.5, 0.8, 0.0) for _ in range(21)]
    # PIP joints below tips in image coordinates => fingers up.
    for tip, pip, x in ((8, 6, .4), (12, 10, .48), (16, 14, .56), (20, 18, .64)):
        pts[pip] = Point(x, 0.55, 0.0)
        pts[tip] = Point(x, 0.35, 0.0)
    pts[4] = Point(0.28, 0.5, 0.0)
    return Hand(tuple(pts), "Right")


def closed_hand():
    pts = [Point(0.5, 0.5, 0.0) for _ in range(21)]
    for tip, pip in ((8, 6), (12, 10), (16, 14), (20, 18)):
        pts[pip] = Point(0.5, 0.4, 0.0)
        pts[tip] = Point(0.5, 0.6, 0.0)
    return Hand(tuple(pts), "Right")


def test_open_palm_toggles_only_once_until_released():
    engine = GestureEngine(CFG)
    first = engine.update([open_hand()])
    assert first.toggle_pause
    assert engine.paused

    second = engine.update([open_hand()])
    assert not second.toggle_pause
    assert engine.paused

    engine.update([closed_hand()])
    third = engine.update([open_hand()])
    assert third.toggle_pause
    assert not engine.paused
