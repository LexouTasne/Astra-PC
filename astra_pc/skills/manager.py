from __future__ import annotations

from typing import Any

from astra_pc.core.permissions import PermissionLayer

from .apps import AppsSkill
from .base import SkillResult
from .files import FilesSkill
from .git import GitSkill
from .system import SystemSkill


class SkillManager:
    def __init__(self, permissions: PermissionLayer | None = None):
        self.permissions = permissions or PermissionLayer()
        self.skills = {
            "apps": AppsSkill(),
            "system": SystemSkill(),
            "files": FilesSkill(),
            "git": GitSkill(),
        }

    def describe(self) -> list[dict[str, str]]:
        return [
            {"name": skill.name, "description": skill.description}
            for skill in self.skills.values()
        ]

    def execute(
        self,
        skill_name: str,
        action: str,
        args: dict[str, Any],
        *,
        confirmed: bool = False,
    ) -> SkillResult:
        skill = self.skills.get(skill_name)
        if skill is None:
            return SkillResult(False, f"Unknown skill: {skill_name}")

        decision = self.permissions.evaluate(action)
        if not decision.allowed:
            return SkillResult(False, decision.reason)
        if decision.needs_confirmation and not confirmed:
            return SkillResult(False, "confirmation required")

        return skill.execute(action, args)
