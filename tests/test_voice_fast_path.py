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
