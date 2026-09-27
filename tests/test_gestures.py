from astra_pc.gestures.engine import GestureEngine
from astra_pc.vision.hands import Hand, Point


def fake_hand() -> Hand:
    pts = [Point(0.5, 0.8, 0.0) for _ in range(21)]
    pts[6] = Point(0.5, 0.55, 0.0)
    pts[8] = Point(0.5, 0.35, 0.0)
    pts[10] = Point(0.6, 0.65, 0.0)
    pts[12] = Point(0.6, 0.75, 0.0)
    pts[14] = Point(0.7, 0.65, 0.0)
    pts[16] = Point(0.7, 0.75, 0.0)
    pts[18] = Point(0.8, 0.65, 0.0)
    pts[20] = Point(0.8, 0.75, 0.0)
    pts[4] = Point(0.3, 0.6, 0.0)
    return Hand(tuple(pts), "Right")


def test_pointer_gesture():
    engine = GestureEngine({
        "pinch_threshold": 0.045,
        "click_release_threshold": 0.065,
        "drag_hold_ms": 220,
        "pause_cooldown_ms": 900,
        "scroll_gain": 8.0,
        "scroll_deadzone": 0.007,
    })
    result = engine.update(fake_hand())
    assert result.pointer is not None
    assert result.label == "pointer"
