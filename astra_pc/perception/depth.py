from __future__ import annotations

from pathlib import Path

import cv2


class DepthEstimator:
    """Optional monocular depth backend using a user-provided ONNX model."""

    def __init__(self, model_path: str | Path):
        self.path = Path(model_path)
        if not self.path.exists():
            raise FileNotFoundError(self.path)
        self.net = cv2.dnn.readNetFromONNX(str(self.path))

    def estimate(self, frame_bgr):
        h, w = frame_bgr.shape[:2]
        blob = cv2.dnn.blobFromImage(
            frame_bgr,
            scalefactor=1.0 / 255.0,
            size=(256, 256),
            swapRB=True,
            crop=False,
        )
        self.net.setInput(blob)
        depth = self.net.forward()
        depth = depth.squeeze()
        return cv2.resize(depth, (w, h), interpolation=cv2.INTER_CUBIC)


class StereoDepth:
    """Fast classical stereo depth for two aligned cameras."""

    def __init__(self):
        self.matcher = cv2.StereoSGBM_create(
            minDisparity=0,
            numDisparities=64,
            blockSize=5,
            P1=8 * 3 * 5 * 5,
            P2=32 * 3 * 5 * 5,
        )

    def disparity(self, left_bgr, right_bgr):
        left = cv2.cvtColor(left_bgr, cv2.COLOR_BGR2GRAY)
        right = cv2.cvtColor(right_bgr, cv2.COLOR_BGR2GRAY)
        return self.matcher.compute(left, right).astype("float32") / 16.0
