from __future__ import annotations

import json
import re
from typing import Any

from astra_pc.ai.agent import AstraBrain
from astra_pc.core.context import DesktopContext
from astra_pc.skills.manager import SkillManager


class AstraPlanner:
    """Deterministic routes first, local model only when necessary."""

    ACTIONISH = re.compile(
        r"^\s*(?:por\s+favor\s+)?(?:"
        r"abra|abre|abrir|feche|fecha|fechar|clique|clica|clicar|"
        r"digite|digita|escreva|escreve|copie|copia|cole|cola|"
        r"mova|move|renomeie|renomear|apague|apagar|delete|deletar|"
        r"execute|executa|rodar|rode|inicie|iniciar|pare|pausar|"
        r"pause|play|toque|volume|mute|desmute|maximize|minimize|"
        r"troque|mude|salve|crie|criar|git\b|pytest\b"
        r")",
        re.I,
    )

    def __init__(self, brain: AstraBrain, skills: SkillManager):
        self.brain = brain
        self.skills = skills

    @classmethod
    def needs_planning(cls, text: str) -> bool:
        q = " ".join(text.lower().strip().split())
        if cls.ACTIONISH.search(q):
            return True
        return any(
            phrase in q
            for phrase in (
                "status do pc",
                "status do computador",
                "status do sistema",
                "processos pesados",
                "top processos",
                "o que está pesando",
                "o que esta pesando",
                "ler clipboard",
                "área de transferência",
                "area de transferencia",
                "rodar rotina",
                "executar rotina",
            )
        )

    def plan(
        self,
        text: str,
        context: DesktopContext,
        accessibility: list[dict[str, Any]] | None = None,
        memories: list[dict[str, Any]] | None = None,
        reference: dict[str, Any] | None = None,
        browser_dom: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        fast = self._fast_plan(text, context)
        if fast:
            return fast

        prompt = {
            "request": text,
            "context": context.as_dict(),
            "skills": self.skills.describe(),
            "relevant_memory": (memories or [])[:6],
            "resolved_reference": reference or {},
            "accessibility": (accessibility or [])[:35],
            "browser_dom": (browser_dom or [])[:35],
            "schema": {
                "type": "skill|answer",
                "skill": "skill name",
                "action": "action name",
                "args": {},
                "answer": "text when type=answer",
            },
        }
        raw = self.brain.ask(
            "Planeje este pedido de desktop. Retorne APENAS um objeto JSON compacto. "
            "Use uma skill somente quando ela realmente corresponder a uma skill disponível. "
            "Use memória relevante somente quando ajudar. "
            "Nunca invente capacidades. Se houver campo 'answer', escreva-o em português do Brasil.\n"
            + json.dumps(prompt, ensure_ascii=False)
        )
        return self._json(raw)

    @staticmethod
    def _fast_plan(text: str, context: DesktopContext | None = None) -> dict[str, Any] | None:
        q = " ".join(text.lower().strip().split())

        url = re.search(r"https?://\S+", text)
        if url and re.search(r"\b(abre|abra|abrir|open)\b", q):
            return {
                "type": "skill",
                "skill": "apps",
                "action": "open_url",
                "args": {"url": url.group(0).rstrip(".,)")},
            }

        m = re.search(r"\b(?:abre|abra|abrir|open)\s+(?:o\s+|a\s+)?([\w.+À-ÿ-]+)", q)
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

        if any(x in q for x in ("o que copiei", "ler clipboard", "ler área de transferência", "ler area de transferencia")):
            return {"type": "skill", "skill": "clipboard", "action": "clipboard_read", "args": {}}

        m = re.search(r"^(?:copie|copiar|clipboard)\s+(.+)$", text.strip(), re.I)
        if m:
            return {
                "type": "skill",
                "skill": "clipboard",
                "action": "clipboard_write",
                "args": {"text": m.group(1)},
            }

        if q in {"git status", "status do git"}:
            return {
                "type": "skill",
                "skill": "git",
                "action": "git_status",
                "args": {"repo": context.cwd if context else "."},
            }
        if q in {"git diff", "diff do git"}:
            return {
                "type": "skill",
                "skill": "git",
                "action": "git_diff",
                "args": {"repo": context.cwd if context else "."},
            }
        if q in {"qual branch", "branch atual", "git branch"}:
            return {
                "type": "skill",
                "skill": "git",
                "action": "git_branch",
                "args": {"repo": context.cwd if context else "."},
            }

        if q in {"rode os testes", "rodar testes", "run tests", "pytest"}:
            return {
                "type": "skill",
                "skill": "coding",
                "action": "run_tests",
                "args": {"root": context.cwd if context else "."},
            }

        return None

    @staticmethod
    def _json(raw: str) -> dict[str, Any]:
        cleaned = raw.strip()
        fence = chr(96) * 3
        if cleaned.startswith(fence):
            cleaned = re.sub(r"^" + re.escape(fence) + r"(?:json)?\s*", "", cleaned)
            cleaned = re.sub(r"\s*" + re.escape(fence) + r"$", "", cleaned)
        try:
            value = json.loads(cleaned)
        except Exception:
            start, end = cleaned.find("{"), cleaned.rfind("}")
            if start < 0 or end <= start:
                return {"type": "answer", "answer": raw.strip()}
            value = json.loads(cleaned[start:end + 1])
        return value if isinstance(value, dict) else {"type": "answer", "answer": str(value)}
