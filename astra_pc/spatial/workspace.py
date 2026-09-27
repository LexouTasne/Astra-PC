from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class Transform:
    position: list[float] = field(default_factory=lambda: [0.0, 0.0, 0.0])
    rotation: list[float] = field(default_factory=lambda: [0.0, 0.0, 0.0])
    scale: list[float] = field(default_factory=lambda: [1.0, 1.0, 1.0])


@dataclass(slots=True)
class SpatialObject:
    object_id: str
    kind: str
    transform: Transform = field(default_factory=Transform)
    metadata: dict[str, Any] = field(default_factory=dict)
    grabbed_by: str | None = None


class SpatialWorkspace:
    """Renderer-independent spatial state shared by desktop HUD and future OpenXR."""

    def __init__(self):
        self.objects: dict[str, SpatialObject] = {}

    def add(self, obj: SpatialObject) -> None:
        self.objects[obj.object_id] = obj

    def remove(self, object_id: str) -> None:
        self.objects.pop(object_id, None)

    def grab(self, object_id: str, hand: str) -> bool:
        obj = self.objects.get(object_id)
        if not obj or (obj.grabbed_by and obj.grabbed_by != hand):
            return False
        obj.grabbed_by = hand
        return True

    def release(self, object_id: str) -> None:
        obj = self.objects.get(object_id)
        if obj:
            obj.grabbed_by = None

    def translate(self, object_id: str, dx: float, dy: float, dz: float = 0.0) -> None:
        obj = self.objects[object_id]
        obj.transform.position[0] += dx
        obj.transform.position[1] += dy
        obj.transform.position[2] += dz

    def rotate(self, object_id: str, rx: float = 0.0, ry: float = 0.0, rz: float = 0.0) -> None:
        obj = self.objects[object_id]
        obj.transform.rotation[0] += rx
        obj.transform.rotation[1] += ry
        obj.transform.rotation[2] += rz

    def scale(self, object_id: str, factor: float) -> None:
        obj = self.objects[object_id]
        factor = max(0.05, min(20.0, factor))
        obj.transform.scale = [max(0.01, x * factor) for x in obj.transform.scale]

    def snapshot(self) -> list[dict[str, Any]]:
        return [
            {
                "id": o.object_id,
                "kind": o.kind,
                "position": o.transform.position,
                "rotation": o.transform.rotation,
                "scale": o.transform.scale,
                "grabbed_by": o.grabbed_by,
                "metadata": o.metadata,
            }
            for o in self.objects.values()
        ]
