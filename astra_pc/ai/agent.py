from __future__ import annotations

from pathlib import Path

from .ollama_client import OllamaClient
from .router import ModelRouter


SYSTEM_PROMPT = """Você é Astra, uma assistente local para computador.
RESPONDA SEMPRE EM PORTUGUÊS DO BRASIL, exceto quando o usuário pedir explicitamente outro idioma.
Se o usuário falar português, nunca responda em inglês.
Seu nome é Astra.

Você é uma assistente de desktop com ferramentas locais. Quando o daemon disponibilizar as skills,
você pode abrir e fechar aplicativos, consultar o sistema, listar/pesquisar/ler arquivos na home do
usuário, usar clipboard, Git e rotinas, analisar a tela/imagens/vídeo, trabalhar com voz, gestos e
Astra Mesh. Algumas ações destrutivas ou sensíveis exigem confirmação.

REGRA CRÍTICA: nunca invente conteúdo do computador. Se o usuário perguntar o que existe numa pasta,
o conteúdo de um arquivo, estado de aplicativo, sistema ou tela, use a ferramenta correspondente
quando ela estiver disponível. Se a ferramenta não forneceu os dados, diga que ainda não verificou.

Nunca diga que executou uma ação se nenhuma ferramenta realmente executou essa ação.
Não traduza nomes técnicos, comandos, caminhos ou código quando isso reduzir a precisão.
Seja natural, direta e útil. Em chat, pode explicar o necessário; em voz, prefira respostas curtas."""


class AstraBrain:
    def __init__(
        self,
        text_client: OllamaClient,
        vision_client: OllamaClient,
        strong_client: OllamaClient | None = None,
        fast_client: OllamaClient | None = None,
    ):
        self.text_client = text_client
        self.vision_client = vision_client
        self.strong_client = strong_client
        self.fast_client = fast_client or text_client
        self.router = ModelRouter(text_client, vision_client, strong_client)

    @staticmethod
    def _system(extra_context: str | None = None) -> str:
        if not extra_context:
            return SYSTEM_PROMPT
        return (
            SYSTEM_PROMPT
            + "\n\nCONTEXTO LOCAL CONFIÁVEL FORNECIDO PELO ASTRA:\n"
            + extra_context.strip()
            + "\nUse esse contexto somente quando for relevante ao pedido atual."
        )

    def preload(self) -> None:
        self.text_client.preload()

    def preload_fast(self) -> None:
        if self.fast_client is not self.text_client:
            self.fast_client.preload()

    def preload_vision(self) -> None:
        self.vision_client.preload()

    def ask(self, text: str, extra_context: str | None = None) -> str:
        client = self.router.choose(text)
        strong = self.strong_client is not None and client is self.strong_client
        return client.chat(
            text,
            system=self._system(extra_context),
            num_ctx=8192 if strong else 6144,
            num_predict=320 if strong else 220,
            temperature=0.15,
            think=False,
        )

    def ask_fast(self, text: str, extra_context: str | None = None) -> str:
        """Fast path reserved for voice/lightweight conversational replies."""
        return self.fast_client.chat(
            text,
            system=self._system(extra_context),
            num_ctx=2048,
            num_predict=80,
            temperature=0.10,
            think=False,
        )

    def ask_fast_stream(self, text: str, extra_context: str | None = None):
        yield from self.fast_client.chat_stream(
            text,
            system=self._system(extra_context),
            num_ctx=2048,
            num_predict=80,
            temperature=0.10,
            think=False,
        )

    def see(self, image: str | Path, prompt: str) -> str:
        return self.vision_client.chat(
            prompt,
            images=[image],
            system=SYSTEM_PROMPT,
            num_ctx=6144,
            num_predict=180,
            temperature=0.15,
            think=False,
        )

    def inspect_frames(self, frames: list[Path], prompt: str) -> str:
        return self.vision_client.chat(
            prompt,
            images=frames,
            system=SYSTEM_PROMPT + "\nAs imagens anexadas são quadros de vídeo em ordem temporal.",
            num_ctx=8192,
            num_predict=220,
            temperature=0.15,
            think=False,
        )
