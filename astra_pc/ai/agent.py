from __future__ import annotations

from pathlib import Path

from .ollama_client import OllamaClient
from .router import ModelRouter
from .soul import load_soul, voice_soul


VOICE_SYSTEM_PROMPT = """Você é Astra, uma assistente local. Responda em português do Brasil.
Seja curta e natural para voz. Não invente fatos do computador; use apenas contexto confiável fornecido.
Nunca diga que executou algo se nenhuma ferramenta executou."""

SYSTEM_PROMPT = """Você é Astra, uma assistente local para computador.
RESPONDA SEMPRE EM PORTUGUÊS DO BRASIL, exceto quando o usuário pedir explicitamente outro idioma.
Se o usuário falar português, nunca responda em inglês.
Seu nome é Astra. O projeto Astra-PC foi criado por Richard Mateus / Lex.
Astra é local-first e foi projetada para desktop e dispositivos pareados via Astra Mesh.

Você é uma assistente de desktop com ferramentas locais. Quando o daemon disponibilizar as skills,
você pode abrir e fechar aplicativos, consultar o sistema, listar/pesquisar/ler arquivos na home do
usuário, usar clipboard, Git e rotinas, analisar a tela/imagens/vídeo, trabalhar com voz, gestos e
Astra Mesh. Algumas ações destrutivas ou sensíveis exigem confirmação.

REGRA CRÍTICA: nunca invente conteúdo do computador. Se o usuário perguntar o que existe numa pasta,
o conteúdo de um arquivo, estado de aplicativo, sistema ou tela, use a ferramenta correspondente
quando ela estiver disponível. Se a ferramenta não forneceu os dados, diga que ainda não verificou.

CONTEXTO CONVERSACIONAL: trate resultados reais de ferramentas e a conversa recente como estado de
trabalho. Referências como "ele", "essa pasta", "o primeiro item", "lá dentro" e nomes abreviados
devem apontar para o objeto concreto já mostrado, sem pedir ao usuário para repetir o caminho.
Se houver conflito, prefira o resultado real mais recente da ferramenta.

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
        base = SYSTEM_PROMPT + "\n\nSOUL DO ASTRA:\n" + load_soul()
        if not extra_context:
            return base
        return (
            base
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
            num_predict=300 if strong else 220,
            temperature=0.15,
            think=False,
        )

    @staticmethod
    def _voice_system(extra_context: str | None = None) -> str:
        base = VOICE_SYSTEM_PROMPT + "\n" + voice_soul()
        if not extra_context:
            return base
        return (
            base
            + "\nContexto confiável:\n"
            + extra_context.strip()
        )

    def ask_voice(self, text: str, extra_context: str | None = None) -> str:
        """Primary 2B voice path with a compact speech-oriented prompt."""
        return self.text_client.chat(
            text,
            system=self._voice_system(extra_context),
            num_ctx=1536,
            num_predict=72,
            temperature=0.10,
            think=False,
        )

    def ask_voice_stream(self, text: str, extra_context: str | None = None):
        yield from self.text_client.chat_stream(
            text,
            system=self._voice_system(extra_context),
            num_ctx=1536,
            num_predict=72,
            temperature=0.10,
            think=False,
        )

    def ask_fast(self, text: str, extra_context: str | None = None) -> str:
        """0.6B path for lightweight spoken conversation."""
        return self.fast_client.chat(
            text,
            system=self._voice_system(extra_context),
            num_ctx=768,
            num_predict=56,
            temperature=0.10,
            think=False,
        )

    def ask_fast_stream(self, text: str, extra_context: str | None = None):
        yield from self.fast_client.chat_stream(
            text,
            system=self._voice_system(extra_context),
            num_ctx=768,
            num_predict=56,
            temperature=0.10,
            think=False,
        )

    def see(
        self,
        image: str | Path,
        prompt: str,
        extra_context: str | None = None,
    ) -> str:
        return self.vision_client.chat(
            prompt,
            images=[image],
            system=self._system(extra_context),
            num_ctx=8192,
            num_predict=320,
            temperature=0.12,
            think=False,
        )

    def inspect_frames(self, frames: list[Path], prompt: str) -> str:
        return self.vision_client.chat(
            prompt,
            images=frames,
            system=self._system() + "\nAs imagens anexadas são quadros de vídeo em ordem temporal.",
            num_ctx=8192,
            num_predict=220,
            temperature=0.15,
            think=False,
        )
