from __future__ import annotations

import json
import re
import time

import cv2
import numpy as np
from PIL import Image

from astra_pc.accessibility import create_accessibility_provider
from astra_pc.screen.capture import capture_screen

from .ollama_client import OllamaClient
from .tools import DesktopTools


AGENT_PROMPT = """You are Astra's visual desktop planner.
You receive a goal, a screenshot, structural UI elements and verification history.
Choose exactly ONE next action. Return JSON only.

Allowed actions:
{"action":"move","x":123,"y":456,"reason":"...","expected":"..."}
{"action":"click","x":123,"y":456,"reason":"...","expected":"what should visibly change"}
{"action":"right_click","x":123,"y":456,"reason":"...","expected":"..."}
{"action":"type","text":"...","reason":"...","expected":"..."}
{"action":"key_down","key":"w","reason":"hold a key across visual steps","expected":"..."}
{"action":"key_up","key":"w","reason":"release a held key","expected":"..."}
{"action":"hotkey","keys":["ctrl","l"],"reason":"...","expected":"..."}
{"action":"scroll","amount":-3,"reason":"...","expected":"..."}
{"action":"open_url","url":"https://...","reason":"...","expected":"..."}
{"action":"wait","seconds":1,"reason":"...","expected":"..."}
{"action":"done","message":"...","reason":"..."}

Use structural UI names/roles when they are available. Coordinates are screenshot pixels.
Never invent UI elements. Prefer keyboard shortcuts when clearly safer and more reliable.
Never use terminal or shell commands. Never purchase, delete files, send messages,
change passwords, or confirm irreversible actions.
For continuous movement, use key_down and keep observing subsequent screenshots; use key_up
as soon as the movement should stop. Never leave a held key pressed when returning done.
"""


class VisualDesktopAgent:
    def __init__(self, client: OllamaClient, max_steps: int = 8):
        self.client = client
        self.max_steps = max_steps
        self.tools = DesktopTools()
        self.accessibility = create_accessibility_provider()

    def run(self, goal: str, auto_confirm: bool = False) -> str:
        history: list[str] = []
        previous_signature = None

        try:
            for step in range(1, self.max_steps + 1):
                screenshot = capture_screen()
                try:
                    with Image.open(screenshot) as im:
                        width, height = im.size
                    signature = self._signature(screenshot)
                    ui = []
                    if self.accessibility.available():
                        try:
                            ui = [x.as_dict() for x in self.accessibility.snapshot(limit=70)]
                        except Exception:
                            ui = []

                    changed = None
                    if previous_signature is not None:
                        changed = self._difference(previous_signature, signature)

                    prompt = (
                        f"Goal: {goal}\n"
                        f"Screenshot size: {width}x{height}\n"
                        f"Desktop geometry: {json.dumps(self.tools.desktop_geometry(), ensure_ascii=False)}\n"
                        f"Structural UI: {json.dumps(ui[:50], ensure_ascii=False)}\n"
                        f"Verification history: {history[-6:] or ['none']}\n"
                        f"Screen change since previous step: {changed}\n"
                        "Choose the next single action. If the goal is already achieved, return done."
                    )
                    raw = self.client.chat(
                        prompt,
                        images=[screenshot],
                        system=AGENT_PROMPT,
                        temperature=0.05,
                        num_ctx=12288,
                        num_predict=180,
                    )
                    previous_signature = signature
                finally:
                    screenshot.unlink(missing_ok=True)

                action = self._parse_action(raw)
                name = str(action.get("action", ""))
                reason = str(action.get("reason", ""))
                expected = str(action.get("expected", ""))
                print(f"[Astra agent {step}/{self.max_steps}] {name}: {reason}")
                if expected:
                    print(f"  expected: {expected}")

                if name == "done":
                    return str(action.get("message", "Done."))

                if not auto_confirm:
                    answer = input("Execute this action? [Y/n] ").strip().lower()
                    if answer not in {"", "y", "yes", "s", "sim"}:
                        return "Stopped by user."

                result = self.tools.execute(action)
                time.sleep(0.07)
                verify_path = capture_screen()
                try:
                    after = self._signature(verify_path)
                    delta = self._difference(previous_signature, after)
                finally:
                    verify_path.unlink(missing_ok=True)

                history.append(
                    f"{result.message}; expected={expected or 'unspecified'}; "
                    f"screen_delta={delta:.4f}"
                )
                previous_signature = after

                if not result.ok:
                    history.append("tool error: " + result.message)

            return "Stopped after reaching the maximum number of agent steps."
        finally:
            self.tools.release_all()

    @staticmethod
    def _signature(path) -> np.ndarray:
        frame = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
        if frame is None:
            return np.zeros((90, 160), dtype=np.uint8)
        return cv2.resize(frame, (160, 90), interpolation=cv2.INTER_AREA)

    @staticmethod
    def _difference(a: np.ndarray, b: np.ndarray) -> float:
        if a.shape != b.shape:
            return 1.0
        diff = cv2.absdiff(a, b)
        return round(float(np.count_nonzero(diff > 12)) / float(diff.size), 4)

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
