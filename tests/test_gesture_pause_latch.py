from astra_pc.gestures.engine import GestureEngine
from astra_pc.vision.types import Hand, Point


CFG = {
    "right_pinch_threshold": 0.04,
    "click_release_threshold": 0.07,
    "pinch_threshold": 0.045,
    "scroll_deadzone": 0.007,
    "scroll_gain": 8.0,
    "swipe_cooldown_ms": 500,
    "swipe_velocity": 1.0,
    "two_hand_zoom_threshold": 0.025,
    "two_hand_rotate_deadzone_deg": 1.0,
}


def open_hand():
    pts = [Point(0.5, 0.8, 0.0) for _ in range(21)]
    for tip, pip, x in ((8, 6, .4), (12, 10, .48), (16, 14, .56), (20, 18, .64)):
        pts[pip] = Point(x, 0.55, 0.0)
        pts[tip] = Point(x, 0.35, 0.0)
    pts[4] = Point(0.28, 0.5, 0.0)
    return Hand(tuple(pts), "Right")


def test_open_palm_never_pauses_gesture_engine():
    engine = GestureEngine(CFG)

    for _ in range(20):
        out = engine.update([open_hand()])
        assert out.label != "paused"
        assert not hasattr(out, "toggle_pause")
