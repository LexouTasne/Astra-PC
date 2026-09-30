from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path


_FALLBACK = """Astra é local-first. Fale em português do Brasil por padrão.
Nunca invente o estado do computador nem diga que executou algo sem confirmação da ferramenta. Se não houver resultado de ferramenta no contexto, não alegue execução.
Use o ciclo entender -> executar -> verificar -> corrigir. Preserve mudanças existentes em projetos.
Em programação, inspecione antes de editar e teste antes de declarar sucesso.
Prefira rotas determinísticas e modelos leves quando forem suficientes; use visão só para conteúdo visual.
Ações destrutivas ou sensíveis devem respeitar a camada de permissões e confirmação.
Em voz, seja curta, calma e natural."""


def soul_path() -> Path | None:
    explicit = os.getenv("ASTRA_SOUL_PATH", "").strip()
    candidates = []
    if explicit:
        candidates.append(Path(explicit).expanduser())
    candidates.extend(
        [
            Path(__file__).resolve().parents[2] / "SOUL.md",
            Path.cwd() / "SOUL.md",
        ]
    )
    for path in candidates:
        try:
            if path.is_file():
                return path.resolve()
        except OSError:
            continue
    return None


@lru_cache(maxsize=4)
def load_soul(max_chars: int = 4800) -> str:
    path = soul_path()
    if path is None:
        return _FALLBACK[:max_chars].strip()
    try:
        text = path.read_text(encoding="utf-8").strip()
    except OSError:
        text = _FALLBACK
    return (text or _FALLBACK)[:max_chars].strip()


def voice_soul() -> str:
    return (
        "Seja curta, calma e natural. Nunca invente estado do PC nem ação executada. "
        "Use contexto confirmado. Ferramentas fazem ações; só confirme depois do resultado. "
        "Prefira resposta rápida para conversa simples e precisão quando houver risco."
    )


def planner_soul() -> str:
    return (
        "Planeje uma ação mínima por vez. Ferramentas executam; o modelo não deve fingir execução. "
        "Use resultados reais para decidir o próximo passo. Prefira rotas determinísticas quando "
        "o pedido estiver claro. Não repita ação bem-sucedida. Preserve dados e respeite confirmação."
    )
