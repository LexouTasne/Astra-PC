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
        input_device: int | str | None = None,
        adaptive_retry: bool = True,
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
        self.input_device = input_device
        self.adaptive_retry = adaptive_retry
        self.sample_rate = int(sample_rate)
        self.capture_rate = self._resolve_capture_rate(self.sample_rate)
        self.frame_ms = frame_ms
        self.silence_frames = max(1, silence_ms // frame_ms)
        self.pre_roll_frames = max(1, pre_roll_ms // frame_ms)
        self.max_frames = max(1, int(max_utterance_s * 1000 / frame_ms))
        self.frame_samples = int(self.sample_rate * frame_ms / 1000)
        self.capture_frame_samples = int(
            round(self.capture_rate * frame_ms / 1000)
        )
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def _resolve_capture_rate(self, target_rate: int) -> int:
        """Use target rate when possible, otherwise capture at a native rate.

        If a saved device disappeared or became invalid, fall back to the
        current default input instead of letting the ASR thread crash.
        """
        candidates = [self.input_device]
        if self.input_device is not None:
            candidates.append(None)

        last_error = None
        for candidate in candidates:
            try:
                self.sd.check_input_settings(
                    device=candidate,
                    channels=1,
                    dtype="int16",
                    samplerate=target_rate,
                )
                if candidate != self.input_device:
                    print("[asr] saved microphone unavailable; using system default")
                    self.input_device = candidate
                return target_rate
            except Exception as exc:
                last_error = exc

            try:
                info = self.sd.query_devices(candidate, "input")
                native = int(round(float(info.get("default_samplerate", 48000))))
                self.sd.check_input_settings(
                    device=candidate,
                    channels=1,
                    dtype="int16",
                    samplerate=native,
                )
                if candidate != self.input_device:
                    print("[asr] saved microphone unavailable; using system default")
                    self.input_device = candidate
                print(
                    f"[asr] microphone does not accept {target_rate} Hz; "
                    f"capturing at {native} Hz and resampling"
                )
                return native
            except Exception as exc:
                last_error = exc

        raise RuntimeError(
            f"No usable microphone input could be opened: {last_error}"
        )

    def _to_target_rate(self, pcm: bytes) -> bytes:
        if self.capture_rate == self.sample_rate:
            return pcm
        src = np.frombuffer(pcm, dtype=np.int16)
        if src.size == 0:
            return b""
        target_len = max(
            1,
            int(round(src.size * self.sample_rate / self.capture_rate)),
        )
        old_x = np.linspace(0.0, 1.0, num=src.size, endpoint=False)
        new_x = np.linspace(0.0, 1.0, num=target_len, endpoint=False)
        converted = np.interp(new_x, old_x, src.astype(np.float32))
        return np.clip(converted, -32768, 32767).astype(np.int16).tobytes()

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
                audio_q.put_nowait(self._to_target_rate(bytes(indata)))
            except queue.Full:
                try:
                    audio_q.get_nowait()
                    audio_q.put_nowait(self._to_target_rate(bytes(indata)))
                except queue.Empty:
                    pass

        with self.sd.RawInputStream(
            device=self.input_device,
            samplerate=self.capture_rate,
            blocksize=self.capture_frame_samples,
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

        text, confidence = self._decode(audio, beam_size=1)
        if self.adaptive_retry and self._needs_retry(text, confidence):
            retry_text, retry_confidence = self._decode(audio, beam_size=4)
            if retry_text and (
                not text
                or retry_confidence >= confidence - 0.05
                or len(retry_text) > len(text)
            ):
                text = retry_text

        text = text.strip()
        if text:
            self.on_text(text)

    def _decode(self, audio: np.ndarray, beam_size: int) -> tuple[str, float]:
        segments, _ = self.model.transcribe(
            audio,
            language=self.language,
            task="transcribe",
            beam_size=beam_size,
            best_of=1,
            patience=1.0,
            temperature=0.0,
            vad_filter=False,
            condition_on_previous_text=False,
            without_timestamps=True,
            word_timestamps=False,
            initial_prompt=self.initial_prompt,
            hotwords=self.hotwords,
            suppress_blank=True,
            log_prob_threshold=-1.3,
            no_speech_threshold=0.72,
        )
        items = list(segments)
        text = " ".join(seg.text.strip() for seg in items).strip()
        if not items:
            return text, -99.0
        weights = [max(1.0, float(seg.end - seg.start)) for seg in items]
        confidence = sum(
            float(seg.avg_logprob) * weight
            for seg, weight in zip(items, weights)
        ) / sum(weights)
        return text, confidence

    @staticmethod
    def _needs_retry(text: str, confidence: float) -> bool:
        cleaned = text.strip()
        if not cleaned:
            return True
        if len(cleaned) <= 2:
            return True
        if confidence < -0.72:
            return True
        words = cleaned.lower().split()
        if len(words) >= 3 and len(set(words)) <= max(1, len(words) // 3):
            return True
        return False

