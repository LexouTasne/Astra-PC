from __future__ import annotations

import json
import re
from typing import Any

from astra_pc.ai.agent import AstraBrain
from astra_pc.core.context import DesktopContext
from astra_pc.skills.manager import SkillManager


class AstraPlanner:
    """Fast deterministic router first; small LLM planner only as fallback."""

    def __init__(self, brain: AstraBrain, skills: SkillManager):
        self.brain = brain
        self.skills = skills

    def plan(
        self,
        text: str,
        context: DesktopContext,
        accessibility: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        fast = self._fast_plan(text)
        if fast:
            return fast

        prompt = {
            "request": text,
            "context": context.as_dict(),
            "skills": self.skills.describe(),
            "accessibility": (accessibility or [])[:35],
            "schema": {
                "type": "skill|answer",
                "skill": "apps|system",
                "action": "action name",
                "args": {},
                "answer": "text when type=answer",
            },
        }
        raw = self.brain.text_client.chat(
            json.dumps(prompt, ensure_ascii=False),
            system=(
                "You are Astra's local planner. Return ONE compact JSON object only. "
                "Use a skill only when the request clearly maps to an available skill. "
                "Otherwise type=answer and answer the user directly. Never invent skills."
            ),
            temperature=0.05,
            num_ctx=3072,
            num_predict=120,
        )
        return self._json(raw)

    @staticmethod
    def _fast_plan(text: str) -> dict[str, Any] | None:
        q = " ".join(text.lower().strip().split())

        url = re.search(r"https?://\S+", text)
        if url and re.search(r"\b(abre|abra|abrir|open)\b", q):
            return {
                "type": "skill",
                "skill": "apps",
                "action": "open_url",
                "args": {"url": url.group(0).rstrip(".,)")},
            }

        m = re.search(r"\b(?:abre|abra|abrir|open)\s+(?:o\s+|a\s+)?([\w.+-]+)", q)
        if m:
            return {
                "type": "skill",
                "skill": "apps",
                "action": "open_app",
                "args": {"name": m.group(1)},
            }

        m = re.search(r"\b(?:volume)\s+(\d{1,3})\b", q)
        if m:
            return {
                "type": "skill",
                "skill": "system",
                "action": "volume",
                "args": {"value": int(m.group(1))},
            }

        if any(x in q for x in ("status do pc", "status do computador", "status do sistema")):
            return {"type": "skill", "skill": "system", "action": "status", "args": {}}

        if any(x in q for x in ("processos pesados", "top processos", "o que está pesando", "o que esta pesando")):
            return {"type": "skill", "skill": "system", "action": "top_processes", "args": {}}

        if q in {"pause", "pausa", "pausar música", "pausar musica"}:
            return {"type": "skill", "skill": "system", "action": "media", "args": {"command": "pause"}}
        if q in {"play", "tocar música", "tocar musica", "continuar música", "continuar musica"}:
            return {"type": "skill", "skill": "system", "action": "media", "args": {"command": "play"}}
        if q in {"próxima música", "proxima musica", "próxima", "proxima"}:
            return {"type": "skill", "skill": "system", "action": "media", "args": {"command": "next"}}

        return None

    @staticmethod
    def _json(raw: str) -> dict[str, Any]:
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
            cleaned = re.sub(r"\s*```$", "", cleaned)
        try:
            value = json.loads(cleaned)
        except Exception:
            start, end = cleaned.find("{"), cleaned.rfind("}")
            if start < 0 or end <= start:
                return {"type": "answer", "answer": raw.strip()}
            value = json.loads(cleaned[start:end + 1])
        return value if isinstance(value, dict) else {"type": "answer", "answer": str(value)}
