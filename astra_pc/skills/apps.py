from __future__ import annotations

import os
import platform
import shutil
import subprocess
import webbrowser

from .base import Skill, SkillResult


class AppsSkill(Skill):
    name = "apps"
    description = "Open/close common applications and URLs."
    safe_actions = ("open_app", "open_url", "close_app")

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

        if action not in {"open_app", "close_app"}:
            return SkillResult(False, f"Unknown apps action: {action}")

        name = str(args.get("name", "")).lower().strip()
        if not name:
            return SkillResult(False, "Missing app name.")

        if action == "close_app":
            return self._close_app(name)

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


    def _close_app(self, name: str) -> SkillResult:
        candidates = self.APP_ALIASES.get(name, [name])
        system = platform.system()

        if system == "Windows":
            for candidate in candidates:
                image = candidate if candidate.lower().endswith(".exe") else candidate + ".exe"
                p = subprocess.run(
                    ["taskkill", "/IM", image],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
                if p.returncode == 0:
                    return SkillResult(True, f"Fechei {name}.")
            return SkillResult(False, f"Não encontrei {name} em execução.")

        if system in {"Linux", "Darwin"}:
            for candidate in candidates:
                p = subprocess.run(
                    ["pkill", "-x", candidate],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
                if p.returncode == 0:
                    return SkillResult(True, f"Fechei {name}.")
            return SkillResult(False, f"Não encontrei {name} em execução.")

        return SkillResult(False, "Fechar aplicativos não é suportado neste sistema.")
