from __future__ import annotations

import threading

from .base import Skill, SkillResult


class InputControlSkill(Skill):
    name = "input"
    description = (
        "Control mouse and keyboard directly: move/click/scroll/type text/hotkeys."
    )
    safe_actions = (
        "mouse_move",
        "mouse_click",
        "mouse_right_click",
        "mouse_scroll",
        "type_text",
        "hotkey",
    )

    def __init__(self):
        self._backend = None
        self._lock = threading.RLock()

    def _get_backend(self):
        with self._lock:
            if self._backend is None:
                from astra_pc.input.factory import create_input_backend
                self._backend = create_input_backend()
            return self._backend

    def execute(self, action: str, args: dict) -> SkillResult:
        try:
            backend = self._get_backend()

            if action == "mouse_move":
                x = int(args.get("x", 0))
                y = int(args.get("y", 0))
                backend.move(x, y)
                return SkillResult(True, f"Mouse movido para {x}, {y}.")

            if action == "mouse_click":
                backend.left_click()
                return SkillResult(True, "Cliquei.")

            if action == "mouse_right_click":
                backend.right_click()
                return SkillResult(True, "Clique direito executado.")

            if action == "mouse_scroll":
                amount = max(-40, min(40, int(args.get("amount", 0))))
                backend.scroll(amount)
                return SkillResult(True, f"Scroll {amount}.")

            if action == "type_text":
                text = str(args.get("text", ""))
                if not text:
                    return SkillResult(False, "Texto vazio.")
                if len(text) > 20000:
                    return SkillResult(False, "Texto grande demais para digitação direta.")
                backend.type_text(text)
                return SkillResult(True, "Texto digitado.")

            if action == "hotkey":
                raw = args.get("keys", [])
                if not isinstance(raw, list):
                    return SkillResult(False, "Hotkey inválida.")
                keys = [str(key).strip() for key in raw if str(key).strip()]
                if not keys or len(keys) > 8:
                    return SkillResult(False, "Hotkey inválida.")
                backend.hotkey(keys)
                return SkillResult(True, "Atalho executado.")

            return SkillResult(False, f"Unknown input action: {action}")
        except Exception as exc:
            return SkillResult(False, f"Input indisponível: {exc}")
