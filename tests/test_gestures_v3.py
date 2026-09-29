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
    "transform_release_frames": 3,
    "zoom_max_steps_per_frame": 3,
    "pinch_zoom_ratio": 0.065,
    "pose_confirm_frames": 1,
    "scroll_gain": 58.0,
    "scroll_deadzone": 0.0018,
    "scroll_smoothing": 0.62,
    "scroll_max_step": 5,
    "swipe_velocity": 0.48,
    "swipe_distance": 0.085,
    "swipe_window_ms": 240,
    "swipe_cooldown_ms": 360,
    "two_hand_zoom_threshold": 0.02,
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

    assert 1 <= out.zoom_steps <= 3
    assert out.label == "zoom-in"


def test_closing_pinch_zooms_out_after_opening():
    engine = GestureEngine(dict(CFG))
    enter_transform(engine)

    first = engine.update([pointer_hand(0.04)])
    assert 1 <= first.zoom_steps <= 3

    second = engine.update([pointer_hand(0.025)])
    assert -3 <= second.zoom_steps <= -1
    assert second.label == "zoom-out"




def test_pointer_and_drag_are_off_by_default():
    engine = GestureEngine(dict(CFG))
    result = engine.update([pointer_hand(0.12)])

    assert result.pointer is None
    assert result.left_down is None


def scale_hand(hand: Hand, scale: float, cx: float = 0.5, cy: float = 0.5) -> Hand:
    return Hand(
        tuple(
            Point(
                cx + (p.x - cx) * scale,
                cy + (p.y - cy) * scale,
                p.z * scale,
            )
            for p in hand.points
        ),
        hand.handedness,
    )


def one_noisy_folded_finger_hand() -> Hand:
    pts = list(pointer_hand(0.02).points)
    # One folded finger is misclassified as extended.
    pts[10] = Point(0.52, 0.48, 0.0)
    pts[12] = Point(0.52, 0.24, 0.0)
    return Hand(tuple(pts), "Right")


def invalid_transform_pose_hand() -> Hand:
    pts = list(one_noisy_folded_finger_hand().points)
    # A second finger is also extended, making the transform pose invalid.
    pts[14] = Point(0.60, 0.49, 0.0)
    pts[16] = Point(0.60, 0.23, 0.0)
    return Hand(tuple(pts), "Right")


def test_whole_hand_scale_change_does_not_create_zoom():
    engine = GestureEngine(dict(CFG))
    enter_transform(engine, 0.02)

    baseline = pointer_hand(0.02)
    larger = scale_hand(baseline, 1.35, cx=baseline[0].x, cy=baseline[0].y)
    out = engine.update([larger])

    assert out.zoom_steps == 0


def test_one_noisy_folded_finger_is_tolerated_live():
    engine = GestureEngine(dict(CFG))
    enter_transform(engine)

    noisy = engine.update([one_noisy_folded_finger_hand()])

    assert noisy.label == "transform"
    assert engine._transforming


def test_invalid_pose_gets_dropout_grace_instead_of_cancel():
    engine = GestureEngine(dict(CFG))
    enter_transform(engine)

    noisy = engine.update([invalid_transform_pose_hand()])
    assert noisy.label == "transform-hold"
    assert engine._transforming

    recovered = engine.update([pointer_hand(0.04)])
    assert recovered.zoom_steps > 0


def test_fast_pinch_open_can_emit_multiple_zoom_steps():
    engine = GestureEngine(dict(CFG))
    enter_transform(engine)

    out = engine.update([pointer_hand(0.055)])

    assert 1 <= out.zoom_steps <= 3


def test_rotation_preserves_one_degree_granularity():
    engine = GestureEngine(dict(CFG))
    enter_transform(engine)

    out1 = engine.update([pointer_hand(0.02, 1.1)])
    out2 = engine.update([pointer_hand(0.02, 2.1)])
    out3 = engine.update([pointer_hand(0.02, 3.1)])

    assert out1.rotate_steps == 1
    assert out2.rotate_steps == 1
    assert out3.rotate_steps == 1


def test_second_hand_blocks_zoom_completely():
    engine = GestureEngine(dict(CFG))

    out = engine.update([pointer_hand(0.02), pointer_hand(0.02)])

    assert out.label == "multi-hand-blocked"
    assert out.zoom_steps == 0
    assert not engine._transforming


def test_second_hand_cancels_active_zoom_session():
    engine = GestureEngine(dict(CFG))
    enter_transform(engine)
    assert engine._transforming

    blocked = engine.update([pointer_hand(0.04), pointer_hand(0.04)])

    assert blocked.label == "multi-hand-blocked"
    assert blocked.zoom_steps == 0
    assert not engine._transforming


def test_zoom_requires_exact_start_pose():
    engine = GestureEngine(dict(CFG))
    noisy = one_noisy_folded_finger_hand()

    first = engine.update([noisy])
    second = engine.update([noisy])

    assert first.label != "pinch-ready"
    assert second.label != "transform-ready"
    assert not engine._transforming
