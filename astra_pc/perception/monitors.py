from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any


@dataclass(slots=True)
class Monitor:
    x: int
    y: int
    width: int
    height: int
    name: str = ""
    primary: bool = False

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def get_monitors() -> list[Monitor]:
    try:
        from screeninfo import get_monitors as _get
        raw = _get()
        out = []
        for i, m in enumerate(raw):
            out.append(
                Monitor(
                    x=int(m.x),
                    y=int(m.y),
                    width=int(m.width),
                    height=int(m.height),
                    name=str(getattr(m, "name", "") or f"monitor-{i}"),
                    primary=bool(getattr(m, "is_primary", False)),
                )
            )
        return out
    except Exception:
        return []
