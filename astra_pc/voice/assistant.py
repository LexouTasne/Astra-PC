from __future__ import annotations

import queue
import re
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
        self._q: queue.Queue[str] = queue.Queue(maxsize=16)
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

    @staticmethod
    def _clean_for_speech(text: str) -> str:
        value = str(text or "").strip()
        if not value:
            return ""
        # Do not make Piper literally read Markdown syntax, huge code blocks or URLs.
        value = re.sub(r"```[\s\S]*?```", " trecho de código ", value)
        value = re.sub(r"`([^\n`]+)`", r"\1", value)
        value = re.sub(r"https?://\S+", " link ", value)
        value = re.sub(r"(?m)^\s*[-*+]\s+", "", value)
        value = re.sub(r"[*_#>~]", "", value)
        value = re.sub(r"\s+", " ", value).strip()
        return value

    def say(self, text: str) -> None:
        text = self._clean_for_speech(text)
        if not text:
            return
        try:
            self._q.put_nowait(text)
        except queue.Full:
            # Voice should prefer the newest answer over stale queued speech.
            try:
                self._q.get_nowait()
                self._q.put_nowait(text)
            except (queue.Empty, queue.Full):
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

    def dictate_once(self, timeout: float = 15.0) -> str:
        target: queue.Queue[str] = queue.Queue(maxsize=1)
        with self._dictation_lock:
            if self._dictation_target is not None:
                raise RuntimeError("dictation already active")
            self._dictation_target = target
        if self.speaker:
            self.speaker.cancel()
        try:
            return target.get(timeout=max(1.0, float(timeout)))
        except queue.Empty as exc:
            raise TimeoutError("Não ouvi uma frase completa.") from exc
        finally:
            with self._dictation_lock:
                if self._dictation_target is target:
                    self._dictation_target = None

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
        preview_handler: Callable[[str], None] | None = None,
        cancel_handler: Callable[[], None] | None = None,
        conversation_window: float = 9.0,
        partial_interval_ms: int = 850,
        wakeword_model: str | Path | None = None,
        wakeword_threshold: float = 0.55,
        piper_model: str | Path | None = None,
        input_device: int | str | None = None,
        silence_ms: int = 340,
        pre_roll_ms: int = 240,
        start_speech_ms: int = 45,
        min_utterance_ms: int = 150,
        max_utterance_s: float = 18.0,
        vad_mode: int = 2,
        adaptive_retry: bool = True,
    ):
        self.brain = brain
        self.model_path = model_path
        self.wake_word = wake_word.lower()
        self.router = CommandRouter()
        self.request_handler = request_handler
        self.preview_handler = preview_handler
        self.cancel_handler = cancel_handler
        self.conversation_window = max(0.0, float(conversation_window))
        self.partial_interval_ms = max(400, int(partial_interval_ms))
        self._conversation_until = 0.0
        self.speaker = FastSpeaker(piper_model=piper_model) if speak else None
        self._requests: queue.Queue[tuple[str, float]] = queue.Queue(maxsize=4)
        self._previews: queue.Queue[str] = queue.Queue(maxsize=1)
        self._last_preview = ""
        self._preview_thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._dedicated_wake_until = 0.0
        self._dictation_lock = threading.Lock()
        self._dictation_target: queue.Queue[str] | None = None
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
                on_partial=self._on_partial,
                partial_interval_ms=self.partial_interval_ms,
                model_size=whisper_model,
                language=language,
                silence_ms=silence_ms,
                pre_roll_ms=pre_roll_ms,
                start_speech_ms=start_speech_ms,
                min_utterance_ms=min_utterance_ms,
                max_utterance_s=max_utterance_s,
                vad_mode=vad_mode,
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
        print("Audio path: continuous VAD capture -> parallel Whisper -> async Piper TTS")
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
        if self.preview_handler is not None:
            self._preview_thread = threading.Thread(
                target=self._preview_loop,
                name="astra-voice-preview",
                daemon=True,
            )
            self._preview_thread.start()
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
            if self._preview_thread:
                self._preview_thread.join(timeout=0.8)
            if self.speaker:
                self.speaker.stop()

    def _preview_loop(self) -> None:
        while not self._stop.is_set():
            try:
                text = self._previews.get(timeout=0.15)
            except queue.Empty:
                continue
            if not text or self.preview_handler is None:
                continue
            try:
                self.preview_handler(text)
            except Exception as exc:
                print(f"[voice:preview] ignored error: {exc}")

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

    def _wake_match(self, text: str):
        aliases = [re.escape(self.wake_word)]
        # Whisper sometimes drops the /r/ in "Astra" on noisy Brazilian mics.
        if self.wake_word == "astra":
            aliases.append("asta")
        return re.search(r"\b(?:" + "|".join(aliases) + r")\b", text, re.I)

    def _on_partial(self, text: str) -> None:
        if self.preview_handler is None:
            return
        with self._dictation_lock:
            if self._dictation_target is not None:
                return

        normalized = str(text).strip()
        if not normalized:
            return

        wake = self._wake_match(normalized)
        now = time.monotonic()
        if wake is not None:
            request = normalized[wake.end():].strip(" ,:;-")
        elif now <= self._dedicated_wake_until or now <= self._conversation_until:
            request = normalized.strip(" ,:;-")
        else:
            return

        if len(request) < 3 or request == self._last_preview:
            return
        self._last_preview = request
        try:
            self._previews.put_nowait(request)
        except queue.Full:
            try:
                self._previews.get_nowait()
                self._previews.put_nowait(request)
            except (queue.Empty, queue.Full):
                pass

    def _on_text(self, text: str) -> None:
        self._last_preview = ""
        with self._dictation_lock:
            target = self._dictation_target
            if target is not None:
                self._dictation_target = None
                try:
                    target.put_nowait(text.strip())
                except queue.Full:
                    pass
                return

        normalized = text.lower().strip()
        wake = self._wake_match(text)
        now = time.monotonic()

        # Without hardware AEC, desktop speakers can be re-captured by the mic.
        # Ignore ASR while Astra is speaking (plus a tiny tail) unless the user
        # explicitly addresses Astra with a stop/cancel phrase.
        if self.speaker and self.speaker.is_busy():
            stop_words = ("para", "pare", "cala", "cancelar", "stop", "silêncio", "silencio")
            if wake is not None and any(word in normalized for word in stop_words):
                self.speaker.cancel()
                if self.cancel_handler is not None:
                    self.cancel_handler()
                self._conversation_until = 0.0
                print("[barge-in] speech and active work cancelled")
            return

        if wake is not None:
            request = text[wake.end():].strip(" ,:;-")
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
            if self.cancel_handler is not None:
                self.cancel_handler()
            self._conversation_until = 0.0
            print("[barge-in] speech and active work cancelled")
            return

        try:
            self._requests.put_nowait((request, time.perf_counter()))
        except queue.Full:
            pass

    def _answer(self, request: str, heard_at: float) -> None:
        started = time.perf_counter()
        print("You>", request)
        already_spoken = False

        if self.request_handler is not None:
            # Resident voice sends every useful turn through the daemon so even
            # instant answers participate in the same shared conversation state.
            try:
                answer = self.request_handler(request)
                path = "daemon-context"
            except Exception as exc:
                print(f"[voice] daemon context failed, local fallback: {exc}")
                answer = self.brain.ask_voice(self._short_prompt(request))
                path = "text-fallback-2b"
        else:
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
                answer, already_spoken = self._stream_conversation(request)
                path = "text-stream-2b"

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
        first_chunk_checked = False
        prompt = self._short_prompt(request)

        try:
            for piece in self.brain.ask_voice_stream(prompt):
                full += piece
                speech_buffer += piece

                if self.speaker and self._speech_chunk_ready(speech_buffer):
                    chunk = speech_buffer.strip()
                    if chunk:
                        if not first_chunk_checked:
                            first_chunk_checked = True
                            if self._looks_english(chunk):
                                raise RuntimeError("model escaped to English")
                        self.speaker.say(chunk)
                        spoke = True
                    speech_buffer = ""

            if self._looks_english(full):
                raise RuntimeError("model answered in English")

            if self.speaker and speech_buffer.strip():
                self.speaker.say(speech_buffer.strip())
                spoke = True
        except Exception as exc:
            if spoke:
                # Do not duplicate already-spoken Portuguese on a late transport
                # error. Keep what we already have.
                print(f"[voice] stream ended after speech began: {exc}")
                return full.strip(), True
            print(f"[voice] streaming model fallback: {exc}")
            repair = (
                "Responda obrigatoriamente em português do Brasil. "
                "Não use inglês. Responda curto e natural. Pedido original: "
                + request
            )
            full = self.brain.ask_voice(repair)
            spoke = False

        return full.strip(), spoke

    @staticmethod
    def _looks_english(text: str) -> bool:
        words = {
            w.strip(".,!?;:'\"()[]{}").lower()
            for w in text.split()
            if w.strip()
        }
        english = {
            "the", "and", "i'm", "here", "assist", "you", "your", "can",
            "please", "what", "is", "are", "how", "would", "like", "help",
        }
        portuguese = {
            "o", "a", "e", "é", "em", "que", "para", "você", "voce",
            "como", "com", "uma", "um", "não", "nao", "posso", "sim",
        }
        return len(words & english) >= 2 and len(words & portuguese) == 0


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
