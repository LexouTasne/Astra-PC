from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .paths import cache_dir, data_dir


@dataclass(slots=True)
class AstraConfig:
    data: dict[str, Any]

    def section(self, name: str) -> dict[str, Any]:
        return self.data[name]


DEFAULT_CONFIG = Path(__file__).resolve().parent.parent / "config" / "astra.json"


def load_config(path: Path | None = None) -> AstraConfig:
    source = path or DEFAULT_CONFIG
    with source.open("r", encoding="utf-8") as f:
        data = json.load(f)

    # Storage can move independently from the code install. This is useful for
    # SSDs, secondary disks and portable/USB installs.
    if os.getenv("ASTRA_DATA_DIR"):
        root = data_dir()
        data.setdefault("daemon", {})["memory_path"] = str(root / "astra.db")
        data.setdefault("skills", {})["plugin_dir"] = str(root / "skills")
        data.setdefault("mesh", {})["state_path"] = str(root / "mesh")

    if os.getenv("ASTRA_CACHE_DIR"):
        root = cache_dir()
        data.setdefault("daemon", {})["cache_path"] = str(root / "responses.db")

    return AstraConfig(data)
