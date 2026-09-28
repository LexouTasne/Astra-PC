from __future__ import annotations

import collections
import difflib
import queue
import threading
from pathlib import Path
from typing import Callable

import numpy as np


class FastWhisperVoiceEngine:
    """Continuous low-latency microphone ASR for Brazilian Portuguese.

    Capture/VAD and Whisper decoding run on different threads so the microphone
    never stops being consumed while a previous utterance is being decoded.
    """

    def __init__(
        self,
        on_text: Callable[[str], None],
        *,
        model_size: str = "base",
        language: str = "pt",
        sample_rate: int = 16000,
        frame_ms: int = 30,
        silence_ms: int = 480,
        pre_roll_ms: int = 300,
        start_speech_ms: int = 60,
        min_utterance_ms: int = 180,
        max_utterance_s: float = 18.0,
        vad_mode: int = 2,
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
        self.vad_mode = max(0, min(3, int(vad_mode)))
        self.vad = webrtcvad.Vad(self.vad_mode)
        self.model = WhisperModel(
            model_size,
            device="auto",
            compute_type="int8",
            cpu_threads=max(2, min(8, __import__("os").cpu_count() or 4)),
        )
        self.on_text = on_text
        self.raw_frame_callback = raw_frame_callback
        self.language = language
        self.initial_prompt = initial_prompt or "Português do Brasil. Assistente Astra."
        # Keep this list short. Too many hotwords can bias ordinary speech.
        self.hotwords = hotwords or (
            "Astra Discord Brave Spotify VS Code terminal navegador "
            "Downloads arquivo pasta volume clipboard"
        )
        self.input_device = input_device
        self.adaptive_retry = adaptive_retry
        self.sample_rate = int(sample_rate)
        self.capture_rate = self._resolve_capture_rate(self.sample_rate)
        self.frame_ms = int(frame_ms)
        self.silence_frames = max(1, int(silence_ms) // self.frame_ms)
        self.pre_roll_frames = max(1, int(pre_roll_ms) // self.frame_ms)
        self.start_speech_frames = max(1, int(start_speech_ms) // self.frame_ms)
        self.min_speech_frames = max(1, int(min_utterance_ms) // self.frame_ms)
        self.max_frames = max(1, int(max_utterance_s * 1000 / self.frame_ms))
        self.tail_frames = max(1, 150 // self.frame_ms)
        self.frame_samples = int(self.sample_rate * self.frame_ms / 1000)
        self.capture_frame_samples = int(
            round(self.capture_rate * self.frame_ms / 1000)
        )
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._decoder_thread: threading.Thread | None = None
        self._utterances: queue.Queue[bytes | None] = queue.Queue(maxsize=4)

    def _resolve_capture_rate(self, target_rate: int) -> int:
        """Use target rate when possible, otherwise capture at a native rate."""
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

    @staticmethod
    def _condition_audio(audio: np.ndarray) -> np.ndarray:
        """Cheap conditioning for quiet desktop microphones.

        Removes DC offset and applies conservative gain only when speech is
        genuinely quiet. It intentionally avoids heavy denoising libraries.
        """
        if audio.size == 0:
            return audio.astype(np.float32, copy=False)

        out = audio.astype(np.float32, copy=True)
        out -= float(np.mean(out))
        rms = float(np.sqrt(np.mean(np.square(out)) + 1e-12))
        peak = float(np.max(np.abs(out)))

        if rms < 0.003 or peak < 0.008:
            return out

        if rms < 0.055 and peak < 0.85:
            gain = min(3.0, 0.07 / max(rms, 1e-6))
            out *= gain

        return np.clip(out, -0.98, 0.98)

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._decoder_thread = threading.Thread(
            target=self._decode_loop,
            name="astra-whisper-decode",
            daemon=True,
        )
        self._thread = threading.Thread(
            target=self._run,
            name="astra-fast-asr",
            daemon=True,
        )
        self._decoder_thread.start()
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        try:
            self._utterances.put_nowait(None)
        except queue.Full:
            pass
        if self._thread:
            self._thread.join(timeout=1.5)
        if self._decoder_thread:
            self._decoder_thread.join(timeout=2.0)

    def _enqueue_utterance(self, pcm: bytes) -> None:
        if not pcm:
            return
        try:
            self._utterances.put_nowait(pcm)
            return
        except queue.Full:
            pass

        # Prefer the newest thing the user said over stale queued audio.
        try:
            self._utterances.get_nowait()
            self._utterances.put_nowait(pcm)
            print("[asr] decoder backlog: dropped one stale utterance")
        except (queue.Empty, queue.Full):
            pass

    def _decode_loop(self) -> None:
        while not self._stop.is_set():
            try:
                pcm = self._utterances.get(timeout=0.20)
            except queue.Empty:
                continue
            if pcm is None:
                return
            try:
                self._transcribe(pcm)
            except Exception as exc:
                print(f"[asr] transcription failed: {exc}")

    def _run(self) -> None:
        audio_q: queue.Queue[bytes] = queue.Queue(maxsize=128)
        preroll = collections.deque(maxlen=self.pre_roll_frames)
        active = False
        speech: list[bytes] = []
        silent = 0
        speech_run = 0
        voiced = 0

        def callback(indata, frames, time_info, status):
            if status:
                # PortAudio overflow/underflow is useful for diagnostics, but
                # dropping the entire callback makes recognition worse.
                print(f"[asr] audio status: {status}")
            converted = self._to_target_rate(bytes(indata))
            if not converted:
                return
            try:
                audio_q.put_nowait(converted)
            except queue.Full:
                try:
                    audio_q.get_nowait()
                    audio_q.put_nowait(converted)
                except (queue.Empty, queue.Full):
                    pass

        with self.sd.RawInputStream(
            device=self.input_device,
            samplerate=self.capture_rate,
            blocksize=self.capture_frame_samples,
            dtype="int16",
            channels=1,
            callback=callback,
            latency="low",
        ):
            print(
                f"[asr] listening: {self.capture_rate}Hz -> {self.sample_rate}Hz, "
                f"vad={self.vad_mode}, endpoint={self.silence_frames * self.frame_ms}ms"
            )
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

                try:
                    is_speech = self.vad.is_speech(frame, self.sample_rate)
                except Exception:
                    is_speech = False

                if not active:
                    preroll.append(frame)
                    if is_speech:
                        speech_run += 1
                    else:
                        speech_run = 0

                    if speech_run >= self.start_speech_frames:
                        active = True
                        speech = list(preroll)
                        voiced = speech_run
                        silent = 0
                    continue

                speech.append(frame)
                if is_speech:
                    voiced += 1
                    silent = 0
                else:
                    silent += 1

                endpoint = silent >= self.silence_frames
                forced = len(speech) >= self.max_frames
                if endpoint or forced:
                    if voiced >= self.min_speech_frames:
                        # Keep a small natural tail but remove most endpoint silence.
                        trim = max(0, silent - self.tail_frames)
                        final_frames = speech[:-trim] if trim else speech
                        self._enqueue_utterance(b"".join(final_frames))

                    # Even a too-short noise burst must return to idle instead
                    # of holding the microphone session open until max duration.
                    active = False
                    speech = []
                    silent = 0
                    speech_run = 0
                    voiced = 0
                    preroll.clear()

    def _transcribe(self, pcm: bytes) -> None:
        audio = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
        if audio.size < self.sample_rate // 4:
            return

        raw_rms = float(np.sqrt(np.mean(np.square(audio)) + 1e-12))
        audio = self._condition_audio(audio)
        text, confidence = self._decode(audio, beam_size=1)

        if self.adaptive_retry and self._needs_retry(text, confidence):
            retry_text, retry_confidence = self._decode(audio, beam_size=5)
            if retry_text and (
                not text
                or retry_confidence >= confidence - 0.04
                or len(retry_text.split()) > len(text.split())
            ):
                text = retry_text
                confidence = retry_confidence

        text = " ".join(text.strip().split())
        if not text:
            return
        if self._is_hallucination(text, confidence, raw_rms):
            print(f"[asr] rejected hallucination: {text} (score={confidence:.2f})")
            return

        print(f"[asr] {text} (score={confidence:.2f})")
        self.on_text(text)

    def _decode(self, audio: np.ndarray, beam_size: int) -> tuple[str, float]:
        segments, _ = self.model.transcribe(
            audio,
            language=self.language,
            task="transcribe",
            beam_size=beam_size,
            best_of=1,
            patience=1.0 if beam_size == 1 else 1.2,
            temperature=0.0,
            vad_filter=False,
            condition_on_previous_text=False,
            without_timestamps=True,
            word_timestamps=False,
            initial_prompt=self.initial_prompt,
            hotwords=self.hotwords,
            suppress_blank=True,
            log_prob_threshold=-1.2,
            no_speech_threshold=0.68,
            compression_ratio_threshold=2.4,
        )
        items = list(segments)
        text = " ".join(seg.text.strip() for seg in items).strip()
        if not items:
            return text, -99.0
        weights = [max(0.2, float(seg.end - seg.start)) for seg in items]
        confidence = sum(
            float(seg.avg_logprob) * weight
            for seg, weight in zip(items, weights)
        ) / sum(weights)
        return text, confidence

    def _is_hallucination(self, text: str, confidence: float, rms: float) -> bool:
        q = " ".join(text.lower().strip().split())
        if not q:
            return True

        known_noise = (
            "se inscreva no canal",
            "obrigado por assistir",
            "legendas pela comunidade",
            "o que a pessoa disser",
            "deixe-me saber o que a pessoa disser",
        )
        if any(phrase in q for phrase in known_noise):
            return True

        prompt = " ".join(self.initial_prompt.lower().split())
        if len(q) >= 12 and difflib.SequenceMatcher(None, q, prompt).ratio() >= 0.72:
            return True

        words = q.split()
        if len(words) >= 10:
            unique_ratio = len(set(words)) / max(1, len(words))
            if unique_ratio <= 0.38:
                return True

        # Very weak multi-word decodes are overwhelmingly room noise on the
        # always-on resident microphone. Short wake words remain allowed.
        if len(words) >= 4 and confidence < -0.98:
            return True
        if len(words) >= 2 and rms < 0.0025 and confidence < -0.75:
            return True
        return False

    @staticmethod
    def _needs_retry(text: str, confidence: float) -> bool:
        cleaned = text.strip()
        if not cleaned:
            return True
        if len(cleaned) <= 2:
            return True
        if confidence < -0.68:
            return True
        words = cleaned.lower().split()
        if len(words) >= 3 and len(set(words)) <= max(1, len(words) // 3):
            return True
        # Hallucinated captions/noise often arrive as punctuation-heavy junk.
        alnum = sum(ch.isalnum() for ch in cleaned)
        if alnum < max(2, len(cleaned) // 3):
            return True
        return False
