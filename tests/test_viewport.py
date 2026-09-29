import time

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
    try:
        assert viewport.zoom(1)
        assert viewport.zoom(-1)
        assert viewport.reset_zoom()

        assert backend.hotkeys == [
            ["win", "+"],
            ["win", "-"],
            ["win", "0"],
        ]
    finally:
        viewport.close()


def test_viewport_rotation_is_non_blocking_and_quadrant_based():
    backend = Backend()
    viewport = AstraViewport(backend)
    calls = []
    viewport._apply_rotation_value = lambda quadrant: calls.append(quadrant) or True
    try:
        started = time.perf_counter()
        assert viewport.rotate(1)
        elapsed = time.perf_counter() - started

        assert elapsed < 0.05
        assert viewport.rotation_degrees == 90

        deadline = time.monotonic() + 0.6
        while not calls and time.monotonic() < deadline:
            time.sleep(0.01)

        assert calls[-1] == 1

        assert viewport.rotate(-1)
        assert viewport.rotation_degrees == 0
    finally:
        viewport.close()


def test_primary_output_can_be_detected_when_priority_is_on_output_line(monkeypatch):
    backend = Backend()
    viewport = AstraViewport(backend)

    class Result:
        returncode = 0
        stdout = (
            "Output: 1 HDMI-A-1 enabled connected priority 0\n"
            "Output: 2 DP-1 enabled connected priority 1\n"
        )

    monkeypatch.setattr("astra_pc.viewport.controller.platform.system", lambda: "Linux")
    monkeypatch.setattr("astra_pc.viewport.controller.shutil.which", lambda name: "/usr/bin/" + name)
    monkeypatch.setattr("astra_pc.viewport.controller.subprocess.run", lambda *a, **k: Result())
    try:
        primary, outputs = viewport._detect_outputs()
        assert primary == "2"
        assert outputs == ["1", "2"]
    finally:
        viewport.close()


def test_rotation_scope_all_updates_every_active_output(monkeypatch):
    backend = Backend()
    viewport = AstraViewport(backend, {"rotation_scope": "all"})
    calls = []

    class Result:
        returncode = 0

    monkeypatch.setattr("astra_pc.viewport.controller.platform.system", lambda: "Linux")
    monkeypatch.setattr("astra_pc.viewport.controller.shutil.which", lambda name: "/usr/bin/" + name)

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return Result()

    monkeypatch.setattr("astra_pc.viewport.controller.subprocess.run", fake_run)
    viewport._active_outputs = ["1", "2"]
    viewport._primary_output = "1"

    try:
        assert viewport._apply_rotation_value(1)
        assert calls[-1] == [
            "kscreen-doctor",
            "output.1.rotation.right",
            "output.2.rotation.right",
        ]
    finally:
        viewport.close()
