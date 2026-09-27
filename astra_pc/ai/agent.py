from __future__ import annotations

from pathlib import Path

from .ollama_client import OllamaClient


SYSTEM_PROMPT = """You are Astra, a local desktop assistant.
Be concise, practical and safe. You can reason about screenshots, images and sampled
video frames. Never claim an action was executed unless the caller actually provided
a tool that executed it. When analyzing GUI screenshots, describe concrete visible
elements and useful next actions. Answer in the user's language when possible."""


class AstraBrain:
    def __init__(self, client: OllamaClient):
        self.client = client

    def ask(self, text: str) -> str:
        return self.client.chat(text, system=SYSTEM_PROMPT)

    def see(self, image: str | Path, prompt: str) -> str:
        return self.client.chat(
            prompt,
            images=[image],
            system=SYSTEM_PROMPT,
            num_ctx=12288,
        )

    def inspect_frames(self, frames: list[Path], prompt: str) -> str:
        return self.client.chat(
            prompt,
            images=frames,
            system=SYSTEM_PROMPT
            + "\nThe attached images are ordered frames sampled from one video.",
            num_ctx=16384,
        )
