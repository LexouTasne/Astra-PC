from __future__ import annotations


class OpenXRBridge:
    """Optional OpenXR bridge. Core Astra never requires an XR runtime."""

    def __init__(self):
        try:
            import xr
        except ImportError:
            self.xr = None
        else:
            self.xr = xr

    def available(self) -> bool:
        return self.xr is not None

    def status(self) -> dict:
        return {
            "available": self.available(),
            "backend": "pyopenxr" if self.available() else None,
            "note": (
                "OpenXR runtime detected; hand/space integration can be enabled by a spatial skill."
                if self.available()
                else "Install an OpenXR Python binding and runtime to enable XR."
            ),
        }
