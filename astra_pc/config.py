from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class AstraConfig:
    data: dict[str, Any]

    def section(self, name: str) -> dict[str, Any]:
        return self.data[name]


DEFAULT_CONFIG = Path(__file__).resolve().parent.parent / "config" / "astra.json"


def load_config(path: Path | None = None) -> AstraConfig:
    source = path or DEFAULT_CONFIG
    with source.open("r", encoding="utf-8") as f:
        return AstraConfig(json.load(f))
