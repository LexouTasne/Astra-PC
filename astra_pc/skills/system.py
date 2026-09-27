from __future__ import annotations

import os
import platform
import shutil
import subprocess

from .base import Skill, SkillResult


class SystemSkill(Skill):
    name = "system"
    description = "Read system status and perform safe system actions."

    def execute(self, action: str, args: dict) -> SkillResult:
        if action == "status":
            return SkillResult(
                True,
                "System status",
                {
                    "os": platform.platform(),
                    "cpu_count": os.cpu_count(),
                    "machine": platform.machine(),
                    "python": platform.python_version(),
                },
            )

        if action == "volume":
            value = max(0, min(100, int(args.get("value", 50))))
            if platform.system() == "Linux":
                if shutil.which("wpctl"):
                    p = subprocess.run(
                        ["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", f"{value}%"],
                        capture_output=True,
                        text=True,
                    )
                    return SkillResult(p.returncode == 0, f"Volume {value}%")
                if shutil.which("pactl"):
                    p = subprocess.run(
                        ["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{value}%"],
                        capture_output=True,
                        text=True,
                    )
                    return SkillResult(p.returncode == 0, f"Volume {value}%")
            return SkillResult(False, "No supported volume backend found.")

        return SkillResult(False, f"Unknown system action: {action}")
