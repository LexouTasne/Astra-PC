import json
from pathlib import Path


def test_2b_is_primary_and_06b_is_fast_only():
    data = json.loads(Path("config/astra.json").read_text(encoding="utf-8"))
    ai = data["ai"]
    assert ai["text_model"] == "qwen3-vl:2b-instruct"
    assert ai["vision_model"] == "qwen3-vl:2b-instruct"
    assert ai["fast_model"] == "qwen3:0.6b"
    assert ai["strong_model"] == ""
