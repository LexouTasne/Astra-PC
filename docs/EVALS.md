# Astra Evals

O Astra separa testes rápidos de regressão dos testes que realmente chamam modelos locais.

## Suíte rápida

Comando: pytest -q

Não precisa carregar Qwen/Ollama. Cobre planner, permissões, comandos de voz, caminhos, arquivos,
código, matemática, horários, roteamento, gestos e outras regras determinísticas.

A matriz grande fica em tests/test_mass_daily_matrix.py e inclui todos os 1.440 minutos do dia,
frases de apps/mouse/teclado, operações matemáticas e geração/identificação de código em várias
linguagens.

## Qwen3 0.6B — planner rápido

Responsabilidade: classificação leve e escolha de ferramenta/ação.

Comando: ASTRA_RUN_MODEL_TESTS=1 pytest -q -s tests/test_model_integration.py::TestFastPlannerModel

A saída bruta do modelo passa pelo mesmo normalizador e guardrails usados pelo Astra real. Isso é
intencional: modelos pequenos podem errar detalhes de schema, mas o sistema não deve executar uma
ação errada por causa disso.

## Qwen3 1.7B — texto/programação

Responsabilidade: conversa principal, explicações e tarefas de programação.

Comando: ASTRA_RUN_MODEL_TESTS=1 pytest -q -s tests/test_model_integration.py::TestPrimaryTextModel

Os evals verificam Python, JavaScript, SQL, C++, Rust, Git, pytest e uma regra central do SOUL.md:
não alegar execução de ferramenta sem resultado confiável.

## Qwen3-VL 2B — visão

Responsabilidade: tela/imagem. É deliberadamente separado porque custa muito mais na RX 550.

Comando: ASTRA_RUN_MODEL_TESTS=1 ASTRA_RUN_VISION_TESTS=1 pytest -q -s tests/test_model_integration.py::TestVisionModel

## SOUL.md

SOUL.md é carregado pelo modelo de texto/visão. Voz e planners recebem uma versão compacta para
preservar latência. Um caminho alternativo pode ser usado com ASTRA_SOUL_PATH=/caminho/SOUL.md.

Mudanças no Soul entram no próximo processo do Astra, pois o conteúdo é cacheado em memória.
