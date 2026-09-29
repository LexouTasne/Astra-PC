from __future__ import annotations

import threading

from astra_pc.input.factory import create_input_backend
from astra_pc.viewport.controller import AstraViewport

from .base import Skill, SkillResult


class ViewportSkill(Skill):
    name = "viewport"
    description = "System-wide Astra zoom and screen rotation, independent of app zoom."
    safe_actions = (
        "zoom_in",
        "zoom_out",
        "zoom_reset",
        "rotate_left",
        "rotate_right",
        "rotation_reset",
    )

    def __init__(self):
        self._viewport = None
        self._lock = threading.RLock()

    def _get(self) -> AstraViewport:
        with self._lock:
            if self._viewport is None:
                from astra_pc.input.factory import create_input_backend
                self._viewport = AstraViewport(create_input_backend())
            return self._viewport

    def execute(self, action: str, args: dict) -> SkillResult:
        try:
            viewport = self._get()
            if action == "zoom_in":
                steps = max(1, min(8, int(args.get("steps", 1))))
                return SkillResult(viewport.zoom(steps), "Zoom global aumentado.")
            if action == "zoom_out":
                steps = max(1, min(8, int(args.get("steps", 1))))
                return SkillResult(viewport.zoom(-steps), "Zoom global reduzido.")
            if action == "zoom_reset":
                return SkillResult(viewport.reset_zoom(), "Zoom global resetado.")
            if action == "rotate_left":
                return SkillResult(viewport.rotate(-1), "Tela girada para a esquerda.")
            if action == "rotate_right":
                return SkillResult(viewport.rotate(1), "Tela girada para a direita.")
            if action == "rotation_reset":
                return SkillResult(viewport.reset_rotation(), "Rotação resetada.")
            return SkillResult(False, f"Unknown viewport action: {action}")
        except Exception as exc:
            return SkillResult(False, f"Viewport indisponível: {exc}")
