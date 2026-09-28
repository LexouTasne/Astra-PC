from astra_pc.ai.ollama_client import OllamaClient


def test_numeric_string_keep_alive_becomes_number():
    client = OllamaClient("qwen3:0.6b", keep_alive="-1")
    assert client.keep_alive == -1
    assert isinstance(client.keep_alive, int)


def test_duration_keep_alive_stays_duration():
    client = OllamaClient("qwen3:0.6b", keep_alive="5m")
    assert client.keep_alive == "5m"
