from __future__ import annotations

import platform

from .base import AccessibilityProvider


def create_accessibility_provider() -> AccessibilityProvider:
    system = platform.system()
    if system == "Windows":
        from .windows import WindowsUIAProvider
        return WindowsUIAProvider()
    if system == "Linux":
        from .linux import LinuxATSPIProvider
        return LinuxATSPIProvider()
    return AccessibilityProvider()
