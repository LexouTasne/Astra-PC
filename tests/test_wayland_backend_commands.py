from astra_pc.input.wayland_backend import YdotoolBackend


def backend_stub():
    obj = object.__new__(YdotoolBackend)
    obj._left_down = False
    calls = []
    obj._queue_command = lambda *args: calls.append(args)
    return obj, calls


def test_left_button_uses_current_ydotool_masks():
    backend, calls = backend_stub()
    backend.left_button(True)
    backend.left_button(False)
    assert calls == [("click", "0x40"), ("click", "0x80")]


def test_scroll_uses_mousemove_wheel_not_removed_mousewheel_command():
    backend, calls = backend_stub()
    backend.scroll(3)
    assert calls == [("mousemove", "--wheel", "--", "0", "3")]


def test_atomic_left_click_uses_single_ydotool_event():
    backend, calls = backend_stub()
    backend.left_click()
    assert calls == [("click", "0xC0")]
