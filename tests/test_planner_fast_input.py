from astra_pc.core.planner import AstraPlanner


def test_mouse_move_fast_path():
    plan = AstraPlanner._fast_plan("mova o mouse pra 800, 400")
    assert plan == {
        "type": "skill",
        "skill": "input",
        "action": "mouse_move",
        "args": {"x": 800, "y": 400},
    }


def test_type_text_fast_path():
    plan = AstraPlanner._fast_plan("digite hello world")
    assert plan["skill"] == "input"
    assert plan["action"] == "type_text"
    assert plan["args"]["text"] == "hello world"


def test_spoken_hotkey_fast_path():
    plan = AstraPlanner._fast_plan("pressione ctrl c")
    assert plan["action"] == "hotkey"
    assert plan["args"]["keys"] == ["ctrl", "c"]


def test_global_zoom_fast_path():
    plan = AstraPlanner._fast_plan("aumenta o zoom")
    assert plan["skill"] == "viewport"
    assert plan["action"] == "zoom_in"
