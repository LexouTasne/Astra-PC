from __future__ import annotations

from .base import AccessibilityProvider, UIElement


class WindowsUIAProvider(AccessibilityProvider):
    def __init__(self):
        try:
            from pywinauto import Desktop
        except ImportError:
            self.Desktop = None
        else:
            self.Desktop = Desktop

    def available(self) -> bool:
        return self.Desktop is not None

    def snapshot(self, limit: int = 120) -> list[UIElement]:
        if self.Desktop is None:
            return []

        out: list[UIElement] = []
        try:
            desktop = self.Desktop(backend="uia")
            window = desktop.get_active()
            nodes = [window] + list(window.descendants())
        except Exception:
            return []

        for node in nodes[:limit]:
            try:
                info = node.element_info
                rect = info.rectangle
                out.append(
                    UIElement(
                        name=str(info.name or ""),
                        role=str(info.control_type or ""),
                        x=int(rect.left),
                        y=int(rect.top),
                        width=max(0, int(rect.right - rect.left)),
                        height=max(0, int(rect.bottom - rect.top)),
                        enabled=bool(getattr(info, "enabled", True)),
                        focused=bool(getattr(info, "has_keyboard_focus", False)),
                    )
                )
            except Exception:
                continue
        return out
