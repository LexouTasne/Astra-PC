from __future__ import annotations

import cv2
import mediapipe as mp


class BodyPoseTracker:
    """Optional full-body pose tracking using local MediaPipe."""

    def __init__(self):
        self.pose = mp.solutions.pose.Pose(
            static_image_mode=False,
            model_complexity=0,
            smooth_landmarks=True,
            enable_segmentation=False,
            min_detection_confidence=0.5,
            min_tracking_confidence=0.5,
        )

    def process(self, frame_bgr) -> list[dict]:
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        result = self.pose.process(rgb)
        if not result.pose_landmarks:
            return []
        return [
            {
                "x": round(float(p.x), 5),
                "y": round(float(p.y), 5),
                "z": round(float(p.z), 5),
                "visibility": round(float(p.visibility), 4),
            }
            for p in result.pose_landmarks.landmark
        ]

    def close(self) -> None:
        self.pose.close()
