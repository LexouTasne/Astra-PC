from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class SkillResult:
    ok: bool
    message: str
    data: dict[str, Any] | None = None


class Skill:
    name = "skill"
    description = ""

    def execute(self, action: str, args: dict[str, Any]) -> SkillResult:
        raise NotImplementedError
