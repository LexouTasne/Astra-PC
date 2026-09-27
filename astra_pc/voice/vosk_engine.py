from __future__ import annotations

import json
import queue
import threading
from pathlib import Path
from typing import Callable


class VoskVoiceEngine:
    """Optional offline microphone worker. Heavy imports happen only when enabled."""

    def __init__(self, model_path: Path, on_text: Callable[[str], None]):
        try:
            import sounddevice as sd
            from vosk import KaldiRecognizer, Model
        except ImportError as exc:
            raise RuntimeError('Install voice support with: pip install -e ".[voice]"') from exc

        self._sd = sd
        self._Model = Model
        self._Recognizer = KaldiRecognizer
        self.model_path = model_path
        self.on_text = on_text
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="astra-voice", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1.0)

    def _run(self) -> None:
        audio_q: queue.Queue[bytes] = queue.Queue(maxsize=8)
        model = self._Model(str(self.model_path))
        rec = self._Recognizer(model, 16000)

        def callback(indata, frames, time_info, status):
            if status:
                return
            try:
                audio_q.put_nowait(bytes(indata))
            except queue.Full:
                pass

        with self._sd.RawInputStream(
            samplerate=16000,
            blocksize=4000,
            dtype="int16",
            channels=1,
            callback=callback,
        ):
            while not self._stop.is_set():
                try:
                    chunk = audio_q.get(timeout=0.2)
                except queue.Empty:
                    continue
                if rec.AcceptWaveform(chunk):
                    text = json.loads(rec.Result()).get("text", "").strip()
                    if text:
                        self.on_text(text)
