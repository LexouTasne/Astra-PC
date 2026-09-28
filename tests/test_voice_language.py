from astra_pc.ai.agent import SYSTEM_PROMPT
from astra_pc.voice.assistant import AstraVoiceAssistant


def test_system_prompt_forces_brazilian_portuguese():
    prompt = SYSTEM_PROMPT.lower()
    assert "português do brasil" in prompt
    assert "nunca responda em inglês" in prompt


def test_english_leak_detector():
    assert AstraVoiceAssistant._looks_english("I'm here to assist you with your request.")
    assert not AstraVoiceAssistant._looks_english("Estou aqui para ajudar com seu pedido.")
    assert not AstraVoiceAssistant._looks_english("CPU, RAM e GPU estão normais.")
