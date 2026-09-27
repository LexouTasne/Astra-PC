from __future__ import annotations

import platform
import sys
from pathlib import Path
from typing import Callable

import numpy as np


class OpenWakeWordDetector:
    """Optional dedicated wake-word detector using local openWakeWord models."""

    def __init__(
        self,
        model_path: str | Path,
        on_wake: Callable[[], None],
        threshold: float = 0.55,
    ):
        path = Path(model_path).expanduser()
        if not path.exists():
            raise FileNotFoundError(path)

        if (
            path.suffix.lower() == ".tflite"
            and platform.system() == "Linux"
            and sys.version_info >= (3, 12)
        ):
            raise RuntimeError(
                "TFLite openWakeWord models are unavailable on Linux/Python 3.12 "
                "because tflite-runtime has no cp312 wheel. Use an .onnx wake-word model."
            )

        try:
            from openwakeword.model import Model
        except ImportError as exc:
            raise RuntimeError(
                "Dedicated wake-word support is not installed. "
                "Run installer.py --awareness-extras."
            ) from exc

        self.on_wake = on_wake
        self.threshold = threshold
        kwargs = {"wakeword_models": [str(path)]}
        if path.suffix.lower() == ".onnx":
            kwargs["inference_framework"] = "onnx"
        self.model = Model(**kwargs)
        self._active = False

    def process_pcm(self, pcm: bytes) -> None:
        audio = np.frombuffer(pcm, dtype=np.int16)
        predictions = self.model.predict(audio)
        score = max((float(v) for v in predictions.values()), default=0.0)
        if score >= self.threshold and not self._active:
            self._active = True
            self.on_wake()
        elif score < self.threshold * 0.55:
            self._active = False
