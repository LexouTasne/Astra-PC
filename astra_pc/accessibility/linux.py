from __future__ import annotations

from .base import AccessibilityProvider, UIElement


class LinuxATSPIProvider(AccessibilityProvider):
    def __init__(self):
        try:
            import pyatspi
        except ImportError:
            self.pyatspi = None
        else:
            self.pyatspi = pyatspi

    def available(self) -> bool:
        return self.pyatspi is not None

    def snapshot(self, limit: int = 120) -> list[UIElement]:
        if self.pyatspi is None:
            return []

        out: list[UIElement] = []
        try:
            desktop = self.pyatspi.Registry.getDesktop(0)
        except Exception:
            return []

        def walk(node, depth: int = 0):
            if len(out) >= limit or depth > 10:
                return
            try:
                name = str(getattr(node, "name", "") or "")
                role = str(node.getRoleName() or "")
                state = node.getState()
                focused = state.contains(self.pyatspi.STATE_FOCUSED)
                enabled = state.contains(self.pyatspi.STATE_ENABLED)
                x = y = width = height = None
                try:
                    comp = node.queryComponent()
                    x, y, width, height = comp.getExtents(self.pyatspi.DESKTOP_COORDS)
                except Exception:
                    pass
                if name or role:
                    out.append(
                        UIElement(
                            name=name,
                            role=role,
                            x=x,
                            y=y,
                            width=width,
                            height=height,
                            enabled=enabled,
                            focused=focused,
                        )
                    )
                for child in node:
                    walk(child, depth + 1)
                    if len(out) >= limit:
                        break
            except Exception:
                return

        for app in desktop:
            walk(app)
            if len(out) >= limit:
                break
        return out
