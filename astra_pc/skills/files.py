from __future__ import annotations

import fnmatch
from pathlib import Path

from .base import Skill, SkillResult


class FilesSkill(Skill):
    name = "files"
    description = "Search and inspect files inside the user's home directory."

    def __init__(self):
        self.home = Path.home().resolve()

    def execute(self, action: str, args: dict) -> SkillResult:
        if action == "search_files":
            pattern = str(args.get("pattern", "*")).strip() or "*"
            limit = max(1, min(100, int(args.get("limit", 25))))
            root = self._safe_path(args.get("root") or self.home)
            if root is None or not root.exists():
                return SkillResult(False, "Invalid search root.")

            found = []
            try:
                for path in root.rglob("*"):
                    if len(found) >= limit:
                        break
                    if path.is_file() and fnmatch.fnmatch(path.name.lower(), pattern.lower()):
                        found.append(str(path))
            except PermissionError:
                pass
            return SkillResult(True, f"Found {len(found)} file(s).", {"files": found})

        if action == "read_file":
            path = self._safe_path(args.get("path"))
            if path is None or not path.is_file():
                return SkillResult(False, "File not found or outside home directory.")
            if path.stat().st_size > 1_000_000:
                return SkillResult(False, "File is too large for quick text reading.")
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except Exception as exc:
                return SkillResult(False, str(exc))
            return SkillResult(True, f"Read {path.name}", {"text": text[:50_000]})

        return SkillResult(False, f"Unknown files action: {action}")

    def _safe_path(self, raw) -> Path | None:
        try:
            path = Path(raw).expanduser().resolve()
            path.relative_to(self.home)
            return path
        except Exception:
            return None
