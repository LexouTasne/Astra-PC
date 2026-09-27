from __future__ import annotations

import re
import subprocess
import sys
import webbrowser
from dataclasses import dataclass


@dataclass(slots=True)
class CommandResult:
    handled: bool
    message: str


class CommandRouter:
    """Fast local intent router. No model or network call is required."""

    def execute(self, text: str) -> CommandResult:
        cmd = " ".join(text.lower().strip().split())

        if not cmd:
            return CommandResult(False, "")

        if re.search(r"\b(abra|abrir|open)\b.*\b(navegador|browser)\b", cmd):
            webbrowser.open("about:blank")
            return CommandResult(True, "Abrindo navegador.")

        if re.search(r"\b(terminal|console)\b", cmd) and re.search(r"\b(abra|abrir|open)\b", cmd):
            self._open_terminal()
            return CommandResult(True, "Abrindo terminal.")

        if re.search(r"\b(pausar|pause|parar controle)\b", cmd):
            return CommandResult(True, "pause_gestures")

        if re.search(r"\b(retomar|resume|continuar controle)\b", cmd):
            return CommandResult(True, "resume_gestures")

        return CommandResult(False, "Comando ainda não mapeado.")

    def _open_terminal(self) -> None:
        if sys.platform.startswith("win"):
            subprocess.Popen(["cmd.exe"])
            return
        for terminal in ("kgx", "konsole", "gnome-terminal", "xterm"):
            try:
                subprocess.Popen([terminal])
                return
            except FileNotFoundError:
                continue
