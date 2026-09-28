from __future__ import annotations

from pathlib import Path

from .ollama_client import OllamaClient
from .router import ModelRouter


SYSTEM_PROMPT = """Você é Astra, uma assistente local para computador.
RESPONDA SEMPRE EM PORTUGUÊS DO BRASIL, exceto quando o usuário pedir explicitamente outro idioma.
Se o usuário falar português, nunca responda em inglês.
Responda de forma direta, curta, natural e útil. Prefira 1 a 3 frases em respostas de voz.
Você pode analisar telas, imagens e quadros de vídeo quando eles forem fornecidos.
Nunca diga que executou uma ação se nenhuma ferramenta realmente executou essa ação.
Não traduza nomes técnicos, comandos, caminhos ou código quando isso reduzir a precisão."""


class AstraBrain:
    def __init__(
        self,
        text_client: OllamaClient,
        vision_client: OllamaClient,
        strong_client: OllamaClient | None = None,
    ):
        self.text_client = text_client
        self.vision_client = vision_client
        self.strong_client = strong_client
        self.router = ModelRouter(text_client, vision_client, strong_client)

    def preload(self) -> None:
        self.text_client.preload()

    def preload_vision(self) -> None:
        self.vision_client.preload()

    def ask(self, text: str) -> str:
        client = self.router.choose(text)
        strong = self.strong_client is not None and client is self.strong_client
        return client.chat(
            text,
            system=SYSTEM_PROMPT,
            num_ctx=6144 if strong else 3072,
            num_predict=220 if strong else 96,
            temperature=0.15,
        )

    def see(self, image: str | Path, prompt: str) -> str:
        return self.vision_client.chat(
            prompt,
            images=[image],
            system=SYSTEM_PROMPT,
            num_ctx=6144,
            num_predict=128,
            temperature=0.15,
        )

    def inspect_frames(self, frames: list[Path], prompt: str) -> str:
        return self.vision_client.chat(
            prompt,
            images=frames,
            system=SYSTEM_PROMPT + "\nAs imagens anexadas são quadros de vídeo em ordem temporal.",
            num_ctx=8192,
            num_predict=160,
            temperature=0.15,
        )
