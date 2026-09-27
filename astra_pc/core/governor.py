from __future__ import annotations

from dataclasses import dataclass

import psutil


@dataclass(slots=True)
class PerformanceState:
    mode: str
    cpu: float
    ram: float
    video_frames: int
    vision_max_width: int


class PerformanceGovernor:
    """Adapts expensive perception work to current machine load."""

    def __init__(self, cpu_high: float = 85.0, ram_high: float = 88.0):
        self.cpu_high = cpu_high
        self.ram_high = ram_high

    def state(self) -> PerformanceState:
        cpu = float(psutil.cpu_percent(interval=None))
        ram = float(psutil.virtual_memory().percent)
        if cpu >= self.cpu_high or ram >= self.ram_high:
            return PerformanceState("eco", cpu, ram, 4, 640)
        if cpu < 45 and ram < 72:
            return PerformanceState("performance", cpu, ram, 8, 1080)
        return PerformanceState("balanced", cpu, ram, 6, 960)
