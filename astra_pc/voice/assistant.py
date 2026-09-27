from __future__ import annotations

import queue
import threading
from pathlib import Path

from astra_pc.ai.agent import AstraBrain
from astra_pc.screen.capture import capture_screen
from astra_pc.voice.commands import CommandRouter
from astra_pc.voice.vosk_engine import VoskVoiceEngine


class LocalSpeaker:
    def __init__(self):
        try:
            import pyttsx3
        except ImportError as exc:
            raise RuntimeError('Install voice support with: pip install -e ".[voice]"') from exc
        self.engine = pyttsx3.init()
        self._lock = threading.Lock()

    def say(self, text: str) -> None:
        with self._lock:
            self.engine.say(text)
            self.engine.runAndWait()


class AstraVoiceAssistant:
    def __init__(
        self,
        brain: AstraBrain,
        model_path: Path,
        *,
        wake_word: str = "astra",
        speak: bool = True,
    ):
        self.brain = brain
        self.model_path = model_path
        self.wake_word = wake_word.lower()
        self.router = CommandRouter()
        self.speaker = LocalSpeaker() if speak else None
        self._requests: queue.Queue[str] = queue.Queue(maxsize=4)
        self._stop = threading.Event()
        self._voice = VoskVoiceEngine(model_path, self._on_text)

    def run(self) -> None:
        print(f"Voice Astra online. Say '{self.wake_word}' followed by a request.")
        self._voice.start()
        try:
            while not self._stop.is_set():
                try:
                    request = self._requests.get(timeout=0.25)
                except queue.Empty:
                    continue
                self._answer(request)
        except KeyboardInterrupt:
            pass
        finally:
            self._voice.stop()

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
            self._requests.put_nowait(request)
        except queue.Full:
            pass

    def _answer(self, request: str) -> None:
        print("You>", request)

        quick = self.router.execute(request)
        if quick.handled and quick.message not in {"pause_gestures", "resume_gestures"}:
            answer = quick.message
        elif any(
            phrase in request.lower()
            for phrase in (
                "minha tela",
                "na tela",
                "tela agora",
                "o que estou vendo",
                "what is on my screen",
            )
        ):
            shot = capture_screen()
            try:
                answer = self.brain.see(shot, request)
            finally:
                shot.unlink(missing_ok=True)
        else:
            answer = self.brain.ask(request)

        print("Astra>", answer)
        self._speak(answer)

    def _speak(self, text: str) -> None:
        if self.speaker:
            self.speaker.say(text)
