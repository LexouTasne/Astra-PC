from astra_pc.core.memory import SessionMemory


def test_memory_roundtrip(tmp_path):
    memory = SessionMemory(tmp_path / "astra.db")
    memory.set("profile", "dev")
    assert memory.get("profile") == "dev"
    memory.add("event", {"name": "test"})
    recent = memory.recent(1)
    assert recent[0]["kind"] == "event"
    assert recent[0]["data"]["name"] == "test"
