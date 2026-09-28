from __future__ import annotations

import collections
import queue
import threading
from pathlib import Path
from typing import Callable

import numpy as np


class FastWhisperVoiceEngine:
    """Low-latency microphone ASR with WebRTC VAD and a resident faster-whisper model."""

    def __init__(
        self,
        on_text: Callable[[str], None],
        *,
        model_size: str = "base",
        language: str = "pt",
        sample_rate: int = 16000,
        frame_ms: int = 30,
        silence_ms: int = 360,
        pre_roll_ms: int = 240,
        max_utterance_s: float = 10.0,
        raw_frame_callback: Callable[[bytes], None] | None = None,
        initial_prompt: str | None = None,
        hotwords: str | None = None,
    ):
        try:
            import sounddevice as sd
            import webrtcvad
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise RuntimeError(
                'Install fast voice support with: pip install -e ".[voice-fast]"'
            ) from exc

        self.sd = sd
        self.vad = webrtcvad.Vad(2)
        self.model = WhisperModel(
            model_size,
            device="auto",
            compute_type="int8",
            cpu_threads=max(2, min(8, __import__("os").cpu_count() or 4)),
        )
        self.on_text = on_text
        self.raw_frame_callback = raw_frame_callback
        self.language = language
        self.initial_prompt = initial_prompt or (
            "Astra, assistente local em português do Brasil. "
            "Transcreva números, contas e nomes de aplicativos com precisão."
        )
        self.hotwords = hotwords or (
            "Astra DroidCam navegador terminal volume clipboard "
            "um dois três quatro cinco seis sete oito nove dez"
        )
        self.sample_rate = sample_rate
        self.frame_ms = frame_ms
        self.silence_frames = max(1, silence_ms // frame_ms)
        self.pre_roll_frames = max(1, pre_roll_ms // frame_ms)
        self.max_frames = max(1, int(max_utterance_s * 1000 / frame_ms))
        self.frame_samples = int(sample_rate * frame_ms / 1000)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="astra-fast-asr", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1.5)

    def _run(self) -> None:
        audio_q: queue.Queue[bytes] = queue.Queue(maxsize=64)
        preroll = collections.deque(maxlen=self.pre_roll_frames)
        active = False
        speech: list[bytes] = []
        silent = 0

        def callback(indata, frames, time_info, status):
            if status:
                return
            try:
                audio_q.put_nowait(bytes(indata))
            except queue.Full:
                try:
                    audio_q.get_nowait()
                    audio_q.put_nowait(bytes(indata))
                except queue.Empty:
                    pass

        with self.sd.RawInputStream(
            samplerate=self.sample_rate,
            blocksize=self.frame_samples,
            dtype="int16",
            channels=1,
            callback=callback,
        ):
            while not self._stop.is_set():
                try:
                    frame = audio_q.get(timeout=0.15)
                except queue.Empty:
                    continue

                if len(frame) != self.frame_samples * 2:
                    continue

                if self.raw_frame_callback is not None:
                    try:
                        self.raw_frame_callback(frame)
                    except Exception:
                        pass

                is_speech = self.vad.is_speech(frame, self.sample_rate)

                if not active:
                    preroll.append(frame)
                    if is_speech:
                        active = True
                        speech = list(preroll)
                        silent = 0
                    continue

                speech.append(frame)
                if is_speech:
                    silent = 0
                else:
                    silent += 1

                if silent >= self.silence_frames or len(speech) >= self.max_frames:
                    utterance = b"".join(speech)
                    active = False
                    speech = []
                    silent = 0
                    preroll.clear()
                    self._transcribe(utterance)

    def _transcribe(self, pcm: bytes) -> None:
        audio = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
        if audio.size < self.sample_rate // 4:
            return

        segments, _ = self.model.transcribe(
            audio,
            language=self.language,
            beam_size=1,
            best_of=1,
            temperature=0.0,
            vad_filter=False,
            condition_on_previous_text=False,
            without_timestamps=True,
            word_timestamps=False,
            initial_prompt=self.initial_prompt,
            hotwords=self.hotwords,
        )
        text = " ".join(seg.text.strip() for seg in segments).strip()
        if text:
            self.on_text(text)
