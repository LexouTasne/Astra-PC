import threading

from astra_pc.input.wayland_backend import YdotoolBackend


def backend_stub():
    obj = object.__new__(YdotoolBackend)
    obj._left_down = False
    obj._pending_wheel = 0
    obj._wheel_lock = threading.Lock()
    obj._wake = threading.Event()
    calls = []
    obj._queue_command = lambda *args: calls.append(args)
    return obj, calls


def test_left_button_uses_current_ydotool_masks():
    backend, calls = backend_stub()
    backend.left_button(True)
    backend.left_button(False)
    assert calls == [("click", "0x40"), ("click", "0x80")]


def test_scroll_coalesces_wheel_without_queueing_subprocesses():
    backend, calls = backend_stub()
    backend.scroll(3)
    backend.scroll(-1)
    assert calls == []
    assert backend._take_wheel() == 2


def test_atomic_left_click_uses_single_ydotool_event():
    backend, calls = backend_stub()
    backend.left_click()
    assert calls == [("click", "0xC0")]


def test_relative_mouse_motion_coalesces():
    backend, calls = backend_stub()
    backend._relative_move = (0, 0)

    backend.move_relative(4, -3)
    backend.move_relative(2, 1)

    assert calls == []
    assert backend._take_relative_move() == (6, -2)
