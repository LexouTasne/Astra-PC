from __future__ import annotations

from pathlib import Path

from .ollama_client import OllamaClient


SYSTEM_PROMPT = """You are Astra, a local desktop assistant.
Answer directly, briefly and usefully. Prefer 1-4 short sentences unless the user asks for detail.
You can reason about screenshots, images and sampled video frames. Never claim an action was
executed unless the caller actually provided a tool that executed it. Answer in the user's language."""


class AstraBrain:
    def __init__(self, text_client: OllamaClient, vision_client: OllamaClient):
        self.text_client = text_client
        self.vision_client = vision_client

    def preload(self) -> None:
        self.text_client.preload()

    def preload_vision(self) -> None:
        self.vision_client.preload()

    def ask(self, text: str) -> str:
        return self.text_client.chat(
            text,
            system=SYSTEM_PROMPT,
            num_ctx=3072,
            num_predict=96,
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
            system=SYSTEM_PROMPT + "\nThe attached images are ordered sampled video frames.",
            num_ctx=8192,
            num_predict=160,
            temperature=0.15,
        )
