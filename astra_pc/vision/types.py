from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True, frozen=True)
class Point:
    x: float
    y: float
    z: float


@dataclass(slots=True)
class Hand:
    points: tuple[Point, ...]
    handedness: str

    def __getitem__(self, index: int) -> Point:
        return self.points[index]
