from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path

from astra_pc.paths import data_dir


DEFAULT_PIPER_VOICE = "pt_BR-faber-medium"


def voice_state_path() -> Path:
    return data_dir() / "voice.json"


def resolve_piper_model(explicit: str | Path | None = None) -> Path | None:
    if explicit:
        path = Path(explicit).expanduser()
        if path.exists():
            return path

    state = voice_state_path()
    if state.exists():
        try:
            payload = json.loads(state.read_text(encoding="utf-8"))
            path = Path(str(payload.get("model_path", ""))).expanduser()
            if path.exists():
                return path
        except Exception:
            pass

    candidate = data_dir() / "voices" / f"{DEFAULT_PIPER_VOICE}.onnx"
    return candidate if candidate.exists() else None


class PiperSpeaker:
    """Resident local neural TTS using Piper's Python streaming API.

    The model is loaded once and reused for every utterance. This avoids the
    robotic system speech fallback and avoids reloading Piper for every reply.
    """

    def __init__(
        self,
        model: str | Path,
        *,
        length_scale: float = 0.94,
        noise_scale: float = 0.62,
        noise_w_scale: float = 0.82,
        volume: float = 1.0,
    ):
        self.model = Path(model).expanduser()
        if not self.model.exists():
            raise FileNotFoundError(self.model)

        self.length_scale = max(0.6, min(1.5, float(length_scale)))
        self.noise_scale = max(0.0, min(2.0, float(noise_scale)))
        self.noise_w_scale = max(0.0, min(2.0, float(noise_w_scale)))
        self.volume = max(0.1, min(2.0, float(volume)))
        self._cancel = threading.Event()

        try:
            from piper import PiperVoice, SynthesisConfig
            import sounddevice as sd

            self.sd = sd
            self.SynthesisConfig = SynthesisConfig
            self.voice = PiperVoice.load(str(self.model))
            self._python_api = True
        except Exception:
            self.sd = None
            self.SynthesisConfig = None
            self.voice = None
            self._python_api = False
            if not shutil.which("piper"):
                raise RuntimeError(
                    "Piper TTS is not installed. Run: astra setup voice"
                )

    def cancel(self) -> None:
        self._cancel.set()

    def say(self, text: str) -> None:
        text = text.strip()
        if not text:
            return
        self._cancel.clear()
        if self._python_api:
            self._say_streaming(text)
        else:
            self._say_cli(text)

    def _say_streaming(self, text: str) -> None:
        syn = self.SynthesisConfig(
            volume=self.volume,
            length_scale=self.length_scale,
            noise_scale=self.noise_scale,
            noise_w_scale=self.noise_w_scale,
            normalize_audio=True,
        )
        stream = None
        try:
            for chunk in self.voice.synthesize(text, syn_config=syn):
                if self._cancel.is_set():
                    break
                if stream is None:
                    stream = self.sd.RawOutputStream(
                        samplerate=chunk.sample_rate,
                        channels=chunk.sample_channels,
                        dtype="int16",
                        blocksize=0,
                    )
                    stream.start()
                stream.write(chunk.audio_int16_bytes)
        finally:
            if stream is not None:
                try:
                    stream.stop()
                    stream.close()
                except Exception:
                    pass

    def _say_cli(self, text: str) -> None:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            wav = Path(tmp.name)
        try:
            p = subprocess.run(
                [
                    "piper",
                    "--model",
                    str(self.model),
                    "--output_file",
                    str(wav),
                ],
                input=text,
                text=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
            if p.returncode != 0 or self._cancel.is_set():
                return
            if shutil.which("pw-play"):
                subprocess.run(
                    ["pw-play", str(wav)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
            elif shutil.which("aplay"):
                subprocess.run(
                    ["aplay", "-q", str(wav)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
            elif os.name == "nt":
                safe = str(wav).replace("'", "''")
                subprocess.run(
                    [
                        "powershell",
                        "-NoProfile",
                        "-Command",
                        f"(New-Object Media.SoundPlayer '{safe}').PlaySync()",
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
        finally:
            wav.unlink(missing_ok=True)
