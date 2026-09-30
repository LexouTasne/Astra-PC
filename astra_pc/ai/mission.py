from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .ollama_client import OllamaClient
from .soul import planner_soul


MISSION_SYSTEM = """You are Astra's tool planner. Return exactly one JSON object and nothing else.
Use only listed skills/actions. Prefer a skill over visual clicking.
Intent map: list/liste -> list_dir; read/leia -> read_file; count/conte/quantos -> count_items; search/procure/encontre -> search_files; create folder/pasta -> create_dir; create file/arquivo -> create_text_file; delete/apague -> delete_file.
When the goal contains an explicit file path, use it as the base path/root.
For file operations, skill MUST be "files" and action is the file action such as create_dir or list_dir.
For create_dir, include the requested new folder name in path.
For create_text_file/write_file, path MUST include the requested filename and extension, never only a directory.
For deletion requests, use files.delete_file only; never simulate deletion with write_file.
If the goal names multiple files, handle one file per step and continue until every requested file is verified.
Never claim success before a tool result confirms it.

Valid shapes:
{"type":"skill","skill":"name","action":"name","args":{},"reason":"brief"}
{"type":"visual","goal":"subgoal","reason":"brief"}
{"type":"swarm","goal":"subgoal","count":4,"vision":false,"reason":"brief"}
{"type":"answer","message":"final answer","reason":"done"}

If history already proves the goal is complete, answer from that result.
If a tool failed, choose a different safe step. If confirmation is required, stop and explain it.
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
        fallback_client: OllamaClient | None = None,
        skill_provider: Callable[[], list[dict[str, Any]]],
        context_provider: Callable[[], str],
        execute_skill: Callable[[dict[str, Any]], dict[str, Any]],
        execute_visual: Callable[[str], dict[str, Any]],
        execute_swarm: Callable[[str, int, bool], dict[str, Any]],
        cancel_event=None,
        max_steps: int = 12,
    ) -> None:
        self.client = client
        self.fallback_client = fallback_client
        self.skill_provider = skill_provider
        self.context_provider = context_provider
        self.execute_skill = execute_skill
        self.execute_visual = execute_visual
        self.execute_swarm = execute_swarm
        self.cancel_event = cancel_event
        self.max_steps = max(1, min(40, int(max_steps)))
        self._active_skills: list[dict[str, Any]] = []

    def run(self, goal: str) -> MissionResult:
        goal = str(goal).strip()
        if not goal:
            return MissionResult(False, "Empty mission goal.", [])

        history: list[dict[str, Any]] = []
        direct_steps = self._direct_file_steps(goal)
        if direct_steps:
            direct_messages: list[str] = []
            for index, step in enumerate(direct_steps, 1):
                if self._cancelled():
                    return MissionResult(False, "Stopped by user.", history)
                result = self.execute_skill(step)
                history.append({
                    "index": index,
                    "type": "skill",
                    "reason": "deterministic file fast-path",
                    "request": self._compact_step(step),
                    "result": self._compact_result(result),
                })
                if not result.get("ok"):
                    return MissionResult(
                        False,
                        str(result.get("error") or result.get("message") or "Falha na ação."),
                        history,
                    )
                message = str(result.get("message") or "").strip()
                if str(step.get("action")) == "read_file":
                    data = result.get("data") if isinstance(result.get("data"), dict) else {}
                    text = str(data.get("text") or "")
                    if text:
                        message = (message + " Conteúdo: " + text[:4000]).strip()
                if message:
                    direct_messages.append(message)
            details = direct_messages or [
                str(item.get("result", {}).get("message", "")).strip()
                for item in history
                if str(item.get("result", {}).get("message", "")).strip()
            ]
            return MissionResult(
                True,
                " ".join(details) or "Concluído. As ações foram verificadas.",
                history,
            )

        last_signature = ""
        repeated = 0
        self._active_skills = self._skills_for_goal(goal)

        for step_index in range(1, self.max_steps + 1):
            if self._cancelled():
                return MissionResult(False, "Stopped by user.", history)

            # Explicit paths make desktop/chat context unnecessary and expensive.
            # Keep context only for referential goals such as "essa pasta" or "lá".
            context = "" if self._explicit_path(goal) else self.context_provider()
            planner_skills = [
                {
                    "name": str(item.get("name", "")),
                    "safe": list(item.get("safe_actions") or ()),
                    "confirm": list(item.get("confirm_actions") or ()),
                }
                for item in self._active_skills
            ]
            planner_history = []
            for item in history[-3:]:
                result = item.get("result") if isinstance(item.get("result"), dict) else {}
                planner_history.append({
                    "request": item.get("request"),
                    "ok": bool(result.get("ok")),
                    "message": str(result.get("message") or result.get("error") or "")[:500],
                })

            prompt = {
                "goal": goal,
                "step": step_index,
                "skills": planner_skills,
            }
            if context:
                prompt["context"] = context[-320:]
            if planner_history:
                prompt["history"] = planner_history

            encoded_prompt = json.dumps(
                prompt,
                ensure_ascii=False,
                separators=(",", ":"),
            )
            step = self._request_step("State:" + encoded_prompt)
            step = self._fill_file_args_from_goal(goal, step)
            step = self._repair_file_step_from_goal(goal, step, history)
            signature = self._step_signature(step)
            if signature and signature == last_signature:
                repeated += 1
                if (
                    history
                    and str(step.get("type", "")).lower() == "skill"
                    and bool(history[-1].get("result", {}).get("ok"))
                    and self._tool_result_completes_goal(goal, step)
                ):
                    previous = history[-1]
                    return MissionResult(
                        True,
                        str(previous.get("result", {}).get("message") or "Concluído."),
                        history,
                    )
            else:
                repeated = 0
            last_signature = signature

            if repeated >= 2 and step.get("type") != "answer":
                step = self._request_step(
                    "State:"
                    + encoded_prompt
                    + "\nDo not repeat the previous step. Choose a different safe step or answer."
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

            if result.get("ok") and self._requested_file_creation_complete(goal, history):
                messages = [
                    str((item.get("result") or {}).get("message") or "").strip()
                    for item in history
                    if bool((item.get("result") or {}).get("ok"))
                    and str((item.get("request") or {}).get("action", "")).lower()
                    in {"create_text_file", "write_file"}
                ]
                return MissionResult(
                    True,
                    " ".join(message for message in messages if message) or "Arquivos criados.",
                    history,
                )

            if result.get("ok") and self._tool_result_completes_goal(goal, step):
                return MissionResult(
                    True,
                    self._tool_result_message(step, result),
                    history,
                )

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

    @staticmethod
    def _explicit_path(text: str) -> str | None:
        quoted = re.search(r'["\']((?:~|/|(?:var/)?home/)[^"\']+)["\']', text)
        if quoted:
            return quoted.group(1).rstrip(".,;:!?")
        match = re.search(
            r"(?<![A-Za-z0-9_])((?:~|/|(?:var/)?home/)[^\s,;]+)",
            text,
        )
        return match.group(1).rstrip(".,;:!?") if match else None

    def _direct_file_steps(self, goal: str) -> list[dict[str, Any]]:
        base = self._explicit_path(goal)
        if not base:
            return []

        named_files = self._named_file_mentions(goal)
        creation_intent = bool(re.search(
            r"\b(?:crie|criar|cria|monte|montar|prepare|preparar|gere|gerar)\b",
            goal,
            re.I,
        ))
        delete_intent = bool(re.search(
            r"\b(?:apague|apagar|delete|deletar|exclua|excluir|remova|remover)\b",
            goal,
            re.I,
        ))

        # Explicit destructive action: keep confirmation in the skill layer, but
        # skip LLM planning when the target path is already unambiguous.
        if delete_intent and not re.search(
            r"\b(?:liste|listar|quantos|quantas|conte|leia|procure|encontre|localize)\b",
            goal,
            re.I,
        ):
            target = base
            if not Path(base).suffix and named_files:
                target = str(Path(base).expanduser() / named_files[0])
            return [{
                "type": "skill", "skill": "files", "action": "delete_file",
                "args": {"path": target},
            }]

        # Explicit file creation by full filename is deterministic even when the
        # user omits the word "arquivo", e.g. "crie /home/lex/demo.py ...".
        folder_creation_intent = bool(re.search(
            r"\b(?:crie|criar|cria|prepare|preparar|monte|montar)\b"
            r"[^.!?\n]{0,100}\b(?:pasta|subpasta)\b",
            goal,
            re.I,
        ))
        if creation_intent and len(named_files) == 1 and not folder_creation_intent:
            filename = named_files[0]
            base_path = Path(base).expanduser()
            target = base_path if base_path.name == filename else base_path / filename
            content = self._code_content_for_file(goal, filename, "")
            if not content:
                raw_content = re.search(
                    r"(?:com\s+(?:o\s+)?conte[uú]do|contendo(?:\s+exatamente)?)"
                    r"\s*:?[ \t]*(.+)$",
                    goal,
                    re.I,
                )
                if raw_content:
                    content = raw_content.group(1).strip()
                    # Spoken requests often end the sentence after code.
                    if content.endswith(".") and len(content) > 1:
                        content = content[:-1].rstrip()
            return [{
                "type": "skill", "skill": "files", "action": "create_text_file",
                "args": {"path": str(target), "content": content},
            }]

        # Explicit multi-file code generation can be compiled directly into file
        # tool calls. Ambiguous requests still fall back to the model planner.
        if creation_intent and len(named_files) >= 2:
            generated: list[dict[str, Any]] = []
            for filename in named_files:
                content = self._code_content_for_file(goal, filename, "")
                if not content:
                    generated = []
                    break
                generated.append({
                    "type": "skill", "skill": "files", "action": "create_text_file",
                    "args": {
                        "path": str(Path(base).expanduser() / filename),
                        "content": content,
                    },
                })
            if generated:
                return generated
            return []

        # Creating an explicit absolute folder or a named subfolder is also
        # deterministic and should not spend a model round-trip.
        if creation_intent and not named_files:
            folder_name = self._requested_folder_name(goal)
            if folder_name and Path(base).name != folder_name:
                return [{
                    "type": "skill", "skill": "files", "action": "create_dir",
                    "args": {"path": str(Path(base).expanduser() / folder_name), "parents": True},
                }]
            if re.search(r"\bpasta\b[^\n]{0,80}?(?:/|~)", goal, re.I):
                return [{
                    "type": "skill", "skill": "files", "action": "create_dir",
                    "args": {"path": base, "parents": True},
                }]

        steps: list[dict[str, Any]] = []
        folder_match = re.search(
            r"\b(?:crie|criar|cria)\s+(?:(?:uma|a)\s+)?pasta"
            r"(?:\s+nova)?(?:\s+(?:chamada|com\s+o\s+nome\s+de))?\s+([\w.-]+)",
            goal,
            re.I,
        )
        folder_target: str | None = None
        if folder_match:
            folder_name = folder_match.group(1).rstrip(".,;:")
            folder_target = str(Path(base).expanduser() / folder_name)
            steps.append({
                "type": "skill",
                "skill": "files",
                "action": "create_dir",
                "args": {"path": folder_target, "parents": True},
            })

        file_match = re.search(
            r"\b(?:crie|criar|cria)\s+(?:(?:um|o)\s+)?arquivo"
            r"(?:\s+novo)?(?:\s+(?:chamado|com\s+o\s+nome\s+de))?\s+([\w.-]+)",
            goal,
            re.I,
        )
        if file_match:
            quoted_content = re.search(
                r"contendo(?:\s+exatamente)?\s+[\"']([^\"']*)[\"']",
                goal,
                re.I,
            )
            content_match = re.search(
                r"contendo(?:\s+exatamente)?\s*:?[ \t]*(.+?)"
                r"(?=\.\s*(?:depois|em\s+seguida|quando)\b|$)",
                goal,
                re.I,
            )
            content = (
                quoted_content.group(1)
                if quoted_content
                else (content_match.group(1).strip().rstrip(".,;:") if content_match else "")
            )
            parent = folder_target or str(Path(base).expanduser())
            steps.append({
                "type": "skill",
                "skill": "files",
                "action": "create_text_file",
                "args": {
                    "path": str(Path(parent) / file_match.group(1).rstrip(".,;:")),
                    "content": content,
                },
            })

        q = goal.lower()

        wants_read = bool(re.search(r"\b(?:leia|ler|lê|le)\b", q)) or (
            ("conteúdo" in q or "conteudo" in q) and "arquivo" in q
        )
        if wants_read:
            steps.append({
                "type": "skill",
                "skill": "files",
                "action": "read_file",
                "args": {"path": base},
            })

        list_phrases = (
            "o que tem", "o que contém", "o que contem", "o que existe",
            "me diga o que tem", "mostre o que tem", "mostra o que tem",
            "mostre o conteúdo de", "mostra o conteúdo de",
            "mostre o conteudo de", "mostra o conteudo de",
            "quais arquivos", "quais pastas", "quais itens", "inventário", "inventario",
            "quais arquivos tem", "quais pastas tem", "quais itens tem",
        )
        if re.search(r"\b(?:liste|listar|lista)\b", q) or any(
            phrase in q for phrase in list_phrases
        ):
            steps.append({
                "type": "skill",
                "skill": "files",
                "action": "list_dir",
                "args": {"path": base, "limit": 100},
            })

        extension_aliases = (
            (r"\b(?:python|scripts?\s+python|arquivos?\s+py)\b", "*.py"),
            (r"\b(?:javascript|java\s*script|node(?:\.js)?|js)\b", "*.js"),
            (r"\b(?:typescript|type\s*script|ts)\b", "*.ts"),
            (r"\b(?:jsx|react\s+jsx)\b", "*.jsx"),
            (r"\b(?:tsx|react\s+tsx)\b", "*.tsx"),
            (r"\bjava\b", "*.java"),
            (r"(?<!\w)(?:c\+\+|cpp)(?!\w)", "*.cpp"),
            (r"\bcxx\b", "*.cxx"),
            (r"(?<!\w)cc(?!\w)", "*.cc"),
            (r"\b(?:hpp|header\s+c\+\+|headers\s+c\+\+)\b", "*.hpp"),
            (r"\b(?:csharp|c\s*sharp)\b|(?<!\w)c#(?!\w)", "*.cs"),
            (r"\b(?:linguagem\s+c|arquivos?\s+c)(?!#)\b|(?<!\w)c(?![\w#+])", "*.c"),
            (r"\b(?:header\s+c|headers\s+c|arquivos?\s+h)\b", "*.h"),
            (r"\brust\b", "*.rs"),
            (r"\bgolang\b|\blinguagem\s+go\b|\barquivos?\s+go\b|\bgo\b", "*.go"),
            (r"\bkotlin\b", "*.kt"),
            (r"\bswift\b", "*.swift"),
            (r"\bphp\b", "*.php"),
            (r"\bruby\b", "*.rb"),
            (r"\blua\b", "*.lua"),
            (r"\bdart\b", "*.dart"),
            (r"\bsql\b", "*.sql"),
            (r"\bhtml\b", "*.html"),
            (r"\bcss\b", "*.css"),
            (r"\b(?:shell|bash)\b", "*.sh"),
            (r"\bjson\b", "*.json"),
            (r"\byaml\b", "*.yaml"),
            (r"\byml\b", "*.yml"),
            (r"\bxml\b", "*.xml"),
            (r"\b(?:markdown|arquivos?\s+md)\b", "*.md"),
            (r"\b(?:texto|textos|arquivos?\s+txt)\b", "*.txt"),
            (r"\bpng\b", "*.png"),
            (r"\b(?:jpg|jpeg)\b", "*.jpg"),
        )
        count_terms = ("arquivo", "arquivos", "item", "itens", "pasta", "pastas", "coisa", "coisas", "script", "scripts", "texto", "textos")
        natural_extension_hint = any(
            re.search(pattern, q, re.I) for pattern, _ in extension_aliases
        )
        if re.search(r"\b(?:conte|contar|quantos|quantas)\b", q) and (
            any(term in q for term in count_terms) or natural_extension_hint
        ):
            glob = "*"
            glob_match = re.search(r"(\*\.[A-Za-z0-9]+)", goal)
            ext_match = re.search(r"arquivos?\s+(\.[A-Za-z0-9]+)", goal, re.I)
            if glob_match:
                glob = glob_match.group(1)
            elif ext_match:
                glob = "*" + ext_match.group(1)
            else:
                for pattern, alias_glob in extension_aliases:
                    if re.search(pattern, q, re.I):
                        glob = alias_glob
                        break
            steps.append({
                "type": "skill",
                "skill": "files",
                "action": "count_items",
                "args": {
                    "path": base,
                    "pattern": glob,
                    "recursive": bool(re.search(r"recursiv|subpast", q)),
                },
            })

        search_pattern: str | None = None
        contains_match = re.search(
            r"\b(?:cujo\s+nome|nome)\s+(?:contenha|contém|contem|tenha)\s+([\w*?.-]+)",
            goal,
            re.I,
        )
        if contains_match:
            token = contains_match.group(1).rstrip(".,;:!?")
            search_pattern = token if "*" in token or "?" in token else f"*{token}*"
        else:
            name_match = re.search(
                r"\b(?:arquivos?|pastas?)\s+com\s+([\w*?.-]+)\s+no\s+nome\b",
                goal,
                re.I,
            )
            por_match = re.search(
                r"\bpor\s+(?:(?:um|o)\s+arquivo\s+)?(?:chamado\s+)?([\w*?.-]+)",
                goal,
                re.I,
            )
            simple_match = re.search(
                r"\b(?:localize|encontre|procure|procura|buscar|busque|busca|ache|acha|achar)\s+"
                r"(?:o\s+arquivo\s+|a\s+pasta\s+)?([\w*?.-]+)",
                goal,
                re.I,
            )
            candidate = name_match or por_match or simple_match
            if candidate:
                token = candidate.group(1).rstrip(".,;:!?")
                generic = {
                    "dentro", "em", "na", "no", "por", "um", "uma",
                    "arquivo", "arquivos", "pasta", "pastas",
                }
                if token.lower() not in generic:
                    if "*" not in token and "?" not in token and "." not in token:
                        search_pattern = f"*{token}*"
                    else:
                        search_pattern = token

        if search_pattern:
            steps.append({
                "type": "skill",
                "skill": "files",
                "action": "search_files",
                "args": {
                    "root": base,
                    "pattern": search_pattern,
                    "limit": 100,
                },
            })

        return steps

    def _fill_file_args_from_goal(
        self,
        goal: str,
        step: dict[str, Any],
    ) -> dict[str, Any]:
        if str(step.get("skill", "")).lower() != "files":
            return step

        base = self._explicit_path(goal)
        if not base:
            return step

        normalized = dict(step)
        args = dict(normalized.get("args") or {})
        action = str(normalized.get("action", "")).lower()
        if action in {"list_dir", "read_file", "count_items", "delete_file"} and not args.get("path"):
            args["path"] = base
        elif action == "search_files" and not args.get("root"):
            args["root"] = base
        normalized["args"] = args
        return normalized

    @staticmethod
    def _named_file_mentions(goal: str) -> list[str]:
        extensions = (
            "py|js|ts|jsx|tsx|java|cpp|cxx|cc|c|h|hpp|cs|rs|go|kt|swift|"
            "php|rb|lua|dart|sql|html|css|sh|json|yaml|yml|xml|md|txt"
        )
        found = re.findall(
            rf"(?<![A-Za-z0-9_.-])([A-Za-z0-9_][A-Za-z0-9_.-]*\.(?:{extensions}))(?![A-Za-z0-9_-])",
            goal,
            re.I,
        )
        return list(dict.fromkeys(found))

    @staticmethod
    def _requested_folder_name(goal: str) -> str | None:
        match = re.search(
            r"\b(?:subpasta|pasta)\b[^.!?\n]{0,60}?\b(?:chamada|nome\s+de)\s+([\w.-]+)",
            goal,
            re.I,
        )
        return match.group(1).rstrip(".,;:!?") if match else None

    @staticmethod
    def _code_content_for_file(goal: str, filename: str, fallback: str) -> str:
        lower = goal.lower()
        pos = lower.find(filename.lower())
        if pos < 0:
            return fallback
        segment = goal[pos:pos + 260].split(";", 1)[0]
        marker_match = re.search(r"\bimprima\s+(.+)$", segment, re.I)
        if not marker_match:
            return fallback
        marker = marker_match.group(1).strip().strip("\"'").rstrip(".,;:!?")
        for stop in (" Só finalize", " Use a ferramenta", " Depois", " Em seguida"):
            marker = marker.split(stop, 1)[0].strip().rstrip(".,;:!?")
        if not marker:
            return fallback
        escaped = marker.replace("\\", "\\\\").replace('"', '\\"')
        suffix = Path(filename).suffix.lower()
        stem = re.sub(r"\W+", "_", Path(filename).stem) or "Main"
        if suffix == ".py":
            return f'print("{escaped}")\n'
        if suffix in {".js", ".ts", ".jsx", ".tsx"}:
            return f'console.log("{escaped}");\n'
        if suffix == ".java":
            return (
                f"public class {stem} {{\n"
                "    public static void main(String[] args) {\n"
                f'        System.out.println("{escaped}");\n'
                "    }\n"
                "}\n"
            )
        if suffix in {".cpp", ".cxx", ".cc"}:
            return (
                "#include <iostream>\n"
                "int main() {\n"
                f'    std::cout << "{escaped}" << std::endl;\n'
                "    return 0;\n"
                "}\n"
            )
        if suffix == ".c":
            return (
                "#include <stdio.h>\n"
                "int main(void) {\n"
                f'    puts("{escaped}");\n'
                "    return 0;\n"
                "}\n"
            )
        if suffix == ".cs":
            return (
                "using System;\n"
                "class Program {\n"
                f'    static void Main() => Console.WriteLine("{escaped}");\n'
                "}\n"
            )
        if suffix in {".h", ".hpp"}:
            return f'#pragma once\n#define ASTRA_MESSAGE "{escaped}"\n'
        if suffix == ".rs":
            return f'fn main() {{ println!("{escaped}"); }}\n'
        if suffix == ".go":
            return (
                'package main\n\nimport "fmt"\n\n'
                f'func main() {{ fmt.Println("{escaped}") }}\n'
            )
        if suffix == ".kt":
            return f'fun main() {{ println("{escaped}") }}\n'
        if suffix == ".swift":
            return f'print("{escaped}")\n'
        if suffix == ".php":
            return f'<?php\necho "{escaped}\\n";\n'
        if suffix == ".rb":
            return f'puts "{escaped}"\n'
        if suffix == ".lua":
            return f'print("{escaped}")\n'
        if suffix == ".dart":
            return f'void main() {{ print("{escaped}"); }}\n'
        if suffix == ".sql":
            return "SELECT '" + marker.replace("'", "''") + "';\n"
        if suffix == ".html":
            return f'<p>{marker}</p>\n'
        if suffix == ".css":
            return f'/* {marker} */\n'
        if suffix == ".sh":
            return f'#!/usr/bin/env bash\nprintf \'%s\\n\' "{escaped}"\n'
        if suffix == ".json":
            return json.dumps({"message": marker}, ensure_ascii=False, indent=2) + "\n"
        if suffix in {".yaml", ".yml"}:
            return f'message: "{escaped}"\n'
        if suffix == ".xml":
            return f'<message>{marker}</message>\n'
        if suffix == ".md":
            return f'# {marker}\n'
        if suffix == ".txt":
            return marker + "\n"
        return fallback

    def _repair_file_step_from_goal(
        self,
        goal: str,
        step: dict[str, Any],
        history: list[dict[str, Any]],
    ) -> dict[str, Any]:
        if str(step.get("type", "")).lower() != "skill" or str(step.get("skill", "")).lower() != "files":
            return step

        normalized = dict(step)
        args = dict(normalized.get("args") or {})
        base = self._explicit_path(goal)
        action = str(normalized.get("action", "")).lower()
        mentions = self._named_file_mentions(goal)
        q = " ".join(str(goal).lower().split())

        # Deterministic intent repair: a tiny planner can confuse list/search/count.
        # When the user wording is unambiguous, prefer the parser's verified action.
        direct = self._direct_file_steps(goal)
        if len(mentions) <= 1 and re.search(
            r"\b(?:crie|criar|cria|monte|montar|prepare|preparar|gere|gerar)\b",
            q,
        ):
            for candidate in direct:
                if candidate.get("action") in {"create_dir", "create_text_file"}:
                    return candidate
        if re.search(r"\b(?:conte|contar|quantos|quantas)\b", q):
            for candidate in direct:
                if candidate.get("action") == "count_items":
                    return candidate
        if re.search(r"\b(?:procure|procurar|encontre|localize|buscar|busque|ache)\b", q):
            for candidate in direct:
                if candidate.get("action") == "search_files":
                    return candidate

        delete_intent = bool(re.search(
            r"\b(?:apague|apagar|delete|deletar|exclua|excluir|remova|remover)\b",
            goal,
            re.I,
        ))
        deleted_already = any(
            str((item.get("request") or {}).get("action", "")).lower() == "delete_file"
            and bool((item.get("result") or {}).get("ok"))
            for item in history
        )
        if delete_intent and not deleted_already and base:
            target = base
            if not Path(base).suffix and mentions:
                target = str(Path(base).expanduser() / mentions[0])
            normalized["action"] = "delete_file"
            normalized["args"] = {"path": target}
            return normalized

        if action == "create_dir" and base:
            folder_name = self._requested_folder_name(goal)
            current = str(args.get("path") or "")
            if folder_name and Path(base).name != folder_name and (
                not current or Path(current).expanduser() == Path(base).expanduser()
            ):
                args["path"] = str(Path(base).expanduser() / folder_name)
                normalized["args"] = args
                return normalized

        if action in {"create_text_file", "write_file"} and base and mentions:
            completed = {
                Path(str((item.get("request") or {}).get("args", {}).get("path", ""))).name
                for item in history
                if bool((item.get("result") or {}).get("ok"))
                and str((item.get("request") or {}).get("action", "")).lower()
                in {"create_text_file", "write_file"}
            }
            remaining = [name for name in mentions if name not in completed]
            current_path = str(args.get("path") or "")
            current_name = Path(current_path).name if current_path else ""
            chosen = current_name if current_name in remaining else (remaining[0] if remaining else None)
            if chosen:
                base_path = Path(base).expanduser()
                target = base_path if base_path.name == chosen else base_path / chosen
                args["path"] = str(target)
                args["content"] = self._code_content_for_file(
                    goal,
                    chosen,
                    str(args.get("content") or ""),
                )
                normalized["args"] = args

        return normalized

    def _requested_file_creation_complete(
        self,
        goal: str,
        history: list[dict[str, Any]],
    ) -> bool:
        requested = self._named_file_mentions(goal)
        if not requested or not re.search(
            r"\b(?:crie|criar|cria|monte|montar|prepare|preparar|gere|gerar)\b",
            goal,
            re.I,
        ):
            return False
        completed = {
            Path(str((item.get("request") or {}).get("args", {}).get("path", ""))).name
            for item in history
            if bool((item.get("result") or {}).get("ok"))
            and str((item.get("request") or {}).get("action", "")).lower()
            in {"create_text_file", "write_file"}
        }
        return set(requested).issubset(completed)

    @staticmethod
    def _tool_result_completes_goal(goal: str, step: dict[str, Any]) -> bool:
        if str(step.get("skill", "")).lower() != "files":
            return False

        q = " ".join(str(goal).lower().split())
        action = str(step.get("action", "")).lower()
        creation_requested = bool(re.search(
            r"\b(?:crie|criar|cria|monte|montar|prepare|preparar|gere|gerar)\b",
            q,
            re.I,
        ))
        followup_requested = any(
            cue in q
            for cue in (
                "liste", "listar", "quantos", "quantas", "conte", "leia", "ler",
                "procure", "encontre", "localize", "apague", "delete", "exclua", "remova",
            )
        )
        named_files = MissionAgent._named_file_mentions(goal)
        if action == "create_dir":
            return creation_requested and not named_files and not followup_requested
        if action in {"create_text_file", "write_file"}:
            return creation_requested and len(named_files) == 1 and not followup_requested
        if action == "delete_file":
            delete_requested = bool(re.search(
                r"\b(?:apague|apagar|delete|deletar|exclua|excluir|remova|remover)\b",
                q,
                re.I,
            ))
            followup_requested = any(
                cue in q
                for cue in (
                    "liste", "listar", "quantos", "quantas", "conte", "leia",
                    "procure", "encontre", "localize", "quais arquivos sobraram",
                )
            )
            return delete_requested and not followup_requested

        cues = {
            "list_dir": (
                "liste", "listar", "lista", "o que tem", "o que existe",
                "o que contém", "o que contem", "quais arquivos", "quais pastas",
                "examine", "examinar", "descreva o que encontrar",
            ),
            "read_file": (
                "leia", "ler", "conteúdo", "conteudo", "mostra o conteúdo",
                "mostre o conteúdo",
            ),
            "search_files": (
                "localize", "encontre", "procure", "busca", "buscar", "ache",
                "acha", "onde está", "onde esta",
            ),
            "count_items": (
                "conte", "contar", "quantos", "quantas",
            ),
        }
        return any(cue in q for cue in cues.get(action, ()))

    @staticmethod
    def _tool_result_message(step: dict[str, Any], result: dict[str, Any]) -> str:
        message = str(result.get("message") or "").strip()
        if (
            str(step.get("skill", "")).lower() == "files"
            and str(step.get("action", "")).lower() == "read_file"
        ):
            data = result.get("data") if isinstance(result.get("data"), dict) else {}
            text = str(data.get("text") or "")
            if text:
                message = (message + " Conteúdo: " + text[:4000]).strip()
        return message or "Concluído."

    @staticmethod
    def _normalize_step(step: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(step, dict):
            return step
        normalized = dict(step)
        file_actions = {
            "list_dir", "search_files", "read_file", "count_items", "create_dir",
            "create_text_file", "write_file", "delete_file",
        }
        step_type = str(normalized.get("type", "")).lower()
        skill_name = str(normalized.get("skill", "")).lower()
        action_name = str(normalized.get("action", "")).lower()

        natural_file_aliases = {
            "list": "list_dir", "liste": "list_dir", "listar": "list_dir",
            "read": "read_file", "leia": "read_file", "ler": "read_file",
            "count": "count_items", "conte": "count_items", "quantos": "count_items",
            "search": "search_files", "procure": "search_files", "encontre": "search_files",
            "delete": "delete_file", "apague": "delete_file", "deletar": "delete_file",
            "create folder": "create_dir", "pasta": "create_dir",
            "create file": "create_text_file", "arquivo": "create_text_file",
        }
        if skill_name not in {"files", *file_actions}:
            alias_tokens = {
                token.strip()
                for token in re.split(r"[/|,;]+", skill_name)
                if token.strip()
            }
            alias_action = next(
                (
                    natural_file_aliases[token]
                    for token in alias_tokens
                    if token in natural_file_aliases
                ),
                None,
            )
            if alias_action:
                normalized["skill"] = "files"
                skill_name = "files"
                if action_name not in file_actions:
                    normalized["action"] = alias_action
                    action_name = alias_action

        # Small local models sometimes use "files" as the step type. Repair that
        # common schema slip before validation instead of wasting another inference.
        if step_type == "files":
            normalized["type"] = "skill"
            normalized["skill"] = "files"
        elif step_type in file_actions:
            normalized["type"] = "skill"
            normalized["skill"] = "files"
            normalized.setdefault("action", step_type)
        if skill_name in file_actions:
            normalized["skill"] = "files"
            if not action_name:
                normalized["action"] = skill_name
        if str(normalized.get("skill", "")).lower() != "files":
            return normalized

        args = normalized.get("args")
        if not isinstance(args, dict):
            return normalized
        allowed = {
            "list_dir": {"path", "limit"},
            "search_files": {"root", "pattern", "limit"},
            "read_file": {"path"},
            "count_items": {"path", "pattern", "recursive"},
            "create_dir": {"path", "parents"},
            "create_text_file": {"path", "content"},
            "write_file": {"path", "content"},
            "delete_file": {"path"},
        }
        action = str(normalized.get("action", "")).lower()
        keys = allowed.get(action)
        if keys is not None:
            normalized["args"] = {key: value for key, value in args.items() if key in keys}
        return normalized

    def _skills_for_goal(self, goal: str) -> list[dict[str, Any]]:
        all_skills = [
            item for item in self.skill_provider()
            if isinstance(item, dict) and item.get("name")
        ]
        q = " ".join(str(goal).lower().split())
        aliases = {
            "files": (
                "arquivo", "arquivos", "pasta", "pastas", "diretório", "diretorio",
                "caminho", "localiz", "procur", "buscar", "contar", "apag", "exclu",
                "delet", "remov", "file", "folder",
            ),
            "apps": ("aplicativo", "app ", "abrir ", "abra ", "fechar ", "chrome", "firefox", "discord"),
            "system": ("cpu", "ram", "memória", "memoria", "disco", "sistema", "processo"),
            "git": ("git", "commit", "branch", "repositório", "repositorio"),
            "coding": ("código", "codigo", "python", "projeto", "programa", "script"),
            "terminal": ("terminal", "comando", "shell"),
            "clipboard": ("clipboard", "área de transferência", "area de transferencia", "copiar", "colar"),
            "windows": ("janela", "monitor", "minimizar", "maximizar"),
            "input_control": ("mouse", "teclado", "clic", "digitar", "tecla"),
            "viewport": ("zoom", "rotação", "rotacao"),
            "notifications": ("notificação", "notificacao", "aviso"),
        }
        names = {
            name for name, words in aliases.items()
            if any(word in q for word in words)
        }
        if not names:
            return all_skills[:8]
        selected = [item for item in all_skills if str(item.get("name")) in names]
        return selected or all_skills[:8]

    def _request_step(self, prompt: str, attempts: int = 3) -> dict[str, Any]:
        last_error = "invalid mission step"
        repair = ""
        for attempt in range(1, max(1, int(attempts)) + 1):
            if self._cancelled():
                return {"type": "answer", "message": "Stopped by user."}
            use_fallback = (
                self.fallback_client is not None
                and attempt == max(1, int(attempts))
            )
            client = self.fallback_client if use_fallback else self.client
            raw = client.chat(
                prompt + repair,
                system=MISSION_SYSTEM + "\n" + planner_soul(),
                temperature=0.02 if attempt > 1 else 0.05,
                num_ctx=2048 if use_fallback else 1024,
                num_predict=140 if use_fallback else 96,
                think=False,
                format="json",
            )
            try:
                step = self._normalize_step(self._parse_json(raw))
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
            source = self._active_skills or self.skill_provider()
            described = {
                str(item.get("name", "")): item
                for item in source
                if isinstance(item, dict)
            }
            if skill not in described:
                return f"unknown skill: {skill}"
            allowed_actions = set(described[skill].get("safe_actions") or ())
            allowed_actions.update(described[skill].get("confirm_actions") or ())
            if allowed_actions and action not in allowed_actions:
                return f"unknown action for {skill}: {action}"
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
