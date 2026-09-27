from astra_pc.core.planner import AstraPlanner


def test_open_app_fast_plan():
    plan = AstraPlanner._fast_plan("abra o navegador")
    assert plan["type"] == "skill"
    assert plan["skill"] == "apps"
    assert plan["action"] == "open_app"


def test_volume_fast_plan():
    plan = AstraPlanner._fast_plan("volume 35")
    assert plan["skill"] == "system"
    assert plan["action"] == "volume"
    assert plan["args"]["value"] == 35


def test_media_fast_plan():
    plan = AstraPlanner._fast_plan("próxima música")
    assert plan["action"] == "media"
    assert plan["args"]["command"] == "next"
