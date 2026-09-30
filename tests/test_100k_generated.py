from __future__ import annotations

import pytest

from astra_pc.ai.mission import MissionAgent
from astra_pc.ai.router import ModelRouter
from astra_pc.core.permissions import PermissionLayer
from astra_pc.core.planner import AstraPlanner
from astra_pc.voice.commands import CommandRouter


# This module intentionally contributes exactly 100,000 collected pytest cases.
# Cases are generated from compact deterministic matrices instead of copying
# 100k functions into the repository.
_CASE_COUNTS = {
    "math_add": 20_000,
    "math_sub": 15_000,
    "math_mul": 10_000,
    "mouse": 8_000,
    "type_text": 6_000,
    "apps": 6_000,
    "paths": 8_000,
    "codegen": 8_000,
    "file_queries": 6_000,
    "permissions": 5_000,
    "routing": 4_000,
    "urls": 2_000,
    "normalize": 2_000,
}
assert sum(_CASE_COUNTS.values()) == 100_000


# ---------------------------------------------------------------------------
# 45,000 day-to-day math cases.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("case", range(_CASE_COUNTS["math_add"]))
def test_100k_math_add(case):
    a, b = divmod(case, 100)
    assert CommandRouter._math(f"calcule {a} + {b}") == f"É {a + b}."


@pytest.mark.parametrize("case", range(_CASE_COUNTS["math_sub"]))
def test_100k_math_sub(case):
    a, b = divmod(case, 100)
    assert CommandRouter._math(f"quanto é {a} - {b}?") == f"É {a - b}."


@pytest.mark.parametrize("case", range(_CASE_COUNTS["math_mul"]))
def test_100k_math_mul(case):
    a, b = divmod(case, 100)
    assert CommandRouter._math(f"quanto que é {a} vezes {b}?") == f"É {a * b}."


# ---------------------------------------------------------------------------
# 8,000 pointer commands across positive/negative coordinates and phrasings.
# ---------------------------------------------------------------------------

_MOUSE_STYLES = (
    "mova o mouse para {x}, {y}",
    "move mouse pra {x} x {y}",
    "mover o mouse para {x} {y}",
)


@pytest.mark.parametrize("case", range(_CASE_COUNTS["mouse"]))
def test_100k_mouse_routes(case):
    raw_x = (case * 37) % 4096
    raw_y = (case * 53) % 2160
    x = -raw_x if case % 17 == 0 else raw_x
    y = -raw_y if case % 19 == 0 else raw_y
    text = _MOUSE_STYLES[case % len(_MOUSE_STYLES)].format(x=x, y=y)
    plan = AstraPlanner._fast_plan(text)
    assert plan is not None
    assert plan["skill"] == "input"
    assert plan["action"] == "mouse_move"
    assert plan["args"] == {"x": x, "y": y}


# ---------------------------------------------------------------------------
# 6,000 explicit typing commands, including path-like/code-like payloads.
# This guards against regressions like "digite go test ./..." being mistaken
# for a filesystem request.
# ---------------------------------------------------------------------------

_TYPE_VERBS = ("digite", "digita", "escreva", "escreve")
_TYPE_TEMPLATES = (
    "go test ./pkg/{n}",
    "python script_{n}.py --input /tmp/data/{n}",
    "git checkout feature/test-{n}",
    "npm run test:{n}",
    "cargo test module_{n}",
    "echo /home/lex/project_{n}/file.txt",
    "https://localhost:3000/api/{n}",
    "SELECT * FROM table_{n} WHERE id = {n};",
    "console.log('case {n}')",
    "print('case {n}')",
    "pytest -q tests/test_case_{n}.py",
    "uv run python tools/job_{n}.py",
)


@pytest.mark.parametrize("case", range(_CASE_COUNTS["type_text"]))
def test_100k_type_text_precedence(case):
    verb = _TYPE_VERBS[case % len(_TYPE_VERBS)]
    template = _TYPE_TEMPLATES[(case // len(_TYPE_VERBS)) % len(_TYPE_TEMPLATES)]
    payload = template.format(n=case)
    plan = AstraPlanner._fast_plan(f"{verb} {payload}")
    assert plan is not None
    assert plan["skill"] == "input"
    assert plan["action"] == "type_text"
    assert plan["args"]["text"] == payload


# ---------------------------------------------------------------------------
# 6,000 app open/close commands.
# ---------------------------------------------------------------------------

_OPEN_VERBS = ("abra", "abre", "abrir", "open")
_CLOSE_VERBS = ("feche", "fecha", "fechar", "encerre", "encerra", "encerrar")


@pytest.mark.parametrize("case", range(_CASE_COUNTS["apps"]))
def test_100k_app_commands(case):
    app = f"app-{case % 750}"
    article = ("", "o ", "a ")[case % 3]
    if case < 3_000:
        verb = _OPEN_VERBS[case % len(_OPEN_VERBS)]
        plan = AstraPlanner._fast_plan(f"{verb} {article}{app}")
        assert plan is not None
        assert plan["skill"] == "apps"
        assert plan["action"] == "open_app"
        assert plan["args"]["name"] == app
    else:
        verb = _CLOSE_VERBS[case % len(_CLOSE_VERBS)]
        plan = AstraPlanner._fast_plan(f"{verb} {article}{app}")
        assert plan is not None
        assert plan["skill"] == "apps"
        assert plan["action"] == "close_app"
        assert plan["args"]["name"] == app


# ---------------------------------------------------------------------------
# 8,000 path extraction/routing cases.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("case", range(_CASE_COUNTS["paths"]))
def test_100k_path_routing(case):
    root = f"/home/lex/project_{case % 400}/dir_{(case * 7) % 97}"
    if case % 4 == 0:
        path = root + f"/file_{case}.txt"
        text = f'leia o arquivo "{path}"'
        expected_action = "read_file"
    elif case % 4 == 1:
        path = root
        text = f"olha {path}"
        expected_action = "list_dir"
    elif case % 4 == 2:
        path = "~/" + f"project_{case % 400}/src_{case % 53}"
        text = path
        expected_action = "list_dir"
    else:
        path = f"/tmp/astra_case_{case}/nested"
        text = f"me lista o que tem dentro de {path}"
        expected_action = "list_dir"

    assert AstraPlanner.extract_path(text) == path
    plan = AstraPlanner._fast_plan(text)
    assert plan is not None
    assert plan["skill"] == "files"
    assert plan["action"] == expected_action
    assert plan["args"]["path"] == path


# ---------------------------------------------------------------------------
# 8,000 code-generation cases across many languages/content markers.
# ---------------------------------------------------------------------------

_CODE_EXTENSIONS = (
    ("py", "print"),
    ("js", "console.log"),
    ("ts", "console.log"),
    ("java", "System.out.println"),
    ("cpp", "std::cout"),
    ("c", "puts"),
    ("cs", "Console.WriteLine"),
    ("rs", "println!"),
    ("go", "fmt.Println"),
    ("kt", "println"),
    ("swift", "print"),
    ("php", "echo"),
    ("rb", "puts"),
    ("lua", "print"),
    ("dart", "print"),
    ("sql", "SELECT"),
    ("html", "<p>"),
    ("css", "/*"),
    ("sh", "printf"),
    ("json", '"message"'),
    ("yaml", "message:"),
    ("yml", "message:"),
    ("xml", "<message>"),
    ("md", "# "),
    ("txt", ""),
    ("h", "#pragma once"),
    ("hpp", "#pragma once"),
)


@pytest.mark.parametrize("case", range(_CASE_COUNTS["codegen"]))
def test_100k_codegen(case):
    ext, token = _CODE_EXTENSIONS[case % len(_CODE_EXTENSIONS)]
    marker = f"ASTRA_CASE_{case}_OK"
    filename = f"sample_{case}.{ext}"
    goal = f"Em /tmp/astra crie {filename} que imprima {marker}."
    content = MissionAgent._code_content_for_file(goal, filename, "")
    assert marker in content
    if token:
        assert token in content


# ---------------------------------------------------------------------------
# 6,000 file count/search intents over generated roots/names/extensions.
# ---------------------------------------------------------------------------

_COUNT_ALIASES = (
    ("Python", "*.py"),
    ("JavaScript", "*.js"),
    ("TypeScript", "*.ts"),
    ("Java", "*.java"),
    ("C++", "*.cpp"),
    ("C#", "*.cs"),
    ("Rust", "*.rs"),
    ("Go", "*.go"),
    ("JSON", "*.json"),
    ("YAML", "*.yaml"),
    ("Markdown", "*.md"),
    ("texto", "*.txt"),
)


@pytest.mark.parametrize("case", range(_CASE_COUNTS["file_queries"]))
def test_100k_file_queries(case):
    agent = object.__new__(MissionAgent)
    root = f"/tmp/astra_query_{case % 1000}"
    if case < 3_000:
        alias, pattern = _COUNT_ALIASES[case % len(_COUNT_ALIASES)]
        recursive = bool(case % 2)
        tail = " recursivamente" if recursive else ""
        goal = f"Quantos arquivos {alias} existem{tail} em {root}?"
        steps = agent._direct_file_steps(goal)
        matches = [s for s in steps if s["action"] == "count_items"]
        assert matches
        assert matches[0]["args"]["path"] == root
        assert matches[0]["args"]["pattern"] == pattern
        assert matches[0]["args"]["recursive"] is recursive
    else:
        filename = f"config_{case}.json"
        goal = f"Procure {filename} dentro de {root}."
        steps = agent._direct_file_steps(goal)
        matches = [s for s in steps if s["action"] == "search_files"]
        assert matches
        assert matches[0]["args"]["root"] == root
        assert matches[0]["args"]["pattern"] == filename


# ---------------------------------------------------------------------------
# 5,000 unknown/destructive-like capabilities must fail closed.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("case", range(_CASE_COUNTS["permissions"]))
def test_100k_unknown_permissions_fail_closed(case):
    action = f"unknown_capability_{case:05d}"
    decision = PermissionLayer().evaluate(action)
    assert decision.allowed is False
    assert decision.needs_confirmation is True
    assert decision.reason == "unknown capability"


# ---------------------------------------------------------------------------
# 4,000 routing cases: complex programming work vs lightweight questions.
# ---------------------------------------------------------------------------

_COMPLEX = (
    "debug o bug {n}",
    "analisa a arquitetura do módulo {n}",
    "corrige esse código {n}",
    "refatore a classe Service{n}",
    "planeje a migração da API {n}",
    "compare as implementações {n}",
)
_SIMPLE = (
    "defina conceito_{n}",
    "me diga o que é item_{n}",
    "qual o significado de termo_{n}",
    "explique brevemente palavra_{n}",
)


_ROUTER = ModelRouter(None, None)


@pytest.mark.parametrize("case", range(_CASE_COUNTS["routing"]))
def test_100k_model_routing_complexity(case):
    if case < 2_000:
        prompt = _COMPLEX[case % len(_COMPLEX)].format(n=case)
        assert _ROUTER._complex(prompt) is True
    else:
        prompt = _SIMPLE[case % len(_SIMPLE)].format(n=case)
        assert _ROUTER._complex(prompt) is False


# ---------------------------------------------------------------------------
# 2,000 URL-opening commands should never be mistaken for local paths.
# ---------------------------------------------------------------------------

_URL_VERBS = ("abra", "abre", "abrir", "open")


@pytest.mark.parametrize("case", range(_CASE_COUNTS["urls"]))
def test_100k_url_routing(case):
    url = f"https://example.com/project/{case}/file/{case % 97}?q={case}"
    verb = _URL_VERBS[case % len(_URL_VERBS)]
    text = f"{verb} {url}"
    assert AstraPlanner.extract_path(text) is None
    plan = AstraPlanner._fast_plan(text)
    assert plan is not None
    assert plan["skill"] == "apps"
    assert plan["action"] == "open_url"
    assert plan["args"]["url"] == url


# ---------------------------------------------------------------------------
# 2,000 malformed-small-model tool schemas normalized to safe file steps.
# ---------------------------------------------------------------------------

_FILE_ACTIONS = (
    "list_dir", "search_files", "read_file", "count_items",
    "create_dir", "create_text_file", "write_file", "delete_file",
)


@pytest.mark.parametrize("case", range(_CASE_COUNTS["normalize"]))
def test_100k_file_step_normalization(case):
    action = _FILE_ACTIONS[case % len(_FILE_ACTIONS)]
    path = f"/tmp/astra_norm_{case}"
    if action == "search_files":
        args = {"root": path, "pattern": "*.py", "junk": case}
    elif action == "count_items":
        args = {"path": path, "pattern": "*.py", "recursive": bool(case % 2), "junk": case}
    elif action in {"create_text_file", "write_file"}:
        args = {"path": path + ".txt", "content": f"case {case}", "junk": case}
    elif action == "create_dir":
        args = {"path": path, "parents": True, "junk": case}
    else:
        args = {"path": path, "junk": case}

    variant = case % 3
    if variant == 0:
        raw = {"type": "skill", "skill": action, "action": action, "args": args}
    elif variant == 1:
        raw = {"type": "files", "skill": "files", "action": action, "args": args}
    else:
        raw = {"type": action, "action": action, "args": args}

    step = MissionAgent._normalize_step(raw)
    assert step["type"] == "skill"
    assert step["skill"] == "files"
    assert step["action"] == action
    assert "junk" not in step["args"]
