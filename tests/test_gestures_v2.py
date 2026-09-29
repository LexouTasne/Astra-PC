import threading

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


def test_ydotool_negative_wheel_is_preserved_by_coalescer():
    backend = object.__new__(YdotoolBackend)
    backend._pending_wheel = 0
    backend._wheel_lock = threading.Lock()
    backend._wake = threading.Event()

    backend.scroll(-3)

    assert backend._take_wheel() == -3


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
    assert parse_gesture_control("ativa a pausa por palma") is None


def test_gesture_control_state_persists(tmp_path):
    state = GestureControlState(tmp_path / "gestures.json")

    assert apply_gesture_control(state, "desativa o scroll por gestos")
    assert state.feature("scroll", True) is False

    assert apply_gesture_control(state, "desliga todos os gestos")
    assert state.enabled() is False

    reloaded = GestureControlState(tmp_path / "gestures.json")
    assert reloaded.enabled() is False
    assert reloaded.feature("scroll", True) is False


def scaled_pinch_hand(scale: float, pinch_ratio: float) -> Hand:
    cx, cy = 0.5, 0.65
    pts = [Point(cx, cy, 0.0) for _ in range(21)]
    pts[0] = Point(cx, cy + 0.20 * scale, 0.0)
    pts[5] = Point(cx - 0.10 * scale, cy, 0.0)
    pts[9] = Point(cx, cy - 0.20 * scale, 0.0)
    pts[17] = Point(cx + 0.10 * scale, cy, 0.0)

    pts[6] = Point(cx - 0.06 * scale, cy - 0.18 * scale, 0.0)
    pts[8] = Point(cx - 0.06 * scale, cy - 0.36 * scale, 0.0)
    pts[10] = Point(cx + 0.02 * scale, cy - 0.05 * scale, 0.0)
    pts[12] = Point(cx + 0.02 * scale, cy + 0.05 * scale, 0.0)
    pts[14] = Point(cx + 0.08 * scale, cy - 0.03 * scale, 0.0)
    pts[16] = Point(cx + 0.08 * scale, cy + 0.08 * scale, 0.0)
    pts[18] = Point(cx + 0.13 * scale, cy - 0.01 * scale, 0.0)
    pts[20] = Point(cx + 0.13 * scale, cy + 0.10 * scale, 0.0)

    index = pts[8]
    pinch_distance = 0.05 * scale * pinch_ratio
    pts[4] = Point(index.x + pinch_distance, index.y, 0.0)
    return Hand(tuple(pts), "Right")


def test_pinch_threshold_scales_with_hand_size():
    cfg = dict(CFG)
    cfg["reference_hand_scale"] = 0.20

    near = GestureEngine(cfg)
    far = GestureEngine(cfg)

    near_down = near.update([scaled_pinch_hand(1.4, 0.45)])
    far_down = far.update([scaled_pinch_hand(0.7, 0.45)])

    assert near_down.label in {"pinch-ready", "transform-ready"}
    assert far_down.label in {"pinch-ready", "transform-ready"}


def test_pose_change_requires_two_frames_but_initial_pose_is_immediate():
    cfg = dict(CFG)
    cfg["pose_confirm_frames"] = 2
    engine = GestureEngine(cfg)

    pointer = scroll_hand(0.0)
    # Build a clear pointer hand from the same skeleton.
    pts = list(pointer.points)
    pts[10] = Point(pts[10].x, 0.28, 0.0)
    pts[12] = Point(pts[12].x, 0.60, 0.0)
    pointer_hand = Hand(tuple(pts), "Right")

    first = engine.update([pointer_hand])
    assert first.pointer is None

    one_frame = engine.update([scroll_hand(0.0)])
    assert one_frame.label != "scroll-ready"

    two_frames = engine.update([scroll_hand(0.0)])
    assert two_frames.label == "scroll-ready"
