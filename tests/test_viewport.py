import time

from astra_pc.viewport.controller import AstraViewport


class Backend:
    def __init__(self):
        self.hotkeys = []

    def hotkey(self, keys):
        self.hotkeys.append(list(keys))


def wait_until(predicate, timeout=1.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return bool(predicate())


def test_zoom_runs_outside_camera_thread_and_coalesces():
    viewport = AstraViewport(None, {"zoom_step": 0.1})
    calls = []
    viewport._ensure_zoom_backend = lambda: None
    viewport._apply_zoom_action = lambda direction: calls.append(direction) or True

    try:
        assert viewport.zoom(1)
        assert viewport.zoom(1)
        assert viewport.zoom(1)

        assert wait_until(lambda: len(calls) >= 1)
        assert calls
        assert all(item == 1 for item in calls)
        assert len(calls) <= 3
    finally:
        viewport.close()


def test_zoom_worker_exception_does_not_die_or_escape():
    viewport = AstraViewport(None)
    calls = {"count": 0}

    def flaky(_direction):
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("synthetic zoom failure")
        return True

    viewport._ensure_zoom_backend = lambda: None
    viewport._apply_zoom_action = flaky

    try:
        assert viewport.zoom(1)
        assert wait_until(lambda: calls["count"] >= 1)

        # A later gesture is still accepted: the worker survived the failure.
        assert viewport.zoom(1)
        assert wait_until(lambda: calls["count"] >= 2)
        assert viewport._zoom_worker.is_alive()
    finally:
        viewport.close()


def test_reset_zoom_waits_for_worker_ack_and_returns_to_one():
    viewport = AstraViewport(None, {"zoom_step": 0.1})
    calls = []
    viewport._ensure_zoom_backend = lambda: None
    viewport._apply_zoom_action = lambda direction: calls.append(direction) or True

    try:
        viewport.zoom(1)
        assert wait_until(lambda: 1 in calls)

        assert viewport.reset_zoom(wait=True)
        assert 0 in calls
        assert viewport.zoom_level == 1.0
        assert viewport._zoom_reset_done.is_set()
    finally:
        viewport.close()


def test_close_always_requests_actual_size_before_worker_stops():
    viewport = AstraViewport(None)
    calls = []
    viewport._ensure_zoom_backend = lambda: None
    viewport._apply_zoom_action = lambda direction: calls.append(direction) or True

    viewport.close()

    assert 0 in calls
    assert viewport.zoom_level == 1.0
    assert not viewport._zoom_worker.is_alive()


def test_zoom_queue_is_bounded():
    viewport = AstraViewport(None)
    viewport._ensure_zoom_backend = lambda: None
    viewport._apply_zoom_action = lambda _direction: (time.sleep(0.08) or True)

    try:
        for _ in range(100):
            viewport.zoom(3)

        with viewport._lock:
            assert -6 <= viewport._zoom_pending <= 6
    finally:
        viewport.close()
