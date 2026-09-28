from astra_pc.voice.piper_tts import resolve_piper_model


def test_piper_resolver_accepts_explicit_model(tmp_path):
    model = tmp_path / "voice.onnx"
    model.write_bytes(b"model")
    assert resolve_piper_model(model) == model
