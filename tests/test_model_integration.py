from __future__ import annotations

import json
import os
import urllib.request
import pytest
from PIL import Image, ImageDraw

from astra_pc.ai.agent import AstraBrain
from astra_pc.ai.mission import MISSION_SYSTEM, MissionAgent
from astra_pc.ai.ollama_client import OllamaClient
from astra_pc.ai.soul import planner_soul


pytestmark = pytest.mark.model_integration

if os.getenv("ASTRA_RUN_MODEL_TESTS") != "1":
    pytest.skip("set ASTRA_RUN_MODEL_TESTS=1 to run local Ollama model evals", allow_module_level=True)


HOST = "http://127.0.0.1:11434"


def _unload(model: str) -> None:
    body = json.dumps({
        "model": model,
        "prompt": "",
        "stream": False,
        "keep_alive": 0,
    }).encode()
    req = urllib.request.Request(
        HOST + "/api/generate",
        data=body,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            response.read()
    except Exception:
        pass


def _installed(model: str) -> bool:
    return any(name.split(":")[0] == model.split(":")[0] for name in OllamaClient("qwen3:0.6b", HOST, 20, 0).models())


@pytest.fixture(scope="class")
def fast_model():
    model = "qwen3:0.6b"
    if not _installed(model):
        pytest.skip(f"{model} not installed")
    client = OllamaClient(model, HOST, 60, "45s")
    client.preload()
    yield client
    _unload(model)


@pytest.fixture(scope="class")
def text_model():
    model = "qwen3:1.7b"
    if not _installed(model):
        pytest.skip(f"{model} not installed")
    client = OllamaClient(model, HOST, 90, "45s")
    client.preload()
    yield client
    _unload(model)


@pytest.fixture(scope="class")
def vision_model():
    model = "qwen3-vl:2b-instruct"
    if not _installed(model):
        pytest.skip(f"{model} not installed")
    client = OllamaClient(model, HOST, 120, "30s")
    client.preload()
    yield client
    _unload(model)


PLANNER_CASES = [
    ("Liste o diretório /home/lex/Downloads.", "list_dir"),
    ("Leia o arquivo /home/lex/notes.txt.", "read_file"),
    ("Conte os itens em /home/lex/Downloads.", "count_items"),
    ("Crie a pasta /home/lex/Teste-Astra.", "create_dir"),
    ("Procure config.json dentro de /home/lex/Astra-PC.", "search_files"),
    ("Crie /home/lex/demo.py com conteúdo print('ok').", "create_text_file"),
    ("Apague /home/lex/tmp.txt.", "delete_file"),
    ("Liste /home/lex/Documents.", "list_dir"),
    ("Leia /home/lex/Astra-PC/README.md.", "read_file"),
    ("Conte arquivos em /home/lex/Astra-PC/tests.", "count_items"),
    ("Quantos arquivos Python existem em /home/lex/Astra-PC?", "count_items"),
    ("Encontre README.md dentro de /home/lex/Astra-PC.", "search_files"),
    ("Localize pyproject.toml dentro de /home/lex/Astra-PC.", "search_files"),
    ("Crie a pasta /tmp/astra-cache.", "create_dir"),
    ("Liste /tmp.", "list_dir"),
    ("Leia /home/lex/Astra-PC/pyproject.toml.", "read_file"),
    ("Conte os itens em /tmp.", "count_items"),
    ("Procure test_mission.py dentro de /home/lex/Astra-PC/tests.", "search_files"),
    ("Crie /tmp/hello.js com conteúdo console.log('ok').", "create_text_file"),
    ("Apague /tmp/astra-old.tmp.", "delete_file"),
    ("Liste o diretório /home/lex/Astra-PC/tests.", "list_dir"),
    ("Leia o arquivo /home/lex/Astra-PC/SOUL.md.", "read_file"),
    ("Quantos JSON existem em /home/lex/Astra-PC?", "count_items"),
    ("Encontre astra.json dentro de /home/lex/Astra-PC.", "search_files"),
    ("Crie a pasta /tmp/astra-model-eval.", "create_dir"),
    ("Crie /tmp/astra-model-eval.txt com conteúdo OK.", "create_text_file"),
    ("Apague /tmp/astra-model-eval.txt.", "delete_file"),
    ("Conte arquivos em /home/lex/Astra-PC/astra_pc.", "count_items"),
    ("Procure mission.py dentro de /home/lex/Astra-PC/astra_pc.", "search_files"),
    ("Liste /home/lex/Astra-PC/docs.", "list_dir"),
]


@pytest.mark.usefixtures("fast_model")
class TestFastPlannerModel:
    @pytest.mark.parametrize("goal,expected_action", PLANNER_CASES)
    def test_06b_selects_correct_file_tool(self, fast_model, goal, expected_action):
        prompt = {
            "goal": goal,
            "step": 1,
            "skills": [{
                "name": "files",
                "safe": ["list_dir", "search_files", "read_file", "count_items", "create_dir", "create_text_file"],
                "confirm": ["write_file", "delete_file"],
            }],
        }
        raw = fast_model.chat(
            "State:" + json.dumps(prompt, ensure_ascii=False, separators=(",", ":")),
            system=MISSION_SYSTEM + "\n" + planner_soul(),
            temperature=0.0,
            num_ctx=1024,
            num_predict=96,
            think=False,
            format="json",
        )
        step = MissionAgent._normalize_step(json.loads(raw))
        repairer = object.__new__(MissionAgent)
        step = repairer._repair_file_step_from_goal(goal, step, [])
        assert step.get("type") == "skill"
        assert str(step.get("skill", "")).lower() == "files"
        assert str(step.get("action", "")).lower() == expected_action


TEXT_CASES = [
    ("Em Python, qual tipo evita valores duplicados? Responda em uma frase.", ("set", "conjunto")),
    ("Qual função converte uma string JSON em objeto no JavaScript?", ("json.parse",)),
    ("Qual cláusula SQL filtra linhas?", ("where",)),
    ("Qual header C++ é usado para std::cout?", ("iostream",)),
    ("Qual macro Rust normalmente imprime uma linha no terminal?", ("println!", "println")),
    ("Qual comando Git mostra o status do repositório?", ("git status",)),
    ("Qual comando pytest executa testes silenciosamente?", ("pytest -q", "pytest")),
    ("Qual extensão é comum para arquivo TypeScript?", (".ts", "ts")),
    ("Em Python, qual palavra inicia uma função?", ("def",)),
    ("Você executou alguma ferramenta nesta pergunta? Responda apenas sim ou não.", ("não", "nao")),
    ("Em Python, qual operador testa se uma chave existe em um dicionário?", ("in",)),
    ("No JavaScript, qual palavra espera uma Promise dentro de uma função async?", ("await",)),
    ("Qual comando Git remove um arquivo da área de stage sem apagar o arquivo?", ("restore --staged", "reset")),
    ("Qual cláusula SQL ordena o resultado?", ("order by",)),
    ("Qual header C++ contém std::vector?", ("vector",)),
    ("Como se chama o conceito central de posse de valores em Rust?", ("ownership", "propriedade")),
    ("O que normalmente significa HTTP 404?", ("não encontrado", "nao encontrado", "não foi encontrada", "não pode encontrar", "not found")),
    ("Qual decorator do pytest declara uma fixture?", ("pytest.fixture", "fixture")),
    ("Qual módulo da biblioteca padrão Python trabalha com JSON?", ("json",)),
    ("Qual comando shell mostra o diretório atual?", ("pwd",)),
    ("Qual palavra-chave TypeScript declara uma interface?", ("interface",)),
    ("Em Go, qual função é o ponto de entrada normal de um executável?", ("main",)),
    ("Qual é a assinatura padrão do método main que inicia um programa Java? Responda com a assinatura.", ("static void main", "public static void main")),
    ("Qual header C fornece printf?", ("stdio.h", "stdio")),
    ("Qual módulo Python fornece expressões regulares?", ("re",)),
    ("Qual método de lista Python adiciona um item no final?", ("append",)),
    ("Qual método JavaScript adiciona um item no final de um array?", ("push",)),
    ("Qual comando Git mostra diferenças não commitadas?", ("git diff",)),
    ("Qual comando Python cria um ambiente virtual usando o módulo padrão?", ("venv", "python -m venv")),
    ("Se nenhuma ferramenta foi chamada, você deve afirmar que executou algo no PC? Responda sim ou não.", ("não", "nao")),
]


@pytest.mark.usefixtures("text_model")
class TestPrimaryTextModel:
    @pytest.mark.parametrize("prompt,needles", TEXT_CASES)
    def test_17b_programming_and_soul_answers(self, text_model, prompt, needles):
        answer = text_model.chat(
            prompt,
            system=AstraBrain._system(),
            temperature=0.0,
            num_ctx=2048,
            num_predict=80,
            think=False,
        ).lower()
        assert any(needle in answer for needle in needles)


@pytest.mark.vision_integration
@pytest.mark.skipif(
    os.getenv("ASTRA_RUN_VISION_TESTS") != "1",
    reason="set ASTRA_RUN_VISION_TESTS=1 for heavy Qwen-VL smoke tests",
)
@pytest.mark.usefixtures("vision_model")
class TestVisionModel:
    def test_vl_reads_large_desktop_label(self, vision_model, tmp_path):
        image = Image.new("RGB", (800, 450), "white")
        draw = ImageDraw.Draw(image)
        draw.rectangle((80, 120, 720, 330), outline="black", width=6)
        draw.text((210, 185), "ASTRA 42", fill="black")
        path = tmp_path / "screen.png"
        image.save(path)

        answer = vision_model.chat(
            "Observe a imagem. Responda somente com o número grande visível.",
            images=[path],
            system="Você analisa telas. Não invente. Responda apenas o que estiver visível.",
            temperature=0.0,
            num_ctx=2048,
            num_predict=24,
            think=False,
        )
        assert "42" in answer

    def test_vl_detects_simple_button_text(self, vision_model, tmp_path):
        image = Image.new("RGB", (800, 450), "white")
        draw = ImageDraw.Draw(image)
        draw.rectangle((230, 160, 570, 290), fill="gray", outline="black", width=5)
        draw.text((325, 210), "SALVAR", fill="black")
        path = tmp_path / "button.png"
        image.save(path)

        answer = vision_model.chat(
            "Qual palavra está escrita no botão central? Responda somente a palavra.",
            images=[path],
            system="Você analisa interfaces. Não invente elementos.",
            temperature=0.0,
            num_ctx=2048,
            num_predict=24,
            think=False,
        ).upper()
        assert "SALVAR" in answer
