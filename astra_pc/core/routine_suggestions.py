from __future__ import annotations

from collections import Counter

from astra_pc.core.memory import SessionMemory


class RoutineSuggestionEngine:
    """Finds repeated short window transitions and suggests, but never creates, routines."""

    def __init__(self, memory: SessionMemory):
        self.memory = memory

    def suggest(self, minimum_repeats: int = 3) -> list[dict]:
        contexts = [
            str(e.get("data", {}).get("active_window", ""))
            for e in self.memory.recent(500)
            if e.get("kind") == "context"
        ]
        contexts = [x for x in contexts if x]
        triples = Counter(
            tuple(contexts[i:i+3])
            for i in range(max(0, len(contexts) - 2))
            if len(set(contexts[i:i+3])) > 1
        )
        return [
            {"sequence": list(seq), "repeats": count}
            for seq, count in triples.most_common(8)
            if count >= minimum_repeats
        ]
