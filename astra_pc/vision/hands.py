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
        self._slow_alpha = min(
            1.0,
            max(0.05, float(cfg.get("landmark_slow_alpha", 0.58))),
        )
        self._fast_alpha = min(
            1.0,
            max(self._slow_alpha, float(cfg.get("landmark_fast_alpha", 0.94))),
        )
        self._motion_threshold = max(
            0.002,
            float(cfg.get("landmark_motion_threshold", 0.018)),
        )
        self._snap_distance = max(
            self._motion_threshold,
            float(cfg.get("landmark_snap_distance", 0.085)),
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

        smoothed = []
        for old, new in zip(previous, points):
            motion = self._distance(old, new)
            # Adaptive EMA: tiny movements are stabilized, deliberate motion is
            # almost raw, and large jumps snap immediately. This keeps gesture
            # poses stable without adding perceptible hand lag.
            if motion >= self._snap_distance:
                smoothed.append(new)
                continue

            if motion <= self._motion_threshold:
                ratio = motion / self._motion_threshold
                a = self._slow_alpha + (self._smoothing - self._slow_alpha) * ratio
            else:
                span = max(1e-6, self._snap_distance - self._motion_threshold)
                ratio = min(1.0, (motion - self._motion_threshold) / span)
                a = self._smoothing + (self._fast_alpha - self._smoothing) * ratio

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
