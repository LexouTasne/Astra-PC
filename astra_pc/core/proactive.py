from __future__ import annotations

import time

import psutil

from astra_pc.core.events import EventBus


class ProactiveMonitor:
    """Lightweight threshold monitor. Publishes events; never takes risky action."""

    def __init__(
        self,
        bus: EventBus,
        *,
        cpu_threshold: float = 92.0,
        ram_threshold: float = 92.0,
        interval: float = 5.0,
    ):
        self.bus = bus
        self.cpu_threshold = cpu_threshold
        self.ram_threshold = ram_threshold
        self.interval = interval
        self._last: dict[str, float] = {}

    def tick(self) -> None:
        cpu = float(psutil.cpu_percent(interval=None))
        ram = float(psutil.virtual_memory().percent)
        now = time.time()

        self._emit_limited("system.cpu_high", cpu, self.cpu_threshold, now)
        self._emit_limited("system.ram_high", ram, self.ram_threshold, now)

    def _emit_limited(
        self,
        name: str,
        value: float,
        threshold: float,
        now: float,
    ) -> None:
        if value < threshold:
            return
        if now - self._last.get(name, 0.0) < 60.0:
            return
        self._last[name] = now
        self.bus.publish(name, value=value, threshold=threshold)
