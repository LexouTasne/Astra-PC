from __future__ import annotations

import subprocess
from pathlib import Path

from .base import Skill, SkillResult


class GitSkill(Skill):
    name = "git"
    description = "Inspect Git repositories and create confirmed commits."

    def execute(self, action: str, args: dict) -> SkillResult:
        repo = Path(args.get("repo", ".")).expanduser().resolve()
        if not (repo / ".git").exists():
            return SkillResult(False, f"Not a Git repository: {repo}")

        if action == "git_status":
            return self._run(repo, ["git", "status", "--short", "--branch"])
        if action == "git_diff":
            return self._run(repo, ["git", "diff", "--stat"])
        if action == "git_branch":
            return self._run(repo, ["git", "branch", "--show-current"])
        if action == "git_commit":
            message = str(args.get("message", "")).strip()
            if not message:
                return SkillResult(False, "Commit message is required.")
            return self._run(repo, ["git", "commit", "-am", message])

        return SkillResult(False, f"Unknown git action: {action}")

    @staticmethod
    def _run(repo: Path, cmd: list[str]) -> SkillResult:
        try:
            p = subprocess.run(
                cmd,
                cwd=repo,
                capture_output=True,
                text=True,
                timeout=8,
            )
        except Exception as exc:
            return SkillResult(False, str(exc))
        output = (p.stdout or p.stderr).strip()
        return SkillResult(p.returncode == 0, output or "OK", {"returncode": p.returncode})
