import json
import time
from pathlib import Path

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


def test_rotation_action_decomposition_keeps_one_degree_precision():
    assert AstraViewport._rotation_actions(1) == [
        "AstraRotatePlus1"
    ]
    assert AstraViewport._rotation_actions(7) == [
        "AstraRotatePlus5",
        "AstraRotatePlus1",
        "AstraRotatePlus1",
    ]
    assert AstraViewport._rotation_actions(-21) == [
        "AstraRotateMinus15",
        "AstraRotateMinus5",
        "AstraRotateMinus1",
    ]


def test_viewport_rotation_is_non_blocking_and_degree_based():
    backend = Backend()
    viewport = AstraViewport(backend)
    calls = []
    viewport._rotation_effect_ready = True
    viewport._invoke_kwin_shortcut = lambda action: calls.append(action) or True

    try:
        started = time.perf_counter()
        assert viewport.rotate(7)
        elapsed = time.perf_counter() - started

        assert elapsed < 0.05
        assert viewport.rotation_degrees == 7

        deadline = time.monotonic() + 0.6
        while len(calls) < 3 and time.monotonic() < deadline:
            time.sleep(0.01)

        assert calls[:3] == [
            "AstraRotatePlus5",
            "AstraRotatePlus1",
            "AstraRotatePlus1",
        ]

        assert viewport.rotate(-2)
        assert viewport.rotation_degrees == 5
    finally:
        viewport.close()


def test_rotation_wraps_through_full_360_degrees():
    viewport = AstraViewport(Backend())
    viewport._rotation_effect_ready = True
    viewport._invoke_kwin_shortcut = lambda action: True
    try:
        viewport.rotate(359)
        assert viewport.rotation_degrees == 359
        viewport.rotate(2)
        assert viewport.rotation_degrees == 1
    finally:
        viewport.close()


def test_rotation_reset_uses_kwin_effect_action():
    viewport = AstraViewport(Backend())
    calls = []
    viewport._rotation_effect_ready = True
    viewport._invoke_kwin_shortcut = lambda action: calls.append(action) or True
    try:
        viewport.rotate(23)
        viewport.reset_rotation()

        deadline = time.monotonic() + 0.6
        while "AstraRotateReset" not in calls and time.monotonic() < deadline:
            time.sleep(0.01)

        assert viewport.rotation_degrees == 0
        assert "AstraRotateReset" in calls
    finally:
        viewport.close()


def test_kwin_rotation_package_declares_required_actions():
    root = Path(__file__).resolve().parents[1]
    package = root / "packaging" / "kwin" / "astra-rotation"
    meta = json.loads((package / "metadata.json").read_text(encoding="utf-8"))
    script = (package / "contents" / "code" / "main.js").read_text(
        encoding="utf-8"
    )

    assert meta["KPackageStructure"] == "KWin/Effect"
    assert meta["KPlugin"]["Id"] == "astra-rotation"

    for action in (
        "AstraRotatePlus1",
        "AstraRotateMinus1",
        "AstraRotatePlus5",
        "AstraRotateMinus5",
        "AstraRotatePlus15",
        "AstraRotateMinus15",
        "AstraRotateReset",
    ):
        assert action in script

    assert "Effect.Rotation" in script
    assert "Effect.Translation" in script
    assert "effects.stackingOrder" in script
