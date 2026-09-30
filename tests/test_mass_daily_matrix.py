from __future__ import annotations

from pathlib import Path

import pytest

from astra_pc.ai.mission import MissionAgent
from astra_pc.ai.router import ModelRouter
from astra_pc.core.planner import AstraPlanner
from astra_pc.voice.commands import CommandRouter


# ---------------------------------------------------------------------------
# 1,440 real clock outputs: every minute of a day.
# ---------------------------------------------------------------------------

_NUMBERS = {
    0: "zero", 1: "um", 2: "dois", 3: "três", 4: "quatro", 5: "cinco",
    6: "seis", 7: "sete", 8: "oito", 9: "nove", 10: "dez", 11: "onze",
    12: "doze", 13: "treze", 14: "quatorze", 15: "quinze",
    16: "dezesseis", 17: "dezessete", 18: "dezoito", 19: "dezenove",
    20: "vinte", 21: "vinte e um", 22: "vinte e dois", 23: "vinte e três",
    24: "vinte e quatro", 25: "vinte e cinco", 26: "vinte e seis",
    27: "vinte e sete", 28: "vinte e oito", 29: "vinte e nove",
    30: "trinta", 31: "trinta e um", 32: "trinta e dois", 33: "trinta e três",
    34: "trinta e quatro", 35: "trinta e cinco", 36: "trinta e seis",
    37: "trinta e sete", 38: "trinta e oito", 39: "trinta e nove",
    40: "quarenta", 41: "quarenta e um", 42: "quarenta e dois",
    43: "quarenta e três", 44: "quarenta e quatro", 45: "quarenta e cinco",
    46: "quarenta e seis", 47: "quarenta e sete", 48: "quarenta e oito",
    49: "quarenta e nove", 50: "cinquenta", 51: "cinquenta e um",
    52: "cinquenta e dois", 53: "cinquenta e três", 54: "cinquenta e quatro",
    55: "cinquenta e cinco", 56: "cinquenta e seis", 57: "cinquenta e sete",
    58: "cinquenta e oito", 59: "cinquenta e nove",
}


def _expected_time(hour: int, minute: int) -> str:
    if hour == 0:
        if minute == 0:
            return "Agora é meia-noite."
        if minute == 30:
            return "Agora é meia-noite e meia."
        return f"Agora é meia-noite e {_NUMBERS[minute]}."
    if hour == 12:
        if minute == 0:
            return "Agora é meio-dia."
        if minute == 30:
            return "Agora é meio-dia e meia."
        return f"Agora é meio-dia e {_NUMBERS[minute]}."

    spoken = hour % 12
    hour_word = "uma" if spoken == 1 else _NUMBERS[spoken]
    if 0 <= hour <= 5:
        period = "da madrugada"
    elif hour <= 11:
        period = "da manhã"
    elif hour <= 18:
        period = "da tarde"
    else:
        period = "da noite"
    prefix = "Agora é" if spoken == 1 else "Agora são"
    if minute == 0:
        return f"{prefix} {hour_word} {period}."
    if minute == 30:
        return f"{prefix} {hour_word} e meia {period}."
    return f"{prefix} {hour_word} e {_NUMBERS[minute]} {period}."


CLOCK_CASES = [(h, m) for h in range(24) for m in range(60)]


@pytest.mark.parametrize("hour,minute", CLOCK_CASES)
def test_all_minutes_spoken_ptbr(hour, minute):
    assert CommandRouter._format_time(hour, minute) == _expected_time(hour, minute)


# ---------------------------------------------------------------------------
# Daily desktop planner phrases.
# ---------------------------------------------------------------------------

APPS = [
    "firefox", "discord", "spotify", "chrome", "brave", "steam", "konsole",
    "code", "obs", "vlc", "telegram", "thunderbird", "dolphin", "kate", "gimp",
]
OPEN_CASES = [
    (f"{verb} {article}{app}", app)
    for verb in ("abra", "abre", "abrir", "open")
    for article in ("", "o ")
    for app in APPS
]


@pytest.mark.parametrize("text,app", OPEN_CASES)
def test_daily_open_app_phrases(text, app):
    plan = AstraPlanner._fast_plan(text)
    assert plan == {
        "type": "skill", "skill": "apps", "action": "open_app", "args": {"name": app}
    }


CLOSE_CASES = [
    (f"{verb} {article}{app}", app)
    for verb in ("feche", "fecha", "fechar", "encerre", "encerra", "encerrar")
    for article in ("", "o ")
    for app in APPS
]


@pytest.mark.parametrize("text,app", CLOSE_CASES)
def test_daily_close_app_phrases(text, app):
    plan = AstraPlanner._fast_plan(text)
    assert plan == {
        "type": "skill", "skill": "apps", "action": "close_app", "args": {"name": app}
    }


TYPE_TEXTS = [
    "hello world", "teste 123", "git status", "npm run dev", "python main.py",
    "cargo test", "go test ./...", "pytest -q", "console.log('ok')", "print('ok')",
    "SELECT * FROM users;", "sudo rpm-ostree status", "ollama ps", "astra status",
    "README.md", "TODO: corrigir bug", "feat: add cache", "fix: voice latency",
    "http://localhost:3000", "127.0.0.1:8765", "Richard Mateus", "Astra-PC",
    "Ctrl Shift P", "docker compose up", "uv run pytest",
]
TYPE_CASES = [(f"{verb} {value}", value) for verb in ("digite", "digita", "escreva", "escreve") for value in TYPE_TEXTS]


@pytest.mark.parametrize("text,value", TYPE_CASES)
def test_daily_type_text_phrases(text, value):
    plan = AstraPlanner._fast_plan(text)
    assert plan["skill"] == "input"
    assert plan["action"] == "type_text"
    assert plan["args"]["text"] == value


COORDS = [
    (0, 0), (1, 1), (50, 50), (100, 200), (200, 100), (640, 360), (960, 540),
    (1279, 719), (1280, 720), (1919, 1079), (1920, 1080), (-1, 10), (10, -1),
    (300, 900), (1500, 400), (42, 84), (512, 512), (1366, 768), (1600, 900), (800, 600),
]
MOVE_CASES = []
for x, y in COORDS:
    MOVE_CASES.extend([
        (f"mova o mouse para {x}, {y}", x, y),
        (f"move mouse pra {x} x {y}", x, y),
        (f"mover o mouse para {x} {y}", x, y),
    ])


@pytest.mark.parametrize("text,x,y", MOVE_CASES)
def test_daily_mouse_move_phrases(text, x, y):
    plan = AstraPlanner._fast_plan(text)
    assert plan["skill"] == "input"
    assert plan["action"] == "mouse_move"
    assert plan["args"] == {"x": x, "y": y}


VOLUME_CASES = [(f"volume {value}", value) for value in range(101)]


@pytest.mark.parametrize("text,value", VOLUME_CASES)
def test_every_volume_value_routes_locally(text, value):
    plan = AstraPlanner._fast_plan(text)
    assert plan == {
        "type": "skill", "skill": "system", "action": "volume", "args": {"value": value}
    }


# ---------------------------------------------------------------------------
# Math useful for voice/day-to-day.
# ---------------------------------------------------------------------------

ADD_CASES = [(a, b) for a in range(0, 21) for b in range(0, 11)]
SUB_CASES = [(a, b) for a in range(0, 21) for b in range(0, 6)]
MUL_CASES = [(a, b) for a in range(0, 13) for b in range(0, 13)]


@pytest.mark.parametrize("a,b", ADD_CASES)
def test_voice_math_addition_matrix(a, b):
    assert CommandRouter().execute(f"quanto é {a} + {b}?").message == f"É {a + b}."


@pytest.mark.parametrize("a,b", SUB_CASES)
def test_voice_math_subtraction_matrix(a, b):
    assert CommandRouter().execute(f"calcule {a} - {b}").message == f"É {a - b}."


@pytest.mark.parametrize("a,b", MUL_CASES)
def test_voice_math_multiplication_matrix(a, b):
    assert CommandRouter().execute(f"quanto que é {a} vezes {b}?").message == f"É {a * b}."


# ---------------------------------------------------------------------------
# Realistic path parsing / file routing.
# ---------------------------------------------------------------------------

BASE_DIRS = [
    "/home/lex/Downloads", "/home/lex/Documents", "/home/lex/Desktop",
    "/home/lex/Astra-PC", "/var/home/lex/Downloads", "~/Downloads",
    "~/Documents", "~/Projetos", "/tmp/astra-test", "/home/lex/.config/astra",
]
PATH_SUFFIXES = [
    "", "/src", "/tests", "/docs", "/assets", "/config", "/scripts", "/logs",
    "/README.md", "/main.py",
]
PATH_CASES = [base + suffix for base in BASE_DIRS for suffix in PATH_SUFFIXES]


@pytest.mark.parametrize("path", PATH_CASES)
def test_path_token_is_not_lost(path):
    assert AstraPlanner.extract_path(f"olha {path}") == path


@pytest.mark.parametrize("path", PATH_CASES)
def test_bare_path_routes_to_files(path):
    plan = AstraPlanner._fast_plan(path)
    assert plan["skill"] == "files"
    assert plan["action"] == "list_dir"
    assert plan["args"]["path"] == path


# ---------------------------------------------------------------------------
# Programming/code-generation behavior.
# ---------------------------------------------------------------------------

LANGUAGES = {
    "main.py": "print(",
    "app.js": "console.log(",
    "app.ts": "console.log(",
    "Main.java": "System.out.println(",
    "engine.cpp": "std::cout",
    "engine.c": "puts(",
    "Program.cs": "Console.WriteLine(",
    "tool.rs": "println!(",
    "server.go": "fmt.Println(",
    "Main.kt": "println(",
    "main.swift": "print(",
    "index.php": "echo ",
    "task.rb": "puts ",
    "game.lua": "print(",
    "main.dart": "print(",
    "query.sql": "SELECT '",
    "index.html": "<p>",
    "style.css": "/* ",
    "run.sh": "printf ",
    "config.json": '"message"',
    "config.yaml": "message:",
    "config.xml": "<message>",
    "README.md": "# ",
    "notes.txt": "",
    "common.h": "#pragma once",
    "common.hpp": "#pragma once",
}
MARKERS = [
    "ASTRA OK", "HELLO WORLD", "CACHE READY", "TEST PASSED", "VOICE READY",
    "MODEL READY", "FILES READY", "GIT CLEAN", "BUILD OK", "SERVER UP",
]


CODE_CASES = [(filename, token, marker) for filename, token in LANGUAGES.items() for marker in MARKERS]


@pytest.mark.parametrize("filename,token,marker", CODE_CASES)
def test_programming_generation_many_languages(filename, token, marker):
    goal = f"Em /tmp/astra crie {filename} que imprima {marker}."
    content = MissionAgent._code_content_for_file(goal, filename, "")
    assert marker in content
    if token:
        assert token in content


EXTENSION_QUERIES = [
    ("Python", "*.py"), ("JavaScript", "*.js"), ("TypeScript", "*.ts"),
    ("Java", "*.java"), ("CPP", "*.cpp"), ("C++", "*.cpp"), ("C", "*.c"),
    ("HPP", "*.hpp"), ("C#", "*.cs"), ("Rust", "*.rs"), ("Go", "*.go"),
    ("Kotlin", "*.kt"), ("Swift", "*.swift"), ("PHP", "*.php"), ("Ruby", "*.rb"),
    ("Lua", "*.lua"), ("Dart", "*.dart"), ("SQL", "*.sql"), ("HTML", "*.html"),
    ("CSS", "*.css"), ("Shell", "*.sh"), ("JSON", "*.json"), ("YAML", "*.yaml"),
    ("Markdown", "*.md"), ("texto", "*.txt"),
]
COUNT_TEMPLATES = [
    "Quantos arquivos {name} existem em /tmp/astra?",
    "Conte os arquivos {name} em /tmp/astra.",
    "Quantos {name} existem recursivamente em /tmp/astra?",
]


@pytest.mark.parametrize(
    "query,pattern",
    [(template.format(name=name), pattern) for name, pattern in EXTENSION_QUERIES for template in COUNT_TEMPLATES],
)
def test_programming_extension_queries(query, pattern):
    agent = object.__new__(MissionAgent)
    steps = agent._direct_file_steps(query)
    assert any(
        step["action"] == "count_items" and step["args"].get("pattern") == pattern
        for step in steps
    )


# ---------------------------------------------------------------------------
# Model selection/routing regressions.
# ---------------------------------------------------------------------------

COMPLEX_VERBS = [
    "analisa", "analisar", "compare", "comparar", "debug", "corrige", "corrigir",
    "arquitetura", "planeje", "planejar", "refatore", "refatorar",
]
COMPLEX_OBJECTS = [
    "esse código", "esse projeto", "a API", "o banco", "o bug", "o daemon",
    "o fluxo de voz", "o planner", "o cache", "o repositório",
]
COMPLEX_CASES = [f"{verb} {obj}" for verb in COMPLEX_VERBS for obj in COMPLEX_OBJECTS]


@pytest.mark.parametrize("prompt", COMPLEX_CASES)
def test_model_router_programming_complexity(prompt):
    router = ModelRouter(type("C", (), {"model": "text"})(), type("C", (), {"model": "vision"})())
    assert router._complex(prompt)


SIMPLE_CASES = [
    f"{prefix} {subject}"
    for prefix in ("o que é", "me diga", "defina")
    for subject in (
        "cache", "ram", "ssd", "cpu", "gpu", "python", "java", "rust", "git", "json",
        "yaml", "http", "api", "loop", "lista", "tupla", "classe", "objeto", "variável", "função",
    )
]


@pytest.mark.parametrize("prompt", SIMPLE_CASES)
def test_model_router_daily_simple_prompts(prompt):
    router = ModelRouter(type("C", (), {"model": "text"})(), type("C", (), {"model": "vision"})())
    assert not router._complex(prompt)


# Sanity: this file intentionally contributes > 2k individually collected cases.
def test_mass_matrix_case_budget():
    approximate = (
        len(CLOCK_CASES) + len(OPEN_CASES) + len(CLOSE_CASES) + len(TYPE_CASES)
        + len(MOVE_CASES) + len(VOLUME_CASES) + len(ADD_CASES) + len(SUB_CASES)
        + len(MUL_CASES) + 2 * len(PATH_CASES) + len(CODE_CASES)
        + len(EXTENSION_QUERIES) * len(COUNT_TEMPLATES)
        + len(COMPLEX_CASES) + len(SIMPLE_CASES)
    )
    assert approximate > 2400
