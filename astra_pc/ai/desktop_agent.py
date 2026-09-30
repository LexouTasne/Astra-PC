from __future__ import annotations

import json
import re
import time
from typing import Callable

import cv2
import numpy as np
from PIL import Image

from astra_pc.accessibility import create_accessibility_provider
from astra_pc.screen.capture import capture_screen

from .ollama_client import OllamaClient
from .swarm import SubAgentPool, default_tasks
from .tools import DesktopTools


AGENT_PROMPT = """You are Astra's visual desktop planner. Return exactly one JSON action.
Use the screenshot and structural UI. Never invent UI elements.
Prefer keyboard shortcuts when clearly safer. Coordinates are screenshot pixels.
Do not use terminal/shell, purchase, delete files, send messages, change passwords,
or confirm irreversible actions. Release held keys before done.

Allowed actions:
move(x,y), click(x,y), right_click(x,y), type(text), key_down(key), key_up(key),
hotkey(keys), scroll(amount), open_url(url), wait(seconds), done(message).
Include only fields needed for the action plus brief reason/expected when useful.
"""


class VisualDesktopAgent:
    def __init__(
        self,
        client: OllamaClient,
        max_steps: int = 8,
        *,
        subagents: SubAgentPool | None = None,
        swarm_interval: int = 3,
        swarm_parallel: int | None = None,
        on_subagent_result: Callable | None = None,
        cancel_event=None,
    ):
        self.client = client
        self.max_steps = max(1, int(max_steps))
        self.subagents = subagents
        self.swarm_interval = max(1, int(swarm_interval))
        self.swarm_parallel = swarm_parallel
        self.on_subagent_result = on_subagent_result
        self.cancel_event = cancel_event
        self.tools = DesktopTools()
        self.accessibility = create_accessibility_provider()

    def run(self, goal: str, auto_confirm: bool = False) -> str:
        history: list[str] = []
        previous_signature = None
        last_action_signature = ""
        stagnant_steps = 0

        try:
            for step in range(1, self.max_steps + 1):
                if self._cancelled():
                    return "Stopped by user."

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

                    swarm_findings = []
                    should_consult_swarm = (
                        self.subagents is not None
                        and (
                            step % self.swarm_interval == 0
                            or (history and "tool error" in history[-1].lower())
                            or (changed is not None and changed < 0.002)
                        )
                    )
                    if should_consult_swarm:
                        shared = (
                            f"step={step}; changed={changed}; "
                            f"history={history[-3:]}; "
                            f"ui={json.dumps(ui[:12], ensure_ascii=False)}; "
                            f"geometry={json.dumps(self.tools.desktop_geometry(), ensure_ascii=False)}"
                        )
                        try:
                            swarm_findings = [
                                result.as_dict()
                                for result in self.subagents.run(
                                    default_tasks(goal, include_vision=True)[:self.swarm_parallel],
                                    shared_context=shared,
                                    image=screenshot,
                                    on_result=self.on_subagent_result,
                                    max_parallel=self.swarm_parallel,
                                )
                            ]
                        except Exception as exc:
                            swarm_findings = [
                                {"role": "swarm", "ok": False, "error": str(exc)}
                            ]

                    prompt = (
                        f"Goal: {goal}\n"
                        f"Screenshot size: {width}x{height}\n"
                        f"Desktop geometry: {json.dumps(self.tools.desktop_geometry(), ensure_ascii=False)}\n"
                        f"Structural UI: {json.dumps(ui[:24], ensure_ascii=False)}\n"
                        f"Verification history: {history[-4:] or ['none']}\n"
                        f"Screen change since previous step: {changed}\n"
                        f"Parallel sub-agent findings: {json.dumps(swarm_findings, ensure_ascii=False)}\n"
                        "Use sub-agent findings as advice, not authority. "
                        "Choose the next single action. If the goal is already achieved, return done."
                    )

                    if stagnant_steps >= 2:
                        prompt += (
                            "\nSTALL DETECTED: the screen has barely changed for multiple "
                            "steps. Do not repeat the exact same action; choose a different "
                            "reversible strategy or return done if the goal is already met."
                        )

                    if self._cancelled():
                        return "Stopped by user."

                    action = self._request_valid_action(prompt, screenshot)
                    action_signature = self._action_signature(action)

                    if (
                        stagnant_steps >= 2
                        and action_signature
                        and action_signature == last_action_signature
                        and action.get("action") != "done"
                    ):
                        action = self._request_valid_action(
                            prompt
                            + "\nYour proposed action exactly repeats the stalled previous "
                            "action. Replan now and choose a different valid action.",
                            screenshot,
                        )
                        action_signature = self._action_signature(action)

                    previous_signature = signature
                finally:
                    screenshot.unlink(missing_ok=True)

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

                if self._cancelled():
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
                stagnant_steps = stagnant_steps + 1 if delta < 0.002 else 0
                last_action_signature = action_signature

                if not result.ok:
                    history.append("tool error: " + result.message)

            return "Stopped after reaching the maximum number of agent steps."
        finally:
            self.tools.release_all()

    def _cancelled(self) -> bool:
        return self.cancel_event is not None and self.cancel_event.is_set()

    def _request_valid_action(
        self,
        prompt: str,
        screenshot,
        *,
        max_attempts: int = 3,
    ) -> dict:
        last_error = "unknown validation error"
        repair_note = ""

        for attempt in range(1, max(1, int(max_attempts)) + 1):
            if self._cancelled():
                return {"action": "done", "message": "Stopped by user."}

            raw = self.client.chat(
                prompt + repair_note,
                images=[screenshot],
                system=AGENT_PROMPT,
                temperature=0.03 if attempt > 1 else 0.05,
                num_ctx=4096,
                num_predict=120,
                format="json",
            )

            try:
                action = self._parse_action(raw)
            except Exception as exc:
                last_error = str(exc)
            else:
                validation = self.tools.validate(action)
                if validation.ok:
                    return action
                last_error = validation.message

            repair_note = (
                "\nYour previous answer was rejected before execution: "
                + last_error[:600]
                + "\nReturn exactly one corrected action object using the allowed schema. "
                "Do not explain it outside JSON."
            )

        raise RuntimeError(
            "Astra could not produce a valid desktop action after "
            f"{max_attempts} attempts: {last_error}"
        )

    @staticmethod
    def _action_signature(action: dict) -> str:
        compact = {
            key: value
            for key, value in action.items()
            if key not in {"reason", "expected", "message"}
        }
        try:
            return json.dumps(compact, ensure_ascii=False, sort_keys=True)
        except Exception:
            return str(compact)

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
