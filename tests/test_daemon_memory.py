from pathlib import Path


def test_daemon_conversation_memory_is_not_recursive():
    source = Path("astra_pc/core/daemon.py").read_text(encoding="utf-8")
    start = source.index("    def _remember_conversation")
    end = source.index("\n    def ", start + 8)
    body = source[start:end]
    assert "self.semantic.remember(" in body
    assert "self._background(self._remember_conversation" not in body
