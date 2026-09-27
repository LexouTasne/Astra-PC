from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path


class ScreenCaptureError(RuntimeError):
    pass


def capture_screen(output: str | Path | None = None) -> Path:
    if output is None:
        fd, tmp = tempfile.mkstemp(prefix="astra-screen-", suffix=".png")
        os.close(fd)
        target = Path(tmp)
    else:
        target = Path(output)
        target.parent.mkdir(parents=True, exist_ok=True)

    if os.name == "nt":
        try:
            from PIL import ImageGrab
            ImageGrab.grab(all_screens=True).save(target)
            return target
        except Exception as exc:
            raise ScreenCaptureError(str(exc)) from exc

    if os.getenv("WAYLAND_DISPLAY"):
        if shutil.which("spectacle"):
            p = subprocess.run(
                ["spectacle", "-b", "-n", "-o", str(target)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            if p.returncode == 0 and target.exists():
                return target
        if shutil.which("grim"):
            p = subprocess.run(
                ["grim", str(target)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            if p.returncode == 0 and target.exists():
                return target

    try:
        from PIL import ImageGrab
        ImageGrab.grab(all_screens=True).save(target)
        return target
    except Exception as exc:
        raise ScreenCaptureError(
            "Could not capture the screen. On KDE Wayland install/use Spectacle; "
            "on wlroots compositors install grim."
        ) from exc
