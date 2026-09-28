from astra_pc.gestures.control import (
    GestureControlState,
    apply_gesture_control,
    parse_gesture_control,
)
from astra_pc.gestures.engine import GestureEngine
from astra_pc.input.wayland_backend import YdotoolBackend
from astra_pc.vision.types import Hand, Point


CFG = {
    "pinch_threshold": 0.05,
    "click_release_threshold": 0.075,
    "right_pinch_threshold": 0.055,
    "drag_enabled": False,
    "drag_hold_ms": 420,
    "pause_hold_ms": 0,
    "pause_cooldown_ms": 0,
    "scroll_gain": 100.0,
    "scroll_deadzone": 0.001,
    "scroll_smoothing": 1.0,
    "scroll_max_step": 4,
    "swipe_velocity": 0.5,
    "swipe_distance": 0.08,
    "swipe_window_ms": 350,
    "swipe_cooldown_ms": 0,
    "two_hand_zoom_threshold": 0.02,
    "two_hand_rotate_threshold_deg": 6.0,
}


def scroll_hand(offset_y: float) -> Hand:
    pts = [Point(0.5, 0.72 + offset_y, 0.0) for _ in range(21)]
    pts[0] = Point(0.5, 0.86 + offset_y, 0.0)

    pts[5] = Point(0.44, 0.65 + offset_y, 0.0)
    pts[6] = Point(0.44, 0.54 + offset_y, 0.0)
    pts[8] = Point(0.44, 0.30 + offset_y, 0.0)

    pts[9] = Point(0.52, 0.65 + offset_y, 0.0)
    pts[10] = Point(0.52, 0.54 + offset_y, 0.0)
    pts[12] = Point(0.52, 0.30 + offset_y, 0.0)

    pts[13] = Point(0.60, 0.66 + offset_y, 0.0)
    pts[14] = Point(0.60, 0.56 + offset_y, 0.0)
    pts[16] = Point(0.60, 0.72 + offset_y, 0.0)

    pts[17] = Point(0.68, 0.68 + offset_y, 0.0)
    pts[18] = Point(0.68, 0.58 + offset_y, 0.0)
    pts[20] = Point(0.68, 0.73 + offset_y, 0.0)

    pts[4] = Point(0.30, 0.56 + offset_y, 0.0)
    return Hand(tuple(pts), "Right")


def test_scroll_emits_both_directions():
    engine = GestureEngine(dict(CFG))

    first = engine.update([scroll_hand(0.0)])
    assert first.label == "scroll-ready"

    up = engine.update([scroll_hand(-0.03)])
    assert up.scroll > 0
    assert up.label == "scroll-up"

    down = engine.update([scroll_hand(0.03)])
    assert down.scroll < 0
    assert down.label == "scroll-down"


def test_ydotool_negative_wheel_uses_option_separator():
    backend = object.__new__(YdotoolBackend)
    calls = []
    backend._queue_command = lambda *args: calls.append(args)

    backend.scroll(-3)

    assert calls == [
        ("mousemove", "--wheel", "--", "0", "-3")
    ]


def test_gesture_control_parser_is_specific():
    assert parse_gesture_control("Astra, desativa o scroll por gestos") == (
        "feature", "scroll", False
    )
    assert parse_gesture_control("ativa o cursor por gestos") == (
        "feature", "pointer", True
    )
    assert parse_gesture_control("desliga todos os gestos") == (
        "system", None, False
    )


def test_gesture_control_state_persists(tmp_path):
    state = GestureControlState(tmp_path / "gestures.json")

    assert apply_gesture_control(state, "desativa o scroll por gestos")
    assert state.feature("scroll", True) is False

    assert apply_gesture_control(state, "desliga todos os gestos")
    assert state.enabled() is False

    reloaded = GestureControlState(tmp_path / "gestures.json")
    assert reloaded.enabled() is False
    assert reloaded.feature("scroll", True) is False
