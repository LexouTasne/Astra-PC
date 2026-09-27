from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path


class PiperSpeaker:
    """Optional local neural TTS adapter for the Piper CLI."""

    def __init__(self, model: str | Path):
        self.model = Path(model).expanduser()
        if not shutil.which("piper"):
            raise RuntimeError("piper CLI is not installed.")
        if not self.model.exists():
            raise FileNotFoundError(self.model)

    def say(self, text: str) -> None:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            wav = Path(tmp.name)
        try:
            p = subprocess.run(
                ["piper", "--model", str(self.model), "--output_file", str(wav)],
                input=text,
                text=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
            if p.returncode != 0:
                return
            if shutil.which("pw-play"):
                subprocess.run(["pw-play", str(wav)], check=False)
            elif shutil.which("aplay"):
                subprocess.run(["aplay", "-q", str(wav)], check=False)
            elif os.name == "nt":
                subprocess.run(
                    ["powershell", "-NoProfile", "-Command",
                     f"(New-Object Media.SoundPlayer '{str(wav).replace(chr(39), chr(39)*2)}').PlaySync()"],
                    check=False,
                )
        finally:
            wav.unlink(missing_ok=True)
