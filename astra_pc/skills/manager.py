from __future__ import annotations

from pathlib import Path
from typing import Any

from astra_pc.core.permissions import PermissionLayer

from .apps import AppsSkill
from .base import SkillResult
from .clipboard import ClipboardSkill
from .coding import CodingSkill
from .discovery import discover_skills
from .files import FilesSkill
from .git import GitSkill
from .notifications import NotificationsSkill
from .system import SystemSkill
from .terminal import TerminalSkill


class SkillManager:
    def __init__(
        self,
        permissions: PermissionLayer | None = None,
        plugin_dir: str | Path | None = None,
    ):
        self.permissions = permissions or PermissionLayer()
        builtins = [
            AppsSkill(),
            SystemSkill(),
            FilesSkill(),
            GitSkill(),
            ClipboardSkill(),
            NotificationsSkill(),
            TerminalSkill(),
            CodingSkill(),
        ]
        self.skills = {skill.name: skill for skill in builtins}
        if plugin_dir:
            for skill in discover_skills(plugin_dir):
                self.skills[skill.name] = skill

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
            safe = set(getattr(skill, "safe_actions", ()))
            confirm = set(getattr(skill, "confirm_actions", ()))
            if action in safe:
                pass
            elif action in confirm:
                if not confirmed:
                    return SkillResult(False, "confirmation required")
            else:
                return SkillResult(False, decision.reason)
        elif decision.needs_confirmation and not confirmed:
            return SkillResult(False, "confirmation required")

        return skill.execute(action, args)
