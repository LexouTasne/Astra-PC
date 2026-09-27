from __future__ import annotations

from pathlib import Path
from typing import Callable

import numpy as np


class OpenWakeWordDetector:
    """Optional dedicated wake-word detector using a user supplied openWakeWord model."""

    def __init__(
        self,
        model_path: str | Path,
        on_wake: Callable[[], None],
        threshold: float = 0.55,
    ):
        try:
            import sounddevice as sd
            from openwakeword.model import Model
        except ImportError as exc:
            raise RuntimeError(
                "Install wake-word support with: pip install -e '.[wakeword]'"
            ) from exc

        self.sd = sd
        self.on_wake = on_wake
        self.threshold = threshold
        self.model = Model(wakeword_models=[str(Path(model_path).expanduser())])
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
