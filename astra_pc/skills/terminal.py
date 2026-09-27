from __future__ import annotations

import shlex
import subprocess

from .base import Skill, SkillResult


class TerminalSkill(Skill):
    name = "terminal"
    description = "Run a small allowlist of diagnostic commands after permission checks."

    ALLOWED = {
        "pwd", "whoami", "uname", "uptime", "df", "free",
        "ls", "git", "python", "python3", "pytest",
    }

    def execute(self, action: str, args: dict) -> SkillResult:
        if action != "terminal_run":
            return SkillResult(False, f"Unknown terminal action: {action}")
        raw = str(args.get("command", "")).strip()
        if not raw:
            return SkillResult(False, "Missing command.")
        try:
            parts = shlex.split(raw)
        except ValueError as exc:
            return SkillResult(False, str(exc))
        if not parts or parts[0] not in self.ALLOWED:
            return SkillResult(False, "Command is outside Astra's terminal allowlist.")
        forbidden = (";", "&&", "||", "|", ">", "<", "$(")
        if any(x in raw for x in forbidden) or chr(96) in raw:
            return SkillResult(False, "Shell chaining/redirection is not allowed.")
        try:
            p = subprocess.run(
                parts,
                capture_output=True,
                text=True,
                timeout=max(1, min(30, int(args.get("timeout", 10)))),
                shell=False,
            )
        except Exception as exc:
            return SkillResult(False, str(exc))
        output = ((p.stdout or "") + ("\n" + p.stderr if p.stderr else "")).strip()
        return SkillResult(
            p.returncode == 0,
            output[:20000] or f"exit={p.returncode}",
            {"returncode": p.returncode},
        )
