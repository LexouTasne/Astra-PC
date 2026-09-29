from __future__ import annotations

import platform
import shutil
import subprocess

from astra_pc.config import load_config

from .base import Skill, SkillResult


class NotificationsSkill(Skill):
    name = "notifications"
    description = "Show local desktop notifications."

    def execute(self, action: str, args: dict) -> SkillResult:
        try:
            if not bool(load_config().data.get("notifications", {}).get("enabled", True)):
                return SkillResult(False, "notifications disabled")
        except Exception:
            pass
        if action != "notify":
            return SkillResult(False, f"Unknown notification action: {action}")
        title = str(args.get("title", "Astra"))[:100]
        message = str(args.get("message", ""))[:1000]

        if platform.system() == "Linux" and shutil.which("notify-send"):
            p = subprocess.run(["notify-send", title, message], check=False)
            return SkillResult(p.returncode == 0, message)

        if platform.system() == "Windows":
            safe_t = title.replace("'", "''")
            safe_m = message.replace("'", "''")
            ps = (
                f"[System.Reflection.Assembly]::LoadWithPartialName('System.Windows.Forms')|Out-Null;"
                f"$n=New-Object System.Windows.Forms.NotifyIcon;"
                f"$n.Icon=[System.Drawing.SystemIcons]::Information;"
                f"$n.BalloonTipTitle='{safe_t}';$n.BalloonTipText='{safe_m}';"
                "$n.Visible=$true;$n.ShowBalloonTip(3000);Start-Sleep -Milliseconds 3500;$n.Dispose()"
            )
            p = subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=False)
            return SkillResult(p.returncode == 0, message)

        return SkillResult(False, "No notification backend available.")
