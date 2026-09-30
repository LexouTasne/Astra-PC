from __future__ import annotations

import fnmatch
from pathlib import Path

from .base import Skill, SkillResult


class FilesSkill(Skill):
    name = "files"
    description = (
        "List/search/read files, count folder contents, create folders and create new "
        "text files inside the user's home directory. Overwriting an existing file "
        "requires confirmation."
    )
    safe_actions = (
        "list_dir", "search_files", "read_file", "count_items",
        "create_dir", "create_text_file",
    )
    confirm_actions = ("write_file",)

    def __init__(self):
        self.home = Path.home().resolve()

    def execute(self, action: str, args: dict) -> SkillResult:
        if action == "create_dir":
            path = self._safe_path(args.get("path"))
            if path is None:
                return SkillResult(False, "Caminho de pasta inválido ou fora da sua home.")
            try:
                existed = path.exists()
                if existed and not path.is_dir():
                    return SkillResult(False, "Já existe um arquivo nesse caminho.")
                path.mkdir(parents=bool(args.get("parents", True)), exist_ok=True)
                return SkillResult(
                    True,
                    ("Pasta já existia: " if existed else "Pasta criada: ") + self._display_path(path),
                    {"path": str(path), "created": not existed},
                )
            except Exception as exc:
                return SkillResult(False, f"Não consegui criar a pasta: {exc}")

        if action in {"create_text_file", "write_file"}:
            path = self._safe_path(args.get("path"))
            if path is None:
                return SkillResult(False, "Caminho de arquivo inválido ou fora da sua home.")
            content = str(args.get("content", ""))
            if len(content.encode("utf-8")) > 1_000_000:
                return SkillResult(False, "Conteúdo grande demais (>1 MB).")
            if path.exists() and action == "create_text_file":
                return SkillResult(False, "O arquivo já existe; use write_file com confirmação para sobrescrever.")
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")
                return SkillResult(
                    True,
                    ("Arquivo criado: " if action == "create_text_file" else "Arquivo salvo: ")
                    + self._display_path(path),
                    {"path": str(path), "bytes": len(content.encode("utf-8"))},
                )
            except Exception as exc:
                return SkillResult(False, f"Não consegui salvar o arquivo: {exc}")

        if action == "count_items":
            path = self._safe_path(args.get("path") or self.home)
            if path is None or not path.is_dir():
                return SkillResult(False, "Pasta não encontrada ou fora da sua home.")
            recursive = bool(args.get("recursive", False))
            pattern = str(args.get("pattern", "*")).strip() or "*"
            try:
                iterator = path.rglob("*") if recursive else path.iterdir()
                files = folders = matched = 0
                for item in iterator:
                    if item.is_dir():
                        folders += 1
                    elif item.is_file():
                        files += 1
                    if fnmatch.fnmatch(item.name.lower(), pattern.lower()):
                        matched += 1
                if pattern == "*":
                    message = (
                        f"No total, encontrei {files + folders} item(ns): "
                        f"{files} arquivo(s) e {folders} pasta(s)."
                    )
                else:
                    message = (
                        f"Encontrei {matched} item(ns) que combinam com {pattern}. "
                        f"No total, são {files} arquivo(s) e {folders} pasta(s)."
                    )
                return SkillResult(
                    True,
                    message,
                    {
                        "path": str(path), "files": files, "folders": folders,
                        "matched": matched, "pattern": pattern, "recursive": recursive,
                    },
                )
            except Exception as exc:
                return SkillResult(False, f"Não consegui contar os itens: {exc}")

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
            if found:
                shown = [self._display_path(Path(item)) for item in found[:20]]
                suffix = ""
                if len(found) > len(shown):
                    suffix = f"\n… e mais {len(found) - len(shown)} arquivo(s)."
                message = (
                    f"Encontrei {len(found)} arquivo(s):\n"
                    + "\n".join(f"- {item}" for item in shown)
                    + suffix
                )
            else:
                message = "Encontrei 0 arquivo(s)."
            return SkillResult(
                True,
                message,
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
