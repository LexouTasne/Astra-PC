from astra_pc.core.planner import AstraPlanner
from astra_pc.voice.commands import CommandRouter


def test_simple_math_is_instant():
    result = CommandRouter().execute("quanto é um mais um?")
    assert result.handled
    assert result.message == "É 2."


def test_normal_question_skips_desktop_planner():
    assert not AstraPlanner.needs_planning("quanto é um mais um?")
    assert not AstraPlanner.needs_planning("me explica o que é uma CPU")


def test_desktop_action_uses_planner():
    assert AstraPlanner.needs_planning("abra o navegador")
    assert AstraPlanner.needs_planning("volume 30")
    assert AstraPlanner.needs_planning("rode os testes")


def test_colloquial_math_is_instant():
    result = CommandRouter().execute("quanto que é um mais um?")
    assert result.handled
    assert result.message == "É 2."


def test_embedded_close_discord_is_action():
    assert AstraPlanner.needs_planning("eu pedi para você fechar o Discord")
    plan = AstraPlanner._fast_plan("eu pedi para você fechar o Discord")
    assert plan == {
        "type": "skill",
        "skill": "apps",
        "action": "close_app",
        "args": {"name": "discord"},
    }


def test_time_question_is_local_fast_path():
    result = CommandRouter().execute("que horas são?")
    assert result.handled
    assert result.message.startswith("Agora ")


def test_spoken_time_1830_is_natural_ptbr():
    assert CommandRouter._format_time(18, 30) == "Agora são seis e meia da tarde."


def test_spoken_time_1831_is_natural_ptbr():
    assert CommandRouter._format_time(18, 31) == "Agora são seis e trinta e um da tarde."


def test_spoken_time_1300_uses_singular():
    assert CommandRouter._format_time(13, 0) == "Agora é uma da tarde."


def test_spoken_time_special_cases():
    assert CommandRouter._format_time(0, 0) == "Agora é meia-noite."
    assert CommandRouter._format_time(12, 30) == "Agora é meio-dia e meia."


def test_instant_identity_replies_do_not_need_model():
    router = CommandRouter()
    assert router.execute("qual seu nome?").message == "Meu nome é Astra."
    assert "Richard Mateus" in router.execute("quem te criou?").message


def test_instant_presence_reply():
    assert CommandRouter().execute("Astra, tá aí?").message == "Tô aqui."
