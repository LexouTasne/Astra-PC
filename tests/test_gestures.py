from astra_pc.gestures.engine import GestureEngine
from astra_pc.vision.hands import Hand, Point


CFG = {
    "pinch_threshold": 0.045,
    "click_release_threshold": 0.065,
    "right_pinch_threshold": 0.05,
    "drag_hold_ms": 220,
    "scroll_gain": 8.0,
    "scroll_deadzone": 0.007,
    "swipe_velocity": 1.25,
    "swipe_cooldown_ms": 700,
    "two_hand_zoom_threshold": 0.035,
    "two_hand_rotate_deadzone_deg": 1.0,
}


def fake_hand(x_offset: float = 0.0) -> Hand:
    pts = [Point(0.5 + x_offset, 0.8, 0.0) for _ in range(21)]
    pts[6] = Point(0.5 + x_offset, 0.55, 0.0)
    pts[8] = Point(0.5 + x_offset, 0.35, 0.0)
    pts[10] = Point(0.6 + x_offset, 0.65, 0.0)
    pts[12] = Point(0.6 + x_offset, 0.75, 0.0)
    pts[14] = Point(0.7 + x_offset, 0.65, 0.0)
    pts[16] = Point(0.7 + x_offset, 0.75, 0.0)
    pts[18] = Point(0.8 + x_offset, 0.65, 0.0)
    pts[20] = Point(0.8 + x_offset, 0.75, 0.0)
    pts[4] = Point(0.3 + x_offset, 0.6, 0.0)
    return Hand(tuple(pts), "Right")


def open_hand(x_offset: float = 0.0) -> Hand:
    pts = [Point(0.5 + x_offset, 0.82, 0.0) for _ in range(21)]
    pts[0] = Point(0.5 + x_offset, 0.86, 0.0)
    for tip, pip, x in (
        (8, 6, 0.40),
        (12, 10, 0.48),
        (16, 14, 0.56),
        (20, 18, 0.64),
    ):
        pts[pip] = Point(x + x_offset, 0.56, 0.0)
        pts[tip] = Point(x + x_offset, 0.30, 0.0)
    pts[4] = Point(0.28 + x_offset, 0.50, 0.0)
    return Hand(tuple(pts), "Right")


def test_air_touch_is_disabled_by_default():
    engine = GestureEngine(CFG)
    result = engine.update([fake_hand()])
    assert result.pointer is None


def test_two_hand_mode_requires_explicit_opt_in():
    engine = GestureEngine(CFG)
    result = engine.update([open_hand(-0.15), open_hand(0.15)])
    assert result.label != "two-hand-ready"

    cfg = dict(CFG)
    cfg["two_hand_transforms_enabled"] = True
    enabled = GestureEngine(cfg)
    result = enabled.update([open_hand(-0.15), open_hand(0.15)])
    assert result.label == "two-hand-ready"
