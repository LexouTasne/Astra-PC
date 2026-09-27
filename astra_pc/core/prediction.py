from __future__ import annotations

from collections import Counter

from astra_pc.core.memory import SessionMemory


class PredictionEngine:
    """Suggests likely next context from past transitions; never executes it."""

    def __init__(self, memory: SessionMemory):
        self.memory = memory

    def next_windows(self, active_window: str, limit: int = 3) -> list[dict]:
        events = [
            e for e in self.memory.recent(250)
            if e.get("kind") == "context"
        ]
        transitions: Counter[str] = Counter()
        previous = None
        for event in events:
            window = str(event.get("data", {}).get("active_window", ""))
            if previous == active_window and window and window != active_window:
                transitions[window] += 1
            previous = window
        return [
            {"window": name, "count": count}
            for name, count in transitions.most_common(limit)
        ]
