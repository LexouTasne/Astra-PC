from __future__ import annotations

import importlib.util
from pathlib import Path

from .base import Skill


def discover_skills(directory: str | Path) -> list[Skill]:
    root = Path(directory).expanduser()
    if not root.exists():
        return []

    found: list[Skill] = []
    for path in sorted(root.glob("*.py")):
        if path.name.startswith("_"):
            continue
        try:
            spec = importlib.util.spec_from_file_location(f"astra_user_skill_{path.stem}", path)
            if spec is None or spec.loader is None:
                continue
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            factory = getattr(module, "create_skill", None)
            if callable(factory):
                skill = factory()
                if isinstance(skill, Skill):
                    found.append(skill)
        except Exception:
            continue
    return found
