from __future__ import annotations

import queue
import shutil
import subprocess
import threading
import time
from pathlib import Path

from astra_pc.ai.agent import AstraBrain
from astra_pc.screen.capture import capture_screen
from astra_pc.voice.commands import CommandRouter
from astra_pc.voice.fast_whisper import FastWhisperVoiceEngine
from astra_pc.voice.vosk_engine import VoskVoiceEngine


class FastSpeaker:
    """Non-blocking TTS queue with fast system backends and pyttsx3 fallback."""

    def __init__(self):
        self._q: queue.Queue[str] = queue.Queue(maxsize=8)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="astra-tts", daemon=True)
        self._thread.start()

    def say(self, text: str) -> None:
        text = text.strip()
        if not text:
            return
        try:
            self._q.put_nowait(text)
        except queue.Full:
            pass

    def stop(self) -> None:
        self._stop.set()
        try:
            self._q.put_nowait("")
        except queue.Full:
            pass
        self._thread.join(timeout=1.0)

    def _run(self) -> None:
        engine = None
        while not self._stop.is_set():
            try:
                text = self._q.get(timeout=0.25)
            except queue.Empty:
                continue
            if not text:
                continue

            if shutil.which("spd-say"):
                subprocess.run(
                    ["spd-say", "-w", text],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
                continue

            if __import__("os").name == "nt":
                safe = text.replace("'", "''")
                ps = (
                    "Add-Type -AssemblyName System.Speech; "
                    "$s=New-Object System.Speech.Synthesis.SpeechSynthesizer; "
                    f"$s.Speak('{safe}')"
                )
                subprocess.run(
                    ["powershell", "-NoProfile", "-Command", ps],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
                continue

            if engine is None:
                try:
                    import pyttsx3
                    engine = pyttsx3.init()
                except Exception:
                    continue
            engine.say(text)
            engine.runAndWait()


class AstraVoiceAssistant:
    def __init__(
        self,
        brain: AstraBrain,
        model_path: Path | None = None,
        *,
        wake_word: str = "astra",
        speak: bool = True,
        engine: str = "fast",
        whisper_model: str = "base",
        language: str = "pt",
    ):
        self.brain = brain
        self.model_path = model_path
        self.wake_word = wake_word.lower()
        self.router = CommandRouter()
        self.speaker = FastSpeaker() if speak else None
        self._requests: queue.Queue[tuple[str, float]] = queue.Queue(maxsize=4)
        self._stop = threading.Event()

        if engine == "fast":
            self._voice = FastWhisperVoiceEngine(
                self._on_text,
                model_size=whisper_model,
                language=language,
                silence_ms=330,
                pre_roll_ms=240,
            )
        else:
            if model_path is None:
                raise RuntimeError("Vosk fallback requires --voice-model.")
            self._voice = VoskVoiceEngine(model_path, self._on_text)

    def run(self) -> None:
        print(f"Voice Astra online. Say '{self.wake_word}' followed by a request.")
        print("Fast path: VAD -> resident ASR -> 0.6B text model -> async TTS")
        self.brain.preload()
        threading.Thread(
            target=self._warm_vision,
            name="astra-vision-warmup",
            daemon=True,
        ).start()
        self._voice.start()
        try:
            while not self._stop.is_set():
                try:
                    request, heard_at = self._requests.get(timeout=0.20)
                except queue.Empty:
                    continue
                self._answer(request, heard_at)
        except KeyboardInterrupt:
            pass
        finally:
            self._voice.stop()
            if self.speaker:
                self.speaker.stop()

    def _warm_vision(self) -> None:
        try:
            self.brain.preload_vision()
            print("[warmup] vision model ready")
        except Exception as exc:
            print(f"[warmup] vision model skipped: {exc}")

    def _on_text(self, text: str) -> None:
        normalized = text.lower().strip()
        pos = normalized.find(self.wake_word)
        if pos < 0:
            return
        request = text[pos + len(self.wake_word):].strip(" ,:;-")
        if not request:
            self._speak("Sim?")
            return
        try:
            self._requests.put_nowait((request, time.perf_counter()))
        except queue.Full:
            pass

    def _answer(self, request: str, heard_at: float) -> None:
        started = time.perf_counter()
        print("You>", request)

        quick = self.router.execute(request)
        if quick.handled and quick.message not in {"pause_gestures", "resume_gestures"}:
            answer = quick.message
            path = "command"
        elif self._needs_screen(request):
            shot = capture_screen()
            try:
                answer = self.brain.see(shot, self._short_prompt(request))
            finally:
                shot.unlink(missing_ok=True)
            path = "vision"
        else:
            answer = self.brain.ask(self._short_prompt(request))
            path = "text"

        finished = time.perf_counter()
        model_ms = (finished - started) * 1000.0
        total_ms = (finished - heard_at) * 1000.0
        print(f"Astra> {answer}")
        print(f"[latency] path={path} model={model_ms:.0f}ms after_asr={total_ms:.0f}ms")
        self._speak(answer)

    @staticmethod
    def _needs_screen(request: str) -> bool:
        q = request.lower()
        return any(
            phrase in q
            for phrase in (
                "minha tela",
                "na tela",
                "tela agora",
                "o que estou vendo",
                "what is on my screen",
                "essa janela",
            )
        )

    @staticmethod
    def _short_prompt(request: str) -> str:
        return (
            "Responda em português de forma direta e curta, idealmente em até 3 frases. "
            + request
        )

    def _speak(self, text: str) -> None:
        if self.speaker:
            self.speaker.say(text)
