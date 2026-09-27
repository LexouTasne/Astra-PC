from __future__ import annotations

from typing import Any

from astra_pc.core.memory import SessionMemory
from astra_pc.skills.manager import SkillManager


class RoutineManager:
    def __init__(self, memory: SessionMemory, skills: SkillManager):
        self.memory = memory
        self.skills = skills

    def save(self, name: str, steps: list[dict[str, Any]]) -> None:
        routines = self.memory.get("routines", {})
        routines[name.lower()] = steps
        self.memory.set("routines", routines)

    def list(self) -> list[str]:
        return sorted(self.memory.get("routines", {}).keys())

    def run(self, name: str, confirmed: bool = False) -> list[dict[str, Any]]:
        routines = self.memory.get("routines", {})
        steps = routines.get(name.lower())
        if not steps:
            return [{"ok": False, "message": f"Routine not found: {name}"}]

        results = []
        for step in steps:
            result = self.skills.execute(
                str(step.get("skill", "")),
                str(step.get("action", "")),
                dict(step.get("args", {})),
                confirmed=confirmed,
            )
            results.append({"ok": result.ok, "message": result.message, "data": result.data})
            if not result.ok:
                break
        return results
