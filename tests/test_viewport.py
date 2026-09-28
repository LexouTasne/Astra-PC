from astra_pc.viewport.controller import AstraViewport


class Backend:
    def __init__(self):
        self.hotkeys = []

    def hotkey(self, keys):
        self.hotkeys.append(list(keys))


def test_viewport_zoom_uses_global_meta_shortcuts():
    backend = Backend()
    viewport = AstraViewport(backend, {"zoom_step": 0.2})
    viewport._ensure_zoom_backend = lambda: None

    assert viewport.zoom(1)
    assert viewport.zoom(-1)
    assert viewport.reset_zoom()

    assert backend.hotkeys == [
        ["win", "+"],
        ["win", "-"],
        ["win", "0"],
    ]


def test_viewport_rotation_state_is_quadrant_based():
    backend = Backend()
    viewport = AstraViewport(backend)
    calls = []
    viewport._apply_rotation = lambda: calls.append(viewport.rotation_degrees) or True

    assert viewport.rotate(1)
    assert viewport.rotation_degrees == 90
    assert viewport.rotate(-1)
    assert viewport.rotation_degrees == 0
    assert calls == [90, 0]
