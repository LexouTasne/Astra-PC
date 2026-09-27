from astra_pc.core.semantic_memory import SemanticMemory


def test_semantic_memory_lexical_fallback(tmp_path):
    memory = SemanticMemory(tmp_path / "memory.db", embeddings=None)
    memory.remember("Practice client update failed in Git", kind="dev")
    memory.remember("The weather is sunny", kind="other")
    results = memory.search("Practice Git update", limit=2)
    assert results
    assert "Practice" in results[0]["text"]
