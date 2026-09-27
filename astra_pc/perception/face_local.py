from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np


class LocalFaceProfiles:
    """Explicit opt-in local face profiles using OpenCV LBPH. No network use."""

    def __init__(self, root: str | Path | None = None):
        self.root = Path(root or (Path.home() / ".local" / "share" / "astra-pc" / "faces")).expanduser()
        self.root.mkdir(parents=True, exist_ok=True)
        self.labels_path = self.root / "labels.json"
        self.model_path = self.root / "lbph.yml"
        cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        self.detector = cv2.CascadeClassifier(cascade_path)

    def enroll(self, name: str, frames_bgr: list[np.ndarray]) -> int:
        profile = self.root / self._safe(name)
        profile.mkdir(parents=True, exist_ok=True)
        saved = 0
        for frame in frames_bgr:
            face = self._largest_face(frame)
            if face is None:
                continue
            face = cv2.resize(face, (160, 160))
            cv2.imwrite(str(profile / f"{saved:03d}.png"), face)
            saved += 1
        if saved:
            self.train()
        return saved

    def train(self) -> None:
        if not hasattr(cv2, "face"):
            raise RuntimeError("OpenCV contrib face module is unavailable.")
        images, labels, names = [], [], {}
        next_id = 0
        for directory in sorted(p for p in self.root.iterdir() if p.is_dir()):
            names[next_id] = directory.name
            for image_path in directory.glob("*.png"):
                image = cv2.imread(str(image_path), cv2.IMREAD_GRAYSCALE)
                if image is not None:
                    images.append(image)
                    labels.append(next_id)
            next_id += 1
        if not images:
            raise RuntimeError("No enrolled face samples.")
        model = cv2.face.LBPHFaceRecognizer_create()
        model.train(images, np.asarray(labels, dtype=np.int32))
        model.write(str(self.model_path))
        self.labels_path.write_text(json.dumps(names), encoding="utf-8")

    def recognize(self, frame_bgr, threshold: float = 72.0) -> dict | None:
        if not self.model_path.exists() or not self.labels_path.exists() or not hasattr(cv2, "face"):
            return None
        face = self._largest_face(frame_bgr)
        if face is None:
            return None
        model = cv2.face.LBPHFaceRecognizer_create()
        model.read(str(self.model_path))
        label, confidence = model.predict(cv2.resize(face, (160, 160)))
        names = json.loads(self.labels_path.read_text(encoding="utf-8"))
        if float(confidence) > threshold:
            return {"name": None, "confidence": round(float(confidence), 2)}
        return {"name": names.get(str(label)) or names.get(label), "confidence": round(float(confidence), 2)}

    def _largest_face(self, frame_bgr):
        gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
        boxes = self.detector.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(60, 60))
        if len(boxes) == 0:
            return None
        x, y, w, h = max(boxes, key=lambda b: b[2] * b[3])
        return gray[y:y+h, x:x+w]

    @staticmethod
    def _safe(name: str) -> str:
        return "".join(c for c in name.lower().replace(" ", "-") if c.isalnum() or c in "-_") or "profile"
