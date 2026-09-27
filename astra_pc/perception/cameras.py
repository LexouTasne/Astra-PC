from __future__ import annotations

import cv2


class MultiCamera:
    def __init__(self, indexes: list[int]):
        self.caps = [cv2.VideoCapture(i) for i in indexes]

    def opened(self) -> list[bool]:
        return [cap.isOpened() for cap in self.caps]

    def read(self):
        frames = []
        for cap in self.caps:
            ok, frame = cap.read()
            frames.append(frame if ok else None)
        return frames

    def close(self) -> None:
        for cap in self.caps:
            cap.release()
