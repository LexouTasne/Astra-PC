import numpy as np

from astra_pc.voice.fast_whisper import FastWhisperVoiceEngine


def test_native_48k_frame_resamples_to_16k():
    engine = object.__new__(FastWhisperVoiceEngine)
    engine.capture_rate = 48000
    engine.sample_rate = 16000
    source = (np.sin(np.linspace(0, 6.28, 1440)) * 12000).astype(np.int16)
    converted = engine._to_target_rate(source.tobytes())
    out = np.frombuffer(converted, dtype=np.int16)
    assert len(out) == 480
