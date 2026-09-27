from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any


@dataclass(slots=True)
class UIElement:
    name: str
    role: str
    x: int | None = None
    y: int | None = None
    width: int | None = None
    height: int | None = None
    value: str = ""
    enabled: bool = True
    focused: bool = False

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class AccessibilityProvider:
    def available(self) -> bool:
        return False

    def snapshot(self, limit: int = 120) -> list[UIElement]:
        return []
