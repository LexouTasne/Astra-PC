from __future__ import annotations

import fnmatch
from pathlib import Path

from .base import Skill, SkillResult


class FilesSkill(Skill):
    name = "files"
    description = (
        "List folders, search files and read text files inside the user's home directory."
    )
    safe_actions = ("list_dir", "search_files", "read_file")

    def __init__(self):
        self.home = Path.home().resolve()

    def execute(self, action: str, args: dict) -> SkillResult:
        if action == "list_dir":
            path = self._safe_path(args.get("path") or self.home)
            if path is None or not path.is_dir():
                return SkillResult(False, "Pasta não encontrada ou fora da sua home.")

            limit = max(1, min(250, int(args.get("limit", 100))))
            try:
                children = sorted(
                    path.iterdir(),
                    key=lambda item: (not item.is_dir(), item.name.casefold()),
                )
            except PermissionError:
                return SkillResult(False, f"Sem permissão para ler {path}.")
            except Exception as exc:
                return SkillResult(False, f"Não consegui listar {path}: {exc}")

            shown = children[:limit]
            entries = []
            for item in shown:
                try:
                    stat = item.stat()
                    size = int(stat.st_size) if item.is_file() else None
                except Exception:
                    size = None
                entries.append({
                    "name": item.name,
                    "path": str(item),
                    "type": "folder" if item.is_dir() else "file",
                    "size": size,
                })

            display = self._display_path(path)
            if not entries:
                message = f"A pasta {display} está vazia."
            else:
                lines = [
                    f"- {entry['name']}{'/' if entry['type'] == 'folder' else ''}"
                    for entry in entries
                ]
                suffix = ""
                if len(children) > len(entries):
                    suffix = f"\n… e mais {len(children) - len(entries)} item(ns)."
                message = (
                    f"Em {display}, encontrei {len(children)} item(ns):\n"
                    + "\n".join(lines)
                    + suffix
                )
            return SkillResult(
                True,
                message,
                {
                    "path": str(path),
                    "display_path": display,
                    "entries": entries,
                    "total": len(children),
                    "truncated": len(children) > len(entries),
                },
            )

        if action == "search_files":
            pattern = str(args.get("pattern", "*")).strip() or "*"
            limit = max(1, min(100, int(args.get("limit", 25))))
            root = self._safe_path(args.get("root") or self.home)
            if root is None or not root.exists():
                return SkillResult(False, "Raiz de busca inválida.")

            found = []
            try:
                for path in root.rglob("*"):
                    if len(found) >= limit:
                        break
                    if path.is_file() and fnmatch.fnmatch(
                        path.name.lower(),
                        pattern.lower(),
                    ):
                        found.append(str(path))
            except PermissionError:
                pass
            return SkillResult(
                True,
                f"Encontrei {len(found)} arquivo(s).",
                {"files": found},
            )

        if action == "read_file":
            path = self._safe_path(args.get("path"))
            if path is None or not path.is_file():
                return SkillResult(
                    False,
                    "Arquivo não encontrado ou fora da sua home.",
                )
            if path.stat().st_size > 1_000_000:
                return SkillResult(
                    False,
                    "Arquivo grande demais para leitura rápida (>1 MB).",
                )
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except Exception as exc:
                return SkillResult(False, str(exc))
            return SkillResult(
                True,
                f"Li {self._display_path(path)}.",
                {"text": text[:50_000], "path": str(path)},
            )

        return SkillResult(False, f"Ação de arquivos desconhecida: {action}")

    def _safe_path(self, raw) -> Path | None:
        if raw is None:
            return None
        try:
            text = str(raw).strip().strip("'").strip('"')
            if not text:
                return None

            slash = text.replace("\\", "/")
            username = self.home.name
            aliases = (
                f"home/{username}",
                f"/home/{username}",
                f"var/home/{username}",
                f"/var/home/{username}",
            )

            path = None
            for alias in aliases:
                if slash == alias:
                    path = self.home
                    break
                prefix = alias.rstrip("/") + "/"
                if slash.startswith(prefix):
                    path = self.home / slash[len(prefix):]
                    break

            if path is None:
                candidate = Path(text).expanduser()
                if candidate.is_absolute():
                    path = candidate
                else:
                    path = self.home / candidate

            resolved = path.resolve()
            resolved.relative_to(self.home)
            return resolved
        except Exception:
            return None

    def _display_path(self, path: Path) -> str:
        try:
            rel = path.resolve().relative_to(self.home)
            return "~" if not rel.parts else f"~/{rel.as_posix()}"
        except Exception:
            return str(path)
