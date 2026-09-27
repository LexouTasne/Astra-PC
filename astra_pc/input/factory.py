from __future__ import annotations

import os
import platform

from .base import InputBackend
from .pynput_backend import PynputBackend
from .wayland_backend import YdotoolBackend


def create_input_backend() -> InputBackend:
    system = platform.system().lower()
    wayland = bool(os.getenv("WAYLAND_DISPLAY"))

    if system == "linux" and wayland:
        try:
            return YdotoolBackend()
        except RuntimeError:
            return PynputBackend()

    return PynputBackend()
