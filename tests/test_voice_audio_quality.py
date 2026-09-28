import numpy as np

from astra_pc.voice.assistant import AstraVoiceAssistant, FastSpeaker
from astra_pc.voice.fast_whisper import FastWhisperVoiceEngine


def test_tts_cleanup_removes_markdown_and_urls():
    text = FastSpeaker._clean_for_speech(
        "Olha **isso** em `arquivo.txt`: https://example.com/test"
    )
    assert "**" not in text
    assert "`" not in text
    assert "https://" not in text
    assert "arquivo.txt" in text
    assert "link" in text


def test_quiet_speech_conditioning_adds_conservative_gain():
    source = (np.sin(np.linspace(0, 20, 16000)) * 0.02).astype(np.float32)
    conditioned = FastWhisperVoiceEngine._condition_audio(source)
    before = float(np.sqrt(np.mean(source**2)))
    after = float(np.sqrt(np.mean(conditioned**2)))
    assert after > before
    assert float(np.max(np.abs(conditioned))) <= 0.98


def test_near_silence_is_not_aggressively_amplified():
    source = np.full(1600, 0.001, dtype=np.float32)
    conditioned = FastWhisperVoiceEngine._condition_audio(source)
    assert float(np.max(np.abs(conditioned))) < 0.003


def test_astra_wake_word_accepts_common_dropped_r_transcription():
    assistant = object.__new__(AstraVoiceAssistant)
    assistant.wake_word = "astra"
    match = assistant._wake_match("Asta fecha o Discord")
    assert match is not None
    assert match.group(0).lower() == "asta"


def test_prompt_echo_is_rejected_as_hallucination():
    engine = object.__new__(FastWhisperVoiceEngine)
    engine.initial_prompt = "Português do Brasil. Assistente Astra."
    assert engine._is_hallucination(
        "O que a pessoa disser, incluindo nomes de programas, caminhos, números e comandos, sem completar frases.",
        -0.44,
        0.02,
    )


def test_common_whisper_noise_caption_is_rejected():
    engine = object.__new__(FastWhisperVoiceEngine)
    engine.initial_prompt = "Português do Brasil. Assistente Astra."
    assert engine._is_hallucination(
        "Se inscreva no canal e se inscreva no canal.",
        -1.12,
        0.02,
    )


def test_real_app_command_is_not_rejected():
    engine = object.__new__(FastWhisperVoiceEngine)
    engine.initial_prompt = "Português do Brasil. Assistente Astra."
    assert not engine._is_hallucination(
        "Fecha o Discord.",
        -0.58,
        0.02,
    )
