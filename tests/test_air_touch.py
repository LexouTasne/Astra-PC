from astra_pc.core.runtime import AstraRuntime


class Backend:
    def __init__(self):
        self.moves = []
        self.absolute = []

    def move_relative(self, dx, dy):
        self.moves.append((dx, dy))

    def move(self, x, y):
        self.absolute.append((x, y))


def runtime_stub():
    rt = object.__new__(AstraRuntime)
    rt.backend = Backend()
    rt.air_touch_gain = 1.15
    rt.air_touch_deadzone = 0.0028
    rt.air_touch_accel = 1.8
    rt.air_touch_max_step = 82
    rt.air_touch_jump_threshold = 0.11
    rt._air_touch_last = None
    rt._air_touch_missing = 0
    rt._smooth_xy = None
    rt.margin = 0.1
    rt.smoothing = 0.42
    rt.deadzone = 1.0
    rt.screen_origin = (0, 0)
    return rt


def test_air_touch_first_frame_only_anchors():
    rt = runtime_stub()

    rt._move_air_touch((0.50, 0.50), 1920, 1080)

    assert rt.backend.moves == []


def test_air_touch_ignores_small_tremor():
    rt = runtime_stub()
    rt._move_air_touch((0.50, 0.50), 1920, 1080)

    rt._move_air_touch((0.501, 0.501), 1920, 1080)

    assert rt.backend.moves == []


def test_air_touch_moves_relative_for_deliberate_motion():
    rt = runtime_stub()
    rt._move_air_touch((0.50, 0.50), 1920, 1080)

    rt._move_air_touch((0.515, 0.50), 1920, 1080)

    assert len(rt.backend.moves) == 1
    dx, dy = rt.backend.moves[0]
    assert dx > 0
    assert dy == 0


def test_air_touch_tracking_jump_reanchors_without_mouse_jump():
    rt = runtime_stub()
    rt._move_air_touch((0.20, 0.20), 1920, 1080)

    rt._move_air_touch((0.90, 0.90), 1920, 1080)

    assert rt.backend.moves == []
    assert rt._air_touch_last == (0.90, 0.90)


def test_air_touch_reset_prevents_reentry_teleport():
    rt = runtime_stub()
    rt._move_air_touch((0.20, 0.20), 1920, 1080)
    rt._reset_air_touch()

    rt._move_air_touch((0.80, 0.80), 1920, 1080)

    assert rt.backend.moves == []
