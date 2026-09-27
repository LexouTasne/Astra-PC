from __future__ import annotations

import subprocess
from pathlib import Path

from .base import Skill, SkillResult


class CodingSkill(Skill):
    name = "coding"
    description = "Inspect a local code project and run explicitly approved checks."

    def execute(self, action: str, args: dict) -> SkillResult:
        root = Path(args.get("root", ".")).expanduser().resolve()
        if not root.exists() or not root.is_dir():
            return SkillResult(False, "Project directory not found.")

        if action == "project_summary":
            files = []
            for path in root.rglob("*"):
                if len(files) >= 200:
                    break
                if path.is_file() and ".git" not in path.parts and "__pycache__" not in path.parts:
                    try:
                        files.append(str(path.relative_to(root)))
                    except Exception:
                        pass
            return SkillResult(True, "Project summary", {"root": str(root), "files": files})

        if action == "run_tests":
            for cmd in (["python", "-m", "pytest", "-q"], ["python3", "-m", "pytest", "-q"]):
                try:
                    p = subprocess.run(
                        cmd,
                        cwd=root,
                        capture_output=True,
                        text=True,
                        timeout=max(5, min(120, int(args.get("timeout", 60)))),
                    )
                    output = ((p.stdout or "") + ("\n" + p.stderr if p.stderr else "")).strip()
                    return SkillResult(
                        p.returncode == 0,
                        output[:30000] or f"exit={p.returncode}",
                        {"returncode": p.returncode},
                    )
                except FileNotFoundError:
                    continue
                except Exception as exc:
                    return SkillResult(False, str(exc))
            return SkillResult(False, "Python/pytest could not be started.")

        return SkillResult(False, f"Unknown coding action: {action}")
