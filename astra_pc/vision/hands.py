from __future__ import annotations

import math
from typing import Iterable

import cv2
import mediapipe as mp

from .types import Hand, Point


class HandTracker:
    def __init__(self, cfg: dict):
        self._hands = mp.solutions.hands.Hands(
            static_image_mode=False,
            max_num_hands=int(cfg["max_hands"]),
            model_complexity=int(cfg["model_complexity"]),
            min_detection_confidence=float(cfg["min_detection_confidence"]),
            min_tracking_confidence=float(cfg["min_tracking_confidence"]),
        )
        self._smoothing = min(
            1.0,
            max(0.0, float(cfg.get("landmark_smoothing", 0.72))),
        )
        self._snap_distance = max(
            0.01,
            float(cfg.get("landmark_snap_distance", 0.10)),
        )
        self._previous: dict[str, tuple[Point, ...]] = {}

    @staticmethod
    def _distance(a: Point, b: Point) -> float:
        return math.sqrt(
            (a.x - b.x) ** 2
            + (a.y - b.y) ** 2
            + (a.z - b.z) ** 2
        )

    def _smooth(
        self,
        key: str,
        points: tuple[Point, ...],
    ) -> tuple[Point, ...]:
        previous = self._previous.get(key)
        if (
            previous is None
            or len(previous) != len(points)
            or self._smoothing >= 0.999
        ):
            self._previous[key] = points
            return points

        a = self._smoothing
        smoothed = []
        for old, new in zip(previous, points):
            # Fast deliberate motion should never feel like it is dragging
            # through syrup. Snap on large jumps; EMA only the small jitter.
            if self._distance(old, new) >= self._snap_distance:
                smoothed.append(new)
            else:
                smoothed.append(
                    Point(
                        old.x + (new.x - old.x) * a,
                        old.y + (new.y - old.y) * a,
                        old.z + (new.z - old.z) * a,
                    )
                )
        result = tuple(smoothed)
        self._previous[key] = result
        return result

    def process(self, frame_bgr) -> list[Hand]:
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        rgb.flags.writeable = False
        result = self._hands.process(rgb)
        if not result.multi_hand_landmarks:
            self._previous.clear()
            return []

        labels: Iterable[str] = (
            h.classification[0].label for h in (result.multi_handedness or [])
        )
        labels = list(labels)
        found: list[Hand] = []
        active_keys: set[str] = set()

        for i, raw_hand in enumerate(result.multi_hand_landmarks):
            label = labels[i] if i < len(labels) else "Unknown"
            key = label if label in {"Left", "Right"} else f"Unknown-{i}"
            active_keys.add(key)
            raw_points = tuple(
                Point(p.x, p.y, p.z)
                for p in raw_hand.landmark
            )
            points = self._smooth(key, raw_points)
            found.append(Hand(points, label))

        # Do not let stale coordinates from a vanished hand leak into a later
        # re-detection.
        for key in list(self._previous):
            if key not in active_keys:
                self._previous.pop(key, None)

        return found

    def close(self) -> None:
        self._previous.clear()
        self._hands.close()
