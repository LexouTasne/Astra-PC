from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
from dataclasses import dataclass, asdict
from typing import Any


_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


@dataclass(slots=True)
class Monitor:
    x: int
    y: int
    width: int
    height: int
    name: str = ""
    primary: bool = False

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _screeninfo_monitors() -> list[Monitor]:
    try:
        from screeninfo import get_monitors as _get

        raw = _get()
        out = []
        for i, m in enumerate(raw):
            out.append(
                Monitor(
                    x=int(m.x),
                    y=int(m.y),
                    width=int(m.width),
                    height=int(m.height),
                    name=str(getattr(m, "name", "") or f"monitor-{i}"),
                    primary=bool(getattr(m, "is_primary", False)),
                )
            )
        return out
    except Exception:
        return []


def _kscreen_monitors() -> list[Monitor]:
    if (
        platform.system() != "Linux"
        or not os.getenv("WAYLAND_DISPLAY")
        or not shutil.which("kscreen-doctor")
    ):
        return []

    try:
        result = subprocess.run(
            ["kscreen-doctor", "-o"],
            capture_output=True,
            text=True,
            timeout=2.0,
            check=False,
        )
    except Exception:
        return []
    if result.returncode != 0:
        return []

    monitors: list[Monitor] = []
    current_name = ""
    current_primary = False
    enabled = False

    clean_output = _ANSI_RE.sub("", result.stdout)
    for raw in clean_output.splitlines():
        line = raw.strip()
        output = re.match(r"Output:\s+\S+\s+(.+)$", line)
        if output:
            current_name = output.group(1).strip()
            current_primary = False
            enabled = False
            continue
        if line == "enabled":
            enabled = True
            continue
        priority = re.match(r"priority\s+(\d+)", line, re.I)
        if priority:
            current_primary = int(priority.group(1)) == 1
            continue
        geometry = re.match(
            r"Geometry:\s*(-?\d+),(-?\d+)\s+(\d+)x(\d+)",
            line,
            re.I,
        )
        if geometry and enabled:
            x, y, width, height = map(int, geometry.groups())
            monitors.append(
                Monitor(
                    x=x,
                    y=y,
                    width=width,
                    height=height,
                    name=current_name or f"monitor-{len(monitors)}",
                    primary=current_primary,
                )
            )

    return monitors


def get_monitors() -> list[Monitor]:
    # KDE Wayland knows the real logical desktop geometry, including offsets.
    # screeninfo may report every output at 0,0 on Wayland, which breaks
    # screenshot-to-pointer coordinate mapping on multi-monitor desktops.
    if platform.system() == "Linux" and os.getenv("WAYLAND_DISPLAY"):
        monitors = _kscreen_monitors()
        if monitors:
            return monitors

    monitors = _screeninfo_monitors()
    if monitors:
        return monitors

    monitors = _kscreen_monitors()
    if monitors:
        return monitors

    return []


def virtual_bounds(monitors: list[Monitor] | None = None) -> tuple[int, int, int, int]:
    items = monitors if monitors is not None else get_monitors()
    if not items:
        return (0, 0, 0, 0)
    min_x = min(m.x for m in items)
    min_y = min(m.y for m in items)
    max_x = max(m.x + m.width for m in items)
    max_y = max(m.y + m.height for m in items)
    return (min_x, min_y, max_x - min_x, max_y - min_y)
