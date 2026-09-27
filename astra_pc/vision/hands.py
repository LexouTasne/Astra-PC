from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import cv2
import mediapipe as mp


@dataclass(slots=True, frozen=True)
class Point:
    x: float
    y: float
    z: float


@dataclass(slots=True)
class Hand:
    points: tuple[Point, ...]
    handedness: str

    def __getitem__(self, index: int) -> Point:
        return self.points[index]


class HandTracker:
    def __init__(self, cfg: dict):
        self._hands = mp.solutions.hands.Hands(
            static_image_mode=False,
            max_num_hands=int(cfg["max_hands"]),
            model_complexity=int(cfg["model_complexity"]),
            min_detection_confidence=float(cfg["min_detection_confidence"]),
            min_tracking_confidence=float(cfg["min_tracking_confidence"]),
        )

    def process(self, frame_bgr) -> list[Hand]:
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        rgb.flags.writeable = False
        result = self._hands.process(rgb)
        if not result.multi_hand_landmarks:
            return []

        labels: Iterable[str] = (
            h.classification[0].label for h in (result.multi_handedness or [])
        )
        labels = list(labels)
        found: list[Hand] = []
        for i, raw_hand in enumerate(result.multi_hand_landmarks):
            pts = tuple(Point(p.x, p.y, p.z) for p in raw_hand.landmark)
            found.append(Hand(pts, labels[i] if i < len(labels) else "Unknown"))
        return found

    def close(self) -> None:
        self._hands.close()
