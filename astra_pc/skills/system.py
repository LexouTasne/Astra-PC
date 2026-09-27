from __future__ import annotations

import os
import platform
import shutil
import subprocess
import time

import psutil

from .base import Skill, SkillResult


class SystemSkill(Skill):
    name = "system"
    description = "Read live PC status and perform safe system actions."

    def execute(self, action: str, args: dict) -> SkillResult:
        if action == "status":
            vm = psutil.virtual_memory()
            data = {
                "os": platform.platform(),
                "machine": platform.machine(),
                "python": platform.python_version(),
                "cpu_percent": psutil.cpu_percent(interval=0.12),
                "cpu_count": psutil.cpu_count(),
                "ram_percent": vm.percent,
                "ram_used_gb": round((vm.total - vm.available) / (1024**3), 2),
                "ram_total_gb": round(vm.total / (1024**3), 2),
                "boot_age_s": int(time.time() - psutil.boot_time()),
                "processes": len(psutil.pids()),
            }
            try:
                data["disk_percent"] = psutil.disk_usage("/").percent
            except Exception:
                pass
            return SkillResult(True, "System status", data)

        if action == "top_processes":
            rows = []
            for proc in psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent"]):
                try:
                    info = proc.info
                    rows.append(
                        {
                            "pid": info["pid"],
                            "name": info["name"],
                            "cpu": round(float(info["cpu_percent"] or 0), 1),
                            "ram": round(float(info["memory_percent"] or 0), 1),
                        }
                    )
                except Exception:
                    continue
            rows.sort(key=lambda x: (x["cpu"], x["ram"]), reverse=True)
            return SkillResult(True, "Top processes", {"processes": rows[:12]})

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

        if action == "media":
            command = str(args.get("command", "")).lower()
            if platform.system() == "Linux" and shutil.which("playerctl"):
                mapping = {
                    "play": "play",
                    "pause": "pause",
                    "toggle": "play-pause",
                    "next": "next",
                    "previous": "previous",
                }
                cmd = mapping.get(command)
                if cmd:
                    p = subprocess.run(["playerctl", cmd], capture_output=True, text=True)
                    return SkillResult(p.returncode == 0, f"Media: {command}")
            return SkillResult(False, "No supported media backend found.")

        return SkillResult(False, f"Unknown system action: {action}")
