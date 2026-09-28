from __future__ import annotations

import queue
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Callable

from astra_pc.ai.agent import AstraBrain
from astra_pc.screen.capture import capture_screen
from astra_pc.voice.commands import CommandRouter
from astra_pc.voice.fast_whisper import FastWhisperVoiceEngine
from astra_pc.voice.vosk_engine import VoskVoiceEngine


class FastSpeaker:
    """Non-blocking TTS queue with fast system backends and pyttsx3 fallback."""

    def __init__(self, piper_model: str | Path | None = None):
        self._q: queue.Queue[str] = queue.Queue(maxsize=8)
        self.piper_model = Path(piper_model).expanduser() if piper_model else None
        self._stop = threading.Event()
        self._speaking = threading.Event()
        self._last_finished = 0.0
        self._neural = None
        if self.piper_model and self.piper_model.exists():
            try:
                from astra_pc.voice.piper_tts import PiperSpeaker
                self._neural = PiperSpeaker(self.piper_model)
                print(f"[tts] Piper neural voice ready: {self.piper_model.name}")
            except Exception as exc:
                print(f"[tts] Piper unavailable, using system fallback: {exc}")
        self._thread = threading.Thread(target=self._run, name="astra-tts", daemon=True)
        self._thread.start()

    def is_busy(self, grace_ms: int = 300) -> bool:
        if self._speaking.is_set():
            return True
        return (time.monotonic() - self._last_finished) * 1000.0 < grace_ms

    def say(self, text: str) -> None:
        text = text.strip()
        if not text:
            return
        try:
            self._q.put_nowait(text)
        except queue.Full:
            pass

    def cancel(self) -> None:
        while True:
            try:
                self._q.get_nowait()
            except queue.Empty:
                break
        if self._neural is not None:
            try:
                self._neural.cancel()
            except Exception:
                pass
        if shutil.which("spd-say"):
            subprocess.run(
                ["spd-say", "-C"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )

    def stop(self) -> None:
        self.cancel()
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

            self._speaking.set()
            try:
                if self._neural is not None:
                    try:
                        self._neural.say(text)
                        continue
                    except Exception as exc:
                        print(f"[tts] neural synthesis failed: {exc}")

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
            finally:
                self._speaking.clear()
                self._last_finished = time.monotonic()


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
        request_handler: Callable[[str], str] | None = None,
        conversation_window: float = 9.0,
        wakeword_model: str | Path | None = None,
        wakeword_threshold: float = 0.55,
        piper_model: str | Path | None = None,
        input_device: int | str | None = None,
        silence_ms: int = 260,
        pre_roll_ms: int = 200,
        adaptive_retry: bool = True,
    ):
        self.brain = brain
        self.model_path = model_path
        self.wake_word = wake_word.lower()
        self.router = CommandRouter()
        self.request_handler = request_handler
        self.conversation_window = max(0.0, float(conversation_window))
        self._conversation_until = 0.0
        self.speaker = FastSpeaker(piper_model=piper_model) if speak else None
        self._requests: queue.Queue[tuple[str, float]] = queue.Queue(maxsize=4)
        self._stop = threading.Event()
        self._dedicated_wake_until = 0.0
        self._wake_detector = None
        if wakeword_model:
            try:
                from astra_pc.voice.wakeword import OpenWakeWordDetector
                self._wake_detector = OpenWakeWordDetector(
                    wakeword_model,
                    self._on_dedicated_wake,
                    threshold=wakeword_threshold,
                )
            except Exception as exc:
                print(f"[wakeword] dedicated detector unavailable: {exc}")

        if engine == "fast":
            self._voice = FastWhisperVoiceEngine(
                self._on_text,
                model_size=whisper_model,
                language=language,
                silence_ms=silence_ms,
                pre_roll_ms=pre_roll_ms,
                raw_frame_callback=(
                    self._wake_detector.process_pcm if self._wake_detector else None
                ),
                input_device=input_device,
                adaptive_retry=adaptive_retry,
            )
        else:
            if model_path is None:
                raise RuntimeError("Vosk fallback requires --voice-model.")
            self._voice = VoskVoiceEngine(model_path, self._on_text)

    def stop(self) -> None:
        self._stop.set()
        try:
            self._voice.stop()
        except Exception:
            pass
        if self.speaker:
            self.speaker.stop()

    def run(self) -> None:
        print(f"Voice Astra online. Say '{self.wake_word}' followed by a request.")
        print("Fast path: VAD -> resident ASR -> 0.6B text model -> async TTS")
        if self.request_handler is None:
            try:
                self.brain.preload()
                print("[warmup] text model ready")
            except Exception as exc:
                # Voice capture should remain usable even if model warmup fails.
                # The request path can retry once Ollama is ready.
                print(f"[warmup] text model skipped: {exc}")
        else:
            print("[warmup] resident text model already managed by daemon")
        # Do not preload the vision model in voice-only mode. It can contend
        # with the fast text model and is loaded lazily if a screen request occurs.
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

    def _on_dedicated_wake(self) -> None:
        self._dedicated_wake_until = time.monotonic() + 3.0
        self._conversation_until = time.monotonic() + self.conversation_window
        if self.speaker:
            self.speaker.cancel()
        print("[wakeword] Astra detected")

    def _on_text(self, text: str) -> None:
        normalized = text.lower().strip()
        pos = normalized.find(self.wake_word)
        now = time.monotonic()

        # Without hardware AEC, desktop speakers can be re-captured by the mic.
        # Ignore ASR while Astra is speaking (plus a tiny tail) unless the user
        # explicitly addresses Astra with a stop/cancel phrase.
        if self.speaker and self.speaker.is_busy():
            stop_words = ("para", "pare", "cala", "cancelar", "stop", "silêncio", "silencio")
            if pos >= 0 and any(word in normalized for word in stop_words):
                self.speaker.cancel()
                self._conversation_until = 0.0
                print("[barge-in] speech cancelled")
            return

        if pos >= 0:
            request = text[pos + len(self.wake_word):].strip(" ,:;-")
            self._conversation_until = now + self.conversation_window
            if self.speaker:
                self.speaker.cancel()
        elif now <= self._dedicated_wake_until:
            request = text.strip(" ,:;-")
            self._dedicated_wake_until = 0.0
            self._conversation_until = now + self.conversation_window
        elif now <= self._conversation_until:
            request = text.strip(" ,:;-")
        else:
            return

        if not request:
            self._speak("Sim?")
            return

        if request.lower() in {"para", "pare", "cala", "cancelar", "stop", "silencio", "silêncio"}:
            if self.speaker:
                self.speaker.cancel()
            self._conversation_until = 0.0
            print("[barge-in] speech cancelled")
            return

        try:
            self._requests.put_nowait((request, time.perf_counter()))
        except queue.Full:
            pass

    def _answer(self, request: str, heard_at: float) -> None:
        started = time.perf_counter()
        print("You>", request)
        already_spoken = False

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
            # PC actions go through the daemon/tools. Ordinary conversation stays
            # local and streams immediately from the hot 0.6B text model.
            from astra_pc.core.planner import AstraPlanner

            if self.request_handler is not None and AstraPlanner.needs_planning(request):
                try:
                    answer = self.request_handler(request)
                    path = "daemon-action"
                except Exception as exc:
                    print(f"[voice] daemon action failed, local fallback: {exc}")
                    answer = self.brain.ask_fast(self._short_prompt(request))
                    path = "text-fallback"
            else:
                answer, already_spoken = self._stream_conversation(request)
                path = "text-stream"

        answer = (answer or "").strip()
        if not answer:
            answer = "Não consegui gerar a resposta. Tenta de novo."
            path += "-empty"

        finished = time.perf_counter()
        model_ms = (finished - started) * 1000.0
        total_ms = (finished - heard_at) * 1000.0
        print(f"Astra> {answer}")
        print(f"[latency] path={path} model={model_ms:.0f}ms after_asr={total_ms:.0f}ms")
        self._conversation_until = time.monotonic() + self.conversation_window
        if not already_spoken:
            self._speak(answer)

    def _stream_conversation(self, request: str) -> tuple[str, bool]:
        full = ""
        speech_buffer = ""
        spoke = False
        prompt = self._short_prompt(request)

        try:
            for piece in self.brain.ask_fast_stream(prompt):
                full += piece
                speech_buffer += piece

                # Start TTS as soon as one natural phrase is complete rather than
                # waiting for the full model answer.
                if self.speaker and self._speech_chunk_ready(speech_buffer):
                    chunk = speech_buffer.strip()
                    if chunk:
                        self.speaker.say(chunk)
                        spoke = True
                    speech_buffer = ""

            if self.speaker and speech_buffer.strip():
                self.speaker.say(speech_buffer.strip())
                spoke = True
        except Exception as exc:
            print(f"[voice] streaming model fallback: {exc}")
            full = self.brain.ask_fast(prompt)
            spoke = False

        return full.strip(), spoke

    @staticmethod
    def _speech_chunk_ready(text: str) -> bool:
        stripped = text.strip()
        if len(stripped) < 24:
            return False
        if stripped[-1:] in ".!?;:":
            return True
        # Prevent a very long first sentence from delaying speech too much.
        return len(stripped) >= 110 and stripped.endswith((" ", ","))


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
            "Responda SOMENTE em português do Brasil, de forma natural, direta e curta. "
            "Para voz, use no máximo 3 frases e não explique seu raciocínio. Pedido: "
            + request
        )

    def _speak(self, text: str) -> None:
        if self.speaker:
            self.speaker.say(text)
