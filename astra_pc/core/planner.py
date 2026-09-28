from __future__ import annotations

import difflib
import json
import re
import unicodedata
from typing import Any

from astra_pc.ai.agent import AstraBrain
from astra_pc.core.context import DesktopContext
from astra_pc.skills.manager import SkillManager


class AstraPlanner:
    """Deterministic routes first, local model only when necessary."""

    ACTIONISH = re.compile(
        r"\b(?:"
        r"abra|abre|abrir|feche|fecha|fechar|encerre|encerra|encerrar|clique|clica|clicar|"
        r"digite|digita|escreva|escreve|copie|copia|cole|cola|"
        r"mova|move|renomeie|renomear|apague|apagar|delete|deletar|"
        r"execute|executa|rodar|rode|inicie|iniciar|pare|pausar|"
        r"pause|play|toque|volume|mute|desmute|maximize|minimize|"
        r"troque|mude|salve|crie|criar|git\b|pytest\b"
        r")",
        re.I,
    )

    FILE_WORDS = (
        "arquivo", "arquivos", "pasta", "diretório", "diretorio",
        "downloads", "documentos", "documents", "desktop",
        "o que tem dentro", "oque tem dentro", "o que contém", "o que contem",
        "listar", "liste", "me lista", "mostre os arquivos",
        "conteúdo da pasta", "conteudo da pasta",
        "dentro do", "dentro da", "dentro de", "dentro dele", "dentro dela",
        "lá dentro", "la dentro", "primeiro item", "primeira pasta",
        "segundo item", "terceiro item", "item da lista",
    )

    def __init__(self, brain: AstraBrain, skills: SkillManager):
        self.brain = brain
        self.skills = skills

    @classmethod
    def needs_planning(cls, text: str) -> bool:
        q = " ".join(text.lower().strip().split())
        if cls.ACTIONISH.search(q):
            return True
        if cls.extract_path(text):
            return True
        if any(word in q for word in cls.FILE_WORDS):
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

    @staticmethod
    def _reference_key(value: str) -> str:
        normalized = unicodedata.normalize("NFKD", str(value).casefold())
        normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))
        return re.sub(r"[^a-z0-9]+", "", normalized)

    @classmethod
    def resolve_listing_reference(
        cls,
        text: str,
        listing: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        """Resolve conversational references against the last real file listing.

        This deliberately happens before the LLM planner so phrases such as
        "o primeiro item", "dentro do bestclient" and even small typos keep
        pointing at the concrete filesystem object returned by FilesSkill.
        """
        if not isinstance(listing, dict):
            return None
        entries = listing.get("entries")
        if not isinstance(entries, list) or not entries:
            return None

        q = " ".join(str(text).casefold().split())
        q_key = cls._reference_key(q)

        ordinal_patterns = (
            (0, r"\b(?:primeir[oa]|1[ºªo]?|um)\s+(?:item|arquivo|pasta|da lista)\b"),
            (1, r"\b(?:segund[oa]|2[ºªo]?)\s+(?:item|arquivo|pasta|da lista)\b"),
            (2, r"\b(?:terceir[oa]|3[ºªo]?)\s+(?:item|arquivo|pasta|da lista)\b"),
            (3, r"\b(?:quart[oa]|4[ºªo]?)\s+(?:item|arquivo|pasta|da lista)\b"),
            (4, r"\b(?:quint[oa]|5[ºªo]?)\s+(?:item|arquivo|pasta|da lista)\b"),
        )
        for index, pattern in ordinal_patterns:
            if index < len(entries) and re.search(pattern, q, re.I):
                item = entries[index]
                return item if isinstance(item, dict) else None

        # Exact/substring reference wins before fuzzy matching.
        for item in entries:
            if not isinstance(item, dict):
                continue
            name_key = cls._reference_key(item.get("name", ""))
            if len(name_key) >= 3 and name_key in q_key:
                return item

        # Pull the likely object name out of natural follow-ups.
        candidate = q
        match = re.search(
            r"(?:dentro\s+(?:do|da|de|desse|dessa|dele|dela)\s+|"
            r"(?:abre|abra|abrir|leia|ler|lista|liste|listar)\s+(?:o|a|os|as)?\s*)(.+)$",
            q,
            re.I,
        )
        if match:
            candidate = match.group(1)
        candidate = re.sub(
            r"\b(?:porra|mano|cara|pasta|arquivo|diretorio|diretório|item|lista|"
            r"ai|aí|la|lá|ne|né|pra|para|dentro|do|da|de|o|a|os|as)\b",
            " ",
            candidate,
            flags=re.I,
        )
        candidate_key = cls._reference_key(candidate)
        if len(candidate_key) < 3:
            return None

        best = None
        best_score = 0.0
        for item in entries:
            if not isinstance(item, dict):
                continue
            name_key = cls._reference_key(item.get("name", ""))
            if not name_key:
                continue
            score = difflib.SequenceMatcher(None, candidate_key, name_key).ratio()
            if candidate_key in name_key or name_key in candidate_key:
                score = max(score, 0.92)
            if score > best_score:
                best_score = score
                best = item

        return best if best_score >= 0.54 else None

    @classmethod
    def file_followup_plan(
        cls,
        text: str,
        listing: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        if cls.extract_path(text):
            return None
        if not isinstance(listing, dict):
            return None

        q = " ".join(text.casefold().strip().split())
        fileish = any(word in q for word in cls.FILE_WORDS)
        if not fileish:
            return None

        item = cls.resolve_listing_reference(text, listing)
        target = None
        item_type = None
        if item:
            target = item.get("path")
            item_type = item.get("type")

        # Pronouns like "lá dentro" refer to the directory that was just listed.
        if not target and any(
            phrase in q
            for phrase in (
                "lá dentro", "la dentro", "dentro dele", "dentro dela",
                "nessa pasta", "nesta pasta", "nesse diretório", "nesse diretorio",
                "me lista o que tem dentro", "me lista oque tem dentro",
            )
        ):
            target = listing.get("path")
            item_type = "folder"

        if not target:
            return None

        wants_read = any(
            phrase in q
            for phrase in (
                "leia", "ler arquivo", "conteúdo do arquivo", "conteudo do arquivo",
            )
        )
        action = "read_file" if wants_read or item_type == "file" else "list_dir"
        return {
            "type": "skill",
            "skill": "files",
            "action": action,
            "args": {"path": str(target)},
            "resolved_from_context": True,
        }

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
    def extract_path(text: str) -> str | None:
        # Prefer quoted paths so spaces survive intact.
        for pattern in (r'"([^"]+)"', r"'([^']+)'"):
            for match in re.finditer(pattern, text):
                value = match.group(1).strip()
                if value.startswith(("http://", "https://")):
                    continue
                if "/" in value or "\\" in value or value.startswith("~"):
                    return value.rstrip(".,;:!?")

        # Otherwise accept shell-like path tokens such as home/lex/Downloads.
        for raw in reversed(text.split()):
            value = raw.strip().strip("()[]{}<>").rstrip(".,;:!?")
            if value.startswith(("http://", "https://")):
                continue
            if "/" in value or "\\" in value or value.startswith("~"):
                return value
        return None

    @staticmethod
    def _fast_plan(text: str, context: DesktopContext | None = None) -> dict[str, Any] | None:
        q = " ".join(text.lower().strip().split())
        path = AstraPlanner.extract_path(text)

        if path:
            wants_read = any(
                phrase in q
                for phrase in (
                    "leia o arquivo",
                    "ler arquivo",
                    "conteúdo do arquivo",
                    "conteudo do arquivo",
                    "abra o arquivo e leia",
                )
            )
            if wants_read:
                return {
                    "type": "skill",
                    "skill": "files",
                    "action": "read_file",
                    "args": {"path": path},
                }

            # A path by itself, or a question about what is inside it, is a
            # directory-list request. FilesSkill will reject non-directories cleanly.
            return {
                "type": "skill",
                "skill": "files",
                "action": "list_dir",
                "args": {"path": path},
            }

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

        m = re.search(
            r"\b(?:feche|fecha|fechar|encerre|encerra|encerrar)\s+"
            r"(?:o\s+|a\s+)?([\w.+À-ÿ-]+)",
            q,
        )
        if m:
            return {
                "type": "skill",
                "skill": "apps",
                "action": "close_app",
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
