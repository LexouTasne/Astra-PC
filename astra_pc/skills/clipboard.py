from __future__ import annotations

import pyperclip

from .base import Skill, SkillResult


class ClipboardSkill(Skill):
    name = "clipboard"
    description = "Read or replace the local clipboard."

    def execute(self, action: str, args: dict) -> SkillResult:
        if action == "clipboard_read":
            text = pyperclip.paste()
            return SkillResult(True, "Clipboard read.", {"text": text[:50000]})
        if action == "clipboard_write":
            text = str(args.get("text", ""))
            pyperclip.copy(text)
            return SkillResult(True, f"Copied {len(text)} characters.")
        return SkillResult(False, f"Unknown clipboard action: {action}")
