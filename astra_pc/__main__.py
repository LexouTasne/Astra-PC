from __future__ import annotations

import argparse
from pathlib import Path

from .config import load_config
from .core.runtime import AstraRuntime


def main() -> None:
    p = argparse.ArgumentParser(description="Astra-PC gesture-first desktop controller")
    p.add_argument("--config", type=Path)
    p.add_argument("--show-camera", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--voice-model", type=Path)
    a = p.parse_args()
    AstraRuntime(load_config(a.config), a.show_camera, a.dry_run, a.voice_model).run()


if __name__ == "__main__":
    main()
