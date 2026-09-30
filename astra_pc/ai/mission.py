from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Callable

from .ollama_client import OllamaClient


MISSION_SYSTEM = """You are Astra's mission orchestrator.
You coordinate existing safe capabilities to complete a multi-step user goal.
Choose exactly ONE next step and return JSON only.

Allowed step types:
{"type":"skill","skill":"name","action":"name","args":{},"reason":"..."}
{"type":"visual","goal":"subgoal that requires seeing/using the desktop","reason":"..."}
{"type":"swarm","goal":"question/subproblem","count":4,"vision":false,"reason":"..."}
{"type":"answer","message":"final answer","reason":"goal complete"}

Rules:
- Use only skills explicitly listed in the prompt.
- Prefer a skill over visual clicking when a matching skill exists.
- Use swarm for analysis, alternatives, review or decomposition; swarm never executes actions.
- Use visual only for screen-dependent interaction.
- Never claim a step succeeded until its returned result says so.
- If a step fails, inspect the failure and choose a different safe strategy.
- Do not purchase, send messages, change passwords or perform irreversible/destructive actions.
- If a skill reports confirmation required, stop and return an answer explaining what needs confirmation.
- Keep each step minimal and reversible.
"""


@dataclass(slots=True)
class MissionResult:
    ok: bool
    message: str
    steps: list[dict[str, Any]]

    def as_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "message": self.message, "steps": self.steps}


class MissionAgent:
    def __init__(
        self,
        client: OllamaClient,
        *,
        skill_provider: Callable[[], list[dict[str, str]]],
        context_provider: Callable[[], str],
        execute_skill: Callable[[dict[str, Any]], dict[str, Any]],
        execute_visual: Callable[[str], dict[str, Any]],
        execute_swarm: Callable[[str, int, bool], dict[str, Any]],
        cancel_event=None,
        max_steps: int = 12,
    ) -> None:
        self.client = client
        self.skill_provider = skill_provider
        self.context_provider = context_provider
        self.execute_skill = execute_skill
        self.execute_visual = execute_visual
        self.execute_swarm = execute_swarm
        self.cancel_event = cancel_event
        self.max_steps = max(1, min(40, int(max_steps)))

    def run(self, goal: str) -> MissionResult:
        goal = str(goal).strip()
        if not goal:
            return MissionResult(False, "Empty mission goal.", [])

        history: list[dict[str, Any]] = []
        last_signature = ""
        repeated = 0

        for step_index in range(1, self.max_steps + 1):
            if self._cancelled():
                return MissionResult(False, "Stopped by user.", history)

            context = self.context_provider()
            prompt = {
                "goal": goal,
                "step": step_index,
                "max_steps": self.max_steps,
                "context": context[-7000:],
                "skills": self.skill_provider(),
                "history": history[-8:],
                "schema": {
                    "type": "skill|visual|swarm|answer",
                    "skill": "required when type=skill",
                    "action": "required when type=skill",
                    "args": {},
                    "goal": "subgoal for visual/swarm",
                    "count": "1..100 for swarm",
                    "vision": "boolean for swarm",
                    "message": "final response for answer",
                    "reason": "brief reason",
                },
            }

            step = self._request_step(
                "Mission state:\n" + json.dumps(prompt, ensure_ascii=False)
            )
            signature = self._step_signature(step)
            if signature and signature == last_signature:
                repeated += 1
            else:
                repeated = 0
            last_signature = signature

            if repeated >= 2 and step.get("type") != "answer":
                step = self._request_step(
                    "Mission state:\n"
                    + json.dumps(prompt, ensure_ascii=False)
                    + "\nThe previous plan repeated the same step multiple times. "
                    "Choose a different valid strategy or finish with answer."
                )
                last_signature = self._step_signature(step)
                repeated = 0

            step_type = str(step.get("type", "")).lower()
            reason = str(step.get("reason", ""))

            if step_type == "answer":
                message = str(step.get("message", "")).strip() or "Mission complete."
                return MissionResult(True, message, history)

            if step_type == "skill":
                result = self.execute_skill(step)
            elif step_type == "visual":
                subgoal = str(step.get("goal", "")).strip() or goal
                result = self.execute_visual(subgoal)
            elif step_type == "swarm":
                subgoal = str(step.get("goal", "")).strip() or goal
                count = max(1, min(100, int(step.get("count", 4))))
                vision = bool(step.get("vision", False))
                result = self.execute_swarm(subgoal, count, vision)
            else:
                result = {"ok": False, "error": f"unsupported mission step: {step_type}"}

            record = {
                "index": step_index,
                "type": step_type,
                "reason": reason,
                "request": self._compact_step(step),
                "result": self._compact_result(result),
            }
            history.append(record)

            error_text = str(result.get("error") or result.get("message") or "").lower()
            if not result.get("ok") and "confirmation required" in error_text:
                return MissionResult(
                    False,
                    "A próxima ação exige confirmação explícita antes de continuar.",
                    history,
                )

        return MissionResult(
            False,
            "Mission stopped after reaching the maximum number of steps.",
            history,
        )

    def _request_step(self, prompt: str, attempts: int = 3) -> dict[str, Any]:
        last_error = "invalid mission step"
        repair = ""
        for attempt in range(1, max(1, int(attempts)) + 1):
            if self._cancelled():
                return {"type": "answer", "message": "Stopped by user."}
            raw = self.client.chat(
                prompt + repair,
                system=MISSION_SYSTEM,
                temperature=0.03 if attempt > 1 else 0.08,
                num_ctx=8192,
                num_predict=320,
                think=False,
            )
            try:
                step = self._parse_json(raw)
                error = self._validate_step(step)
                if error is None:
                    return step
                last_error = error
            except Exception as exc:
                last_error = str(exc)

            repair = (
                "\nPrevious step rejected: "
                + last_error[:600]
                + "\nReturn exactly one corrected JSON object matching the schema."
            )

        raise RuntimeError(
            f"Mission planner failed after {attempts} attempts: {last_error}"
        )

    def _validate_step(self, step: dict[str, Any]) -> str | None:
        if not isinstance(step, dict):
            return "step must be an object"
        step_type = str(step.get("type", "")).strip().lower()
        if step_type not in {"skill", "visual", "swarm", "answer"}:
            return f"unsupported step type: {step_type}"
        if step_type == "skill":
            skill = str(step.get("skill", "")).strip()
            action = str(step.get("action", "")).strip()
            if not skill or not action:
                return "skill step requires skill and action"
            names = {item.get("name") for item in self.skill_provider()}
            if skill not in names:
                return f"unknown skill: {skill}"
            if not isinstance(step.get("args", {}), dict):
                return "skill args must be an object"
        if step_type in {"visual", "swarm"} and not str(step.get("goal", "")).strip():
            return f"{step_type} step requires a goal"
        if step_type == "swarm":
            try:
                count = int(step.get("count", 4))
            except (TypeError, ValueError):
                return "swarm count must be an integer"
            if not 1 <= count <= 100:
                return "swarm count must be between 1 and 100"
        if step_type == "answer" and not str(step.get("message", "")).strip():
            return "answer step requires message"
        return None

    def _cancelled(self) -> bool:
        return self.cancel_event is not None and self.cancel_event.is_set()

    @staticmethod
    def _parse_json(text: str) -> dict[str, Any]:
        cleaned = str(text).strip()
        cleaned = re.sub(r"^\x60\x60\x60(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*\x60\x60\x60$", "", cleaned)
        try:
            value = json.loads(cleaned)
        except json.JSONDecodeError:
            start, end = cleaned.find("{"), cleaned.rfind("}")
            if start < 0 or end <= start:
                raise RuntimeError("mission planner returned invalid JSON")
            value = json.loads(cleaned[start:end + 1])
        if not isinstance(value, dict):
            raise RuntimeError("mission planner returned non-object JSON")
        return value

    @staticmethod
    def _step_signature(step: dict[str, Any]) -> str:
        compact = {k: v for k, v in step.items() if k not in {"reason", "message"}}
        return json.dumps(compact, ensure_ascii=False, sort_keys=True)

    @staticmethod
    def _compact_step(step: dict[str, Any]) -> dict[str, Any]:
        compact = dict(step)
        if "args" in compact:
            compact["args"] = dict(compact.get("args") or {})
        return compact

    @staticmethod
    def _compact_result(result: dict[str, Any]) -> dict[str, Any]:
        compact: dict[str, Any] = {"ok": bool(result.get("ok"))}
        for key in ("message", "error", "plan", "count", "requested"):
            if key in result:
                value = result[key]
                if isinstance(value, str):
                    value = value[:2000]
                compact[key] = value
        return compact
