import json
from pathlib import Path


def test_text_brain_is_17b_fast_is_06b_and_vision_stays_vl():
    data = json.loads(Path("config/astra.json").read_text(encoding="utf-8"))
    ai = data["ai"]
    assert ai["text_model"] == "qwen3:1.7b"
    assert ai["vision_model"] == "qwen3-vl:2b-instruct"
    assert ai["fast_model"] == "qwen3:0.6b"
    assert ai["text_keep_alive"] == -1
    assert ai["strong_model"] == ""
