from __future__ import annotations

from typing import Any


class ReferenceResolver:
    REFERENTS = {
        "isso", "isto", "esse", "essa", "aquele", "aquela",
        "aqui", "this", "that", "here",
    }

    def resolve(
        self,
        text: str,
        *,
        active_window: str,
        accessibility: list[dict[str, Any]],
        pointer: tuple[int, int] | None = None,
    ) -> dict[str, Any]:
        words = set(text.lower().split())
        if not (words & self.REFERENTS):
            return {}

        focused = [e for e in accessibility if e.get("focused")]
        if focused:
            return {"source": "focused", "element": focused[0]}

        if pointer is not None:
            px, py = pointer
            inside = []
            for e in accessibility:
                x, y = e.get("x"), e.get("y")
                w, h = e.get("width"), e.get("height")
                if None in (x, y, w, h):
                    continue
                if x <= px <= x + w and y <= py <= y + h:
                    inside.append(e)
            if inside:
                inside.sort(key=lambda e: (e.get("width", 99999) * e.get("height", 99999)))
                return {"source": "pointer", "element": inside[0]}

        return {"source": "window", "active_window": active_window}
