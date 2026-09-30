from __future__ import annotations

import json

import pytest

from astra_pc.ai.mission import MissionAgent
from astra_pc.ai.router import ModelRouter
from astra_pc.core.permissions import PermissionLayer
from astra_pc.core.planner import AstraPlanner
from astra_pc.voice.commands import CommandRouter


class FakeClient:
    def __init__(self, model: str, models=None):
        self.model = model
        self._models = list(models or [])

    def models(self):
        return list(self._models)


@pytest.mark.parametrize("action", sorted(PermissionLayer.SAFE))
def test_permission_safe_matrix(action):
    decision = PermissionLayer().evaluate(action)
    assert decision.allowed is True
    assert decision.needs_confirmation is False


@pytest.mark.parametrize("action", sorted(PermissionLayer.CONFIRM))
def test_permission_confirmation_matrix(action):
    decision = PermissionLayer().evaluate(action)
    assert decision.allowed is True
    assert decision.needs_confirmation is True
    assert "confirmation" in decision.reason


@pytest.mark.parametrize("action", sorted(PermissionLayer.BLOCKED_AUTONOMOUS))
def test_permission_blocked_matrix(action):
    decision = PermissionLayer().evaluate(action)
    assert decision.allowed is False
    assert decision.needs_confirmation is True


@pytest.mark.parametrize(
    "action",
    [
        "launch_missiles",
        "erase_everything",
        "unknown_action",
        "teleport",
        "root_everything",
        "buy_random_item",
        "disable_antivirus_magic",
        "format_every_drive",
        "steal_passwords",
        "invent_tool",
    ],
)
def test_permission_unknown_matrix(action):
    decision = PermissionLayer().evaluate(action)
    assert decision.allowed is False
    assert decision.needs_confirmation is True
    assert decision.reason == "unknown capability"


@pytest.mark.parametrize(
    "prompt",
    [
        "analisa esse projeto",
        "analisar esse bug",
        "compare as duas arquiteturas",
        "comparar implementações",
        "debug esse erro",
        "corrige esse código",
        "corrigir a função",
        "arquitetura do sistema",
        "planeje a migração",
        "planejar uma solução",
        "refatore esse módulo",
        "refatorar a classe",
        "explique detalhadamente isso",
        "reason about this problem",
        "analyze this repository",
        "x" * 651,
    ],
)
def test_model_router_complex_matrix(prompt):
    text = FakeClient("text")
    vision = FakeClient("vision")
    strong = FakeClient("strong:4b", ["strong:4b"])
    router = ModelRouter(text, vision, strong)
    assert router._complex(prompt) is True


@pytest.mark.parametrize(
    "prompt",
    [
        "oi",
        "bom dia",
        "qual seu nome",
        "me diga algo curto",
        "2 + 2",
        "abre?",
        "status",
        "cache",
        "python",
        "uma frase pequena",
    ],
)
def test_model_router_simple_matrix(prompt):
    router = ModelRouter(FakeClient("text"), FakeClient("vision"), FakeClient("strong:4b"))
    assert router._complex(prompt) is False


def test_model_router_choose_vision_matrix():
    text = FakeClient("text")
    vision = FakeClient("vision")
    strong = FakeClient("strong:4b", ["strong:4b"])
    assert ModelRouter(text, vision, strong).choose("analisa", has_images=True) is vision


def test_model_router_choose_text_when_simple_matrix():
    text = FakeClient("text")
    vision = FakeClient("vision")
    strong = FakeClient("strong:4b", ["strong:4b"])
    assert ModelRouter(text, vision, strong).choose("oi") is text


def test_model_router_choose_strong_when_complex_installed_matrix():
    text = FakeClient("text", ["strong:4b"])
    vision = FakeClient("vision")
    strong = FakeClient("strong:4b")
    assert ModelRouter(text, vision, strong).choose("debug esse erro") is strong


def test_model_router_falls_back_when_strong_missing_matrix():
    text = FakeClient("text", ["text:latest"])
    vision = FakeClient("vision")
    strong = FakeClient("strong:4b")
    assert ModelRouter(text, vision, strong).choose("debug esse erro") is text


@pytest.mark.parametrize(
    "text",
    [
        "abra o firefox",
        "abre o discord",
        "feche o navegador",
        "encerre o spotify",
        "clique aqui",
        "digite hello",
        "escreva teste",
        "mova o mouse para 10, 20",
        "copie isso",
        "cole aqui",
        "volume 30",
        "maximize a janela",
        "minimize a janela",
        "salve isso",
        "crie uma pasta",
        "git status",
        "rode os testes",
        "pytest",
        "apague o arquivo",
        "renomeie o arquivo",
        "home/lex/Downloads",
        "o que tem dentro da pasta",
        "me lista o que tem dentro",
        "status do pc",
        "status do computador",
        "status do sistema",
        "processos pesados",
        "top processos",
        "ler clipboard",
        "área de transferência",
    ],
)
def test_planner_needs_planning_positive_matrix(text):
    assert AstraPlanner.needs_planning(text) is True


@pytest.mark.parametrize(
    "text",
    [
        "oi",
        "qual seu nome",
        "me explica cache",
        "quanto é um mais um",
        "como funciona uma cpu",
        "qual a capital do brasil",
        "conte uma piada",
        "o que é rust",
        "me fale sobre java",
        "boa tarde",
        "obrigado",
        "você está aí",
        "qual a diferença entre ram e ssd",
        "explique recursão",
    ],
)
def test_planner_needs_planning_negative_matrix(text):
    assert AstraPlanner.needs_planning(text) is False


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ('leia "~/Documents/minha nota.txt"', "~/Documents/minha nota.txt"),
        ("abra '/home/lex/arquivo com espaço.txt'", "/home/lex/arquivo com espaço.txt"),
        ("home/lex/Downloads", "home/lex/Downloads"),
        ("/home/lex/Downloads", "/home/lex/Downloads"),
        ("~/Downloads", "~/Downloads"),
        ("olha /tmp/teste", "/tmp/teste"),
        ("arquivo C:\\Users\\Lex\\x.txt", "C:\\Users\\Lex\\x.txt"),
        ("veja /home/lex/teste.txt.", "/home/lex/teste.txt"),
        ("em /var/home/lex/projeto;", "/var/home/lex/projeto"),
        ("pasta ~/Projeto!", "~/Projeto"),
        ("https://example.com", None),
        ("abra https://example.com", None),
        ("sem caminho aqui", None),
        ("arquivo simples.txt", None),
        ("texto /a/b/c)", "/a/b/c"),
        ('url "https://example.com/a/b"', None),
    ],
)
def test_planner_extract_path_matrix(text, expected):
    assert AstraPlanner.extract_path(text) == expected


@pytest.mark.parametrize(
    ("text", "skill", "action", "expected_args"),
    [
        ("abre firefox", "apps", "open_app", {"name": "firefox"}),
        ("abra o discord", "apps", "open_app", {"name": "discord"}),
        ("feche spotify", "apps", "close_app", {"name": "spotify"}),
        ("encerre o chrome", "apps", "close_app", {"name": "chrome"}),
        ("mova o mouse para 100, 200", "input", "mouse_move", {"x": 100, "y": 200}),
        ("move mouse pra -10 x 35", "input", "mouse_move", {"x": -10, "y": 35}),
        ("clique", "input", "mouse_click", {}),
        ("clica aqui", "input", "mouse_click", {}),
        ("clique direito", "input", "mouse_right_click", {}),
        ("botão direito", "input", "mouse_right_click", {}),
        ("digite Olá mundo", "input", "type_text", {"text": "Olá mundo"}),
        ("escreva teste 123", "input", "type_text", {"text": "teste 123"}),
        ("scroll pra cima", "input", "mouse_scroll", {"amount": 5}),
        ("role para baixo", "input", "mouse_scroll", {"amount": -5}),
        ("ctrl+c", "input", "hotkey", {"keys": ["ctrl", "c"]}),
        ("pressione ctrl v", "input", "hotkey", {"keys": ["ctrl", "v"]}),
        ("faça alt tab", "input", "hotkey", {"keys": ["alt", "tab"]}),
        ("aumenta o zoom", "viewport", "zoom_in", {}),
        ("diminui zoom", "viewport", "zoom_out", {}),
        ("zoom normal", "viewport", "zoom_reset", {}),
        ("gira a tela para esquerda", "viewport", "rotate_left", {}),
        ("rotaciona a tela para direita", "viewport", "rotate_right", {}),
        ("reseta a rotação", "viewport", "rotation_reset", {}),
        ("volume 42", "system", "volume", {"value": 42}),
        ("status do pc", "system", "status", {}),
        ("processos pesados", "system", "top_processes", {}),
        ("pause", "system", "media", {"command": "pause"}),
        ("tocar música", "system", "media", {"command": "play"}),
        ("próxima música", "system", "media", {"command": "next"}),
        ("o que copiei", "clipboard", "clipboard_read", {}),
        ("copie texto importante", "clipboard", "clipboard_write", {"text": "texto importante"}),
        ("git status", "git", "git_status", {"repo": "."}),
        ("git diff", "git", "git_diff", {"repo": "."}),
        ("qual branch", "git", "git_branch", {"repo": "."}),
        ("rode os testes", "coding", "run_tests", {"root": "."}),
        ("pytest", "coding", "run_tests", {"root": "."}),
        ('leia o arquivo "~/Documents/nota.txt"', "files", "read_file", {"path": "~/Documents/nota.txt"}),
        ("home/lex/Downloads", "files", "list_dir", {"path": "home/lex/Downloads"}),
    ],
)
def test_planner_fast_plan_matrix(text, skill, action, expected_args):
    plan = AstraPlanner._fast_plan(text)
    assert plan is not None
    assert plan["skill"] == skill
    assert plan["action"] == action
    assert plan["args"] == expected_args


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("oi", "Oi."),
        ("olá", "Oi."),
        ("opa", "Oi."),
        ("e aí", "Oi."),
        ("qual seu nome?", "Meu nome é Astra."),
        ("como você se chama?", "Meu nome é Astra."),
        ("seu nome", "Meu nome é Astra."),
        ("quem te criou?", "Fui criada por Richard Mateus, também conhecido como Lex."),
        ("seu criador", "Fui criada por Richard Mateus, também conhecido como Lex."),
        ("tá aí?", "Tô aqui."),
        ("você tá aí?", "Tô aqui."),
        ("obrigado", "Tamo junto."),
        ("valeu", "Tamo junto."),
        ("vlw", "Tamo junto."),
    ],
)
def test_command_instant_reply_matrix(text, expected):
    assert CommandRouter().execute(text).message == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("quanto é 1 + 1?", "É 2."),
        ("quanto e 10 menos 3?", "É 7."),
        ("quanto que é 3 vezes 4?", "É 12."),
        ("quanto que e 20 dividido por 5?", "É 4."),
        ("calcule 2 * (3 + 4)", "É 14."),
        ("calcula -5 + 2", "É -3."),
        ("quanto é três mais cinco?", "É 8."),
        ("quanto é vinte dividido por quatro?", "É 5."),
        ("quanto é 2,5 + 0,5?", "É 3."),
        ("calcule 7 x 8", "É 56."),
    ],
)
def test_command_math_matrix(text, expected):
    assert CommandRouter().execute(text).message == expected


@pytest.mark.parametrize(
    ("hour", "minute", "expected"),
    [
        (0, 0, "Agora é meia-noite."),
        (0, 30, "Agora é meia-noite e meia."),
        (1, 0, "Agora é uma da madrugada."),
        (6, 0, "Agora são seis da manhã."),
        (11, 30, "Agora são onze e meia da manhã."),
        (12, 0, "Agora é meio-dia."),
        (12, 30, "Agora é meio-dia e meia."),
        (13, 0, "Agora é uma da tarde."),
        (18, 31, "Agora são seis e trinta e um da tarde."),
        (19, 0, "Agora são sete da noite."),
    ],
)
def test_command_time_format_matrix(hour, minute, expected):
    assert CommandRouter._format_time(hour, minute) == expected


@pytest.mark.parametrize(
    ("filename", "marker", "needle"),
    [
        ("main.py", "PY OK", 'print("PY OK")'),
        ("app.js", "JS OK", 'console.log("JS OK")'),
        ("app.ts", "TS OK", 'console.log("TS OK")'),
        ("Main.java", "JAVA OK", 'System.out.println("JAVA OK")'),
        ("engine.cpp", "CPP OK", 'std::cout << "CPP OK"'),
        ("engine.c", "C OK", 'puts("C OK")'),
        ("Program.cs", "CS OK", 'Console.WriteLine("CS OK")'),
        ("tool.rs", "RUST OK", 'println!("RUST OK")'),
        ("server.go", "GO OK", 'fmt.Println("GO OK")'),
        ("main.kt", "KT OK", 'println("KT OK")'),
        ("main.swift", "SWIFT OK", 'print("SWIFT OK")'),
        ("task.rb", "RB OK", 'puts "RB OK"'),
        ("game.lua", "LUA OK", 'print("LUA OK")'),
        ("config.json", "JSON OK", '"message": "JSON OK"'),
        ("readme.md", "MD OK", "# MD OK"),
    ],
)
def test_mission_code_generation_matrix(filename, marker, needle):
    goal = f"Em /tmp/astra crie {filename} que imprima {marker}."
    content = MissionAgent._code_content_for_file(goal, filename, "")
    assert needle in content


@pytest.mark.parametrize(
    ("goal", "pattern"),
    [
        ("Quantos arquivos Python existem em /tmp/astra?", "*.py"),
        ("Quantos JavaScript existem em /tmp/astra?", "*.js"),
        ("Quantos TypeScript existem em /tmp/astra?", "*.ts"),
        ("Quantos Java existem em /tmp/astra?", "*.java"),
        ("Quantos CPP existem em /tmp/astra?", "*.cpp"),
        ("Quantos C++ existem em /tmp/astra?", "*.cpp"),
        ("Quantos arquivos C existem em /tmp/astra?", "*.c"),
        ("Quantos HPP existem em /tmp/astra?", "*.hpp"),
        ("Quantos C# existem em /tmp/astra?", "*.cs"),
        ("Quantos Rust existem em /tmp/astra?", "*.rs"),
        ("Quantos arquivos Go existem em /tmp/astra?", "*.go"),
        ("Quantos JSON existem em /tmp/astra?", "*.json"),
        ("Quantos YAML existem em /tmp/astra?", "*.yaml"),
        ("Quantos Markdown existem em /tmp/astra?", "*.md"),
        ("Quantos arquivos de texto existem em /tmp/astra?", "*.txt"),
    ],
)
def test_mission_extension_count_matrix(goal, pattern):
    agent = object.__new__(MissionAgent)
    steps = agent._direct_file_steps(goal)
    assert steps
    assert steps[0]["action"] == "count_items"
    assert steps[0]["args"]["pattern"] == pattern


def test_json_payload_generated_by_mission_is_valid_matrix():
    goal = "Em /tmp/astra crie config.json que imprima ASTRA JSON OK."
    content = MissionAgent._code_content_for_file(goal, "config.json", "")
    assert json.loads(content) == {"message": "ASTRA JSON OK"}
