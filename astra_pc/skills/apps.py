from __future__ import annotations

import os
import platform
import shutil
import subprocess
import webbrowser

from .base import Skill, SkillResult


class AppsSkill(Skill):
    name = "apps"
    description = "Open common applications and URLs."

    APP_ALIASES = {
        "browser": ["firefox", "google-chrome", "chromium", "brave-browser"],
        "navegador": ["firefox", "google-chrome", "chromium", "brave-browser"],
        "chrome": ["google-chrome", "chrome", "chromium"],
        "firefox": ["firefox"],
        "discord": ["discord", "Discord"],
        "spotify": ["spotify", "Spotify"],
        "vscode": ["code", "code-insiders"],
        "codigo": ["code", "code-insiders"],
        "código": ["code", "code-insiders"],
        "terminal": ["konsole", "gnome-terminal", "kgx", "xterm"],
    }

    def execute(self, action: str, args: dict) -> SkillResult:
        if action == "open_url":
            url = str(args.get("url", ""))
            if not url.startswith(("http://", "https://")):
                return SkillResult(False, "Only http/https URLs are supported.")
            webbrowser.open(url)
            return SkillResult(True, f"Opened {url}")

        if action != "open_app":
            return SkillResult(False, f"Unknown apps action: {action}")

        name = str(args.get("name", "")).lower().strip()
        if not name:
            return SkillResult(False, "Missing app name.")

        if platform.system() == "Windows":
            try:
                os.startfile(name)  # type: ignore[attr-defined]
                return SkillResult(True, f"Opened {name}")
            except Exception:
                pass

        for candidate in self.APP_ALIASES.get(name, [name]):
            exe = shutil.which(candidate)
            if exe:
                subprocess.Popen(
                    [exe],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
                return SkillResult(True, f"Opened {name}")

        return SkillResult(False, f"Application not found: {name}")
