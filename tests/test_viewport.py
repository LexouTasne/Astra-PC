from astra_pc.viewport.controller import AstraViewport


class Backend:
    def __init__(self):
        self.hotkeys = []

    def hotkey(self, keys):
        self.hotkeys.append(list(keys))


def test_viewport_zoom_uses_global_meta_shortcuts_as_fallback():
    backend = Backend()
    viewport = AstraViewport(backend, {"zoom_step": 0.2})
    viewport._ensure_zoom_backend = lambda: None
    viewport._kglobalaccel_zoom = False

    assert viewport.zoom(1)
    assert viewport.zoom(-1)
    assert viewport.reset_zoom()

    assert backend.hotkeys == [
        ["win", "+"],
        ["win", "-"],
        ["win", "0"],
    ]


def test_viewport_zoom_bounds_are_respected():
    backend = Backend()
    viewport = AstraViewport(
        backend,
        {
            "zoom_step": 0.1,
            "zoom_min": 1.0,
            "zoom_max": 1.21,
        },
    )
    viewport._ensure_zoom_backend = lambda: None
    viewport._kglobalaccel_zoom = False

    assert viewport.zoom(1)
    assert viewport.zoom(1)
    assert not viewport.zoom(1)
    assert viewport.zoom_level <= 1.21


def test_viewport_close_is_noop():
    AstraViewport(Backend()).close()
