from __future__ import annotations

import json
import re

from PIL import Image

from astra_pc.screen.capture import capture_screen

from .ollama_client import OllamaClient
from .tools import DesktopTools


AGENT_PROMPT = """You are Astra's visual desktop planner.
You receive a goal and a fresh screenshot. Choose exactly ONE next action.
Return JSON only. No markdown, no explanation outside JSON.

Allowed actions:
{"action":"click","x":123,"y":456,"reason":"..."}
{"action":"right_click","x":123,"y":456,"reason":"..."}
{"action":"type","text":"...","reason":"..."}
{"action":"hotkey","keys":["ctrl","l"],"reason":"..."}
{"action":"scroll","amount":-3,"reason":"..."}
{"action":"open_url","url":"https://...","reason":"..."}
{"action":"wait","seconds":1,"reason":"..."}
{"action":"done","message":"...","reason":"..."}

Coordinates are screenshot pixels. Never invent UI elements.
Prefer keyboard shortcuts when clearly safer and more reliable.
Never use terminal or shell commands.
Never purchase, delete files, send messages, change passwords, or confirm irreversible actions.
If the goal requires one of those, return done and explain that manual confirmation is needed.
"""


class VisualDesktopAgent:
    def __init__(self, client: OllamaClient, max_steps: int = 8):
        self.client = client
        self.max_steps = max_steps
        self.tools = DesktopTools()

    def run(self, goal: str, auto_confirm: bool = False) -> str:
        history: list[str] = []

        for step in range(1, self.max_steps + 1):
            screenshot = capture_screen()
            try:
                with Image.open(screenshot) as im:
                    width, height = im.size

                prompt = (
                    f"Goal: {goal}\n"
                    f"Screenshot size: {width}x{height}\n"
                    f"Previous actions: {history[-5:] or ['none']}\n"
                    "Choose the next single action."
                )
                raw = self.client.chat(
                    prompt,
                    images=[screenshot],
                    system=AGENT_PROMPT,
                    temperature=0.1,
                    num_ctx=12288,
                )
            finally:
                screenshot.unlink(missing_ok=True)

            action = self._parse_action(raw)
            name = str(action.get("action", ""))
            reason = str(action.get("reason", ""))
            print(f"[Astra agent {step}/{self.max_steps}] {name}: {reason}")

            if name == "done":
                return str(action.get("message", "Done."))

            if not auto_confirm:
                answer = input("Execute this action? [Y/n] ").strip().lower()
                if answer not in {"", "y", "yes", "s", "sim"}:
                    return "Stopped by user."

            result = self.tools.execute(action)
            history.append(result.message)
            if not result.ok:
                history.append("tool error: " + result.message)

        return "Stopped after reaching the maximum number of agent steps."

    @staticmethod
    def _parse_action(text: str) -> dict:
        cleaned = text.strip()
        cleaned = re.sub(r"^\x60\x60\x60(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*\x60\x60\x60$", "", cleaned)
        try:
            value = json.loads(cleaned)
        except json.JSONDecodeError:
            start = cleaned.find("{")
            end = cleaned.rfind("}")
            if start < 0 or end <= start:
                raise RuntimeError(f"Astra returned invalid action JSON: {text}")
            value = json.loads(cleaned[start:end + 1])
        if not isinstance(value, dict) or "action" not in value:
            raise RuntimeError(f"Astra returned invalid action object: {value!r}")
        return value
