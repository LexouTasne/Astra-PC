from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from astra_pc.ai.agent import AstraBrain


class PerceptionFusion:
    """Fuses structural accessibility data with visual understanding."""

    def __init__(self, brain: AstraBrain):
        self.brain = brain

    def describe(
        self,
        screenshot: str | Path,
        accessibility: list[dict[str, Any]],
        question: str,
    ) -> str:
        structural = accessibility[:60]
        prompt = (
            "Use BOTH the screenshot and the structural UI tree. "
            "Prefer structural roles/names for exact controls and visual reasoning "
            "for layout/icon meaning. If they disagree, say so briefly.\n"
            f"Question: {question}\n"
            f"UI tree: {json.dumps(structural, ensure_ascii=False)}"
        )
        return self.brain.see(screenshot, prompt)
