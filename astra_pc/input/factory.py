from __future__ import annotations

import os
import platform

from .base import InputBackend


def create_input_backend() -> InputBackend:
    system = platform.system().lower()
    wayland = bool(os.getenv("WAYLAND_DISPLAY"))

    if system == "linux" and wayland:
        from .wayland_backend import YdotoolBackend

        try:
            return YdotoolBackend()
        except RuntimeError as exc:
            if os.getenv("ASTRA_ALLOW_PYNPUT_WAYLAND_FALLBACK") == "1":
                from .pynput_backend import PynputBackend

                print(
                    "[input] ydotool unavailable; using explicitly enabled "
                    f"pynput Wayland fallback: {exc}"
                )
                return PynputBackend()
            raise RuntimeError(
                "Wayland input is not ready. Astra gestures require a healthy "
                f"ydotool/ydotoold backend on Wayland. Detail: {exc}. "
                "Run: astra setup gestures"
            ) from exc

    from .pynput_backend import PynputBackend
    return PynputBackend()
