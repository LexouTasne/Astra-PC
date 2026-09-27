from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass(slots=True)
class Event:
    name: str
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)


class EventBus:
    """Tiny thread-safe event bus used by the resident Astra core."""

    def __init__(self):
        self._q: queue.Queue[Event] = queue.Queue(maxsize=512)
        self._handlers: dict[str, list[Callable[[Event], None]]] = {}
        self._lock = threading.Lock()

    def publish(self, name: str, **payload: Any) -> None:
        event = Event(name=name, payload=payload)
        try:
            self._q.put_nowait(event)
        except queue.Full:
            try:
                self._q.get_nowait()
                self._q.put_nowait(event)
            except queue.Empty:
                pass

    def subscribe(self, name: str, handler: Callable[[Event], None]) -> None:
        with self._lock:
            self._handlers.setdefault(name, []).append(handler)

    def drain(self, limit: int = 64) -> int:
        handled = 0
        while handled < limit:
            try:
                event = self._q.get_nowait()
            except queue.Empty:
                break
            with self._lock:
                targets = list(self._handlers.get(event.name, ()))
                targets += list(self._handlers.get("*", ()))
            for handler in targets:
                try:
                    handler(event)
                except Exception:
                    pass
            handled += 1
        return handled
