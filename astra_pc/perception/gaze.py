from __future__ import annotations

import cv2
import mediapipe as mp


class GazeEstimator:
    """Optional lightweight webcam gaze direction estimate using FaceMesh irises."""

    def __init__(self):
        self.mesh = mp.solutions.face_mesh.FaceMesh(
            max_num_faces=1,
            refine_landmarks=True,
            min_detection_confidence=0.5,
            min_tracking_confidence=0.5,
        )

    def estimate(self, frame_bgr) -> dict | None:
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        result = self.mesh.process(rgb)
        if not result.multi_face_landmarks:
            return None

        lm = result.multi_face_landmarks[0].landmark
        # MediaPipe refined FaceMesh iris centers.
        left_iris = lm[468]
        right_iris = lm[473]
        left_outer, left_inner = lm[33], lm[133]
        right_inner, right_outer = lm[362], lm[263]

        def ratio(iris, a, b):
            width = max(1e-6, abs(b.x - a.x))
            return (iris.x - min(a.x, b.x)) / width

        horizontal = (
            ratio(left_iris, left_outer, left_inner)
            + ratio(right_iris, right_inner, right_outer)
        ) / 2.0
        direction = "center"
        if horizontal < 0.38:
            direction = "left"
        elif horizontal > 0.62:
            direction = "right"

        return {
            "direction": direction,
            "horizontal": round(float(horizontal), 3),
            "point": [
                round(float((left_iris.x + right_iris.x) / 2), 3),
                round(float((left_iris.y + right_iris.y) / 2), 3),
            ],
        }

    def close(self) -> None:
        self.mesh.close()
