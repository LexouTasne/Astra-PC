from __future__ import annotations

import cv2
import numpy as np


class ScreenChangeDetector:
    def __init__(self, threshold: float = 0.018, size: tuple[int, int] = (320, 180)):
        self.threshold = threshold
        self.size = size
        self._previous: np.ndarray | None = None

    def changed(self, frame_bgr) -> tuple[bool, float]:
        gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
        gray = cv2.resize(gray, self.size, interpolation=cv2.INTER_AREA)
        if self._previous is None:
            self._previous = gray
            return True, 1.0
        diff = cv2.absdiff(self._previous, gray)
        score = float(np.count_nonzero(diff > 14)) / float(diff.size)
        self._previous = gray
        return score >= self.threshold, score
