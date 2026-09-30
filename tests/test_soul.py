from astra_pc.ai.agent import AstraBrain
from astra_pc.ai.soul import load_soul, planner_soul, soul_path, voice_soul


def test_repo_soul_is_loaded():
    path = soul_path()
    assert path is not None
    assert path.name == "SOUL.md"
    text = load_soul()
    assert "Verdade acima de aparência" in text
    assert "Programação" in text
    assert "Nunca invente" in text


def test_text_system_prompt_contains_soul_and_context():
    prompt = AstraBrain._system("Janela: terminal")
    assert "SOUL DO ASTRA" in prompt
    assert "Nunca invente" in prompt
    assert "Janela: terminal" in prompt


def test_voice_soul_stays_compact():
    text = voice_soul()
    assert len(text) < 500
    assert "calma" in text
    assert "Ferramentas" in text


def test_planner_soul_stays_compact():
    text = planner_soul()
    assert len(text) < 500
    assert "ação mínima" in text
    assert "Não repita" in text
