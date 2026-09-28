from astra_pc.vision.hands import HandTracker
from astra_pc.vision.types import Point


def tracker_stub(alpha=0.5, snap=0.1):
    tracker = object.__new__(HandTracker)
    tracker._smoothing = alpha
    tracker._snap_distance = snap
    tracker._previous = {}
    return tracker


def test_landmark_smoothing_reduces_small_jitter():
    tracker = tracker_stub(alpha=0.5, snap=0.1)
    base = tuple(Point(0.5, 0.5, 0.0) for _ in range(21))
    moved = tuple(Point(0.52, 0.48, 0.0) for _ in range(21))

    tracker._smooth("Right", base)
    result = tracker._smooth("Right", moved)

    assert abs(result[0].x - 0.51) < 1e-6
    assert abs(result[0].y - 0.49) < 1e-6


def test_landmark_smoothing_snaps_to_deliberate_large_motion():
    tracker = tracker_stub(alpha=0.5, snap=0.05)
    base = tuple(Point(0.2, 0.2, 0.0) for _ in range(21))
    moved = tuple(Point(0.5, 0.5, 0.0) for _ in range(21))

    tracker._smooth("Right", base)
    result = tracker._smooth("Right", moved)

    assert result[0] == moved[0]
