from __future__ import annotations

import glob
import platform
import time
from dataclasses import dataclass
from pathlib import Path

import cv2


@dataclass(slots=True)
class OpenedCamera:
    cap: cv2.VideoCapture
    index: int
    source: str


def candidate_cameras(preferred: int = 0, limit: int = 16) -> list[tuple[int, str | int]]:
    candidates: list[tuple[int, str | int]] = []

    if platform.system() == "Linux":
        for path in sorted(glob.glob("/dev/video*"))[:limit]:
            suffix = Path(path).name.removeprefix("video")
            if suffix.isdigit():
                candidates.append((int(suffix), path))
    else:
        candidates = [(i, i) for i in range(limit)]

    # Try the configured/preferred camera first, but never duplicate it.
    candidates.sort(key=lambda item: (item[0] != preferred, item[0]))
    return candidates


def open_first_camera(
    preferred: int = 0,
    width: int = 640,
    height: int = 360,
    fps: int = 30,
    limit: int = 16,
    warmup_reads: int = 8,
) -> OpenedCamera | None:
    previous_level = None
    try:
        if hasattr(cv2, "getLogLevel") and hasattr(cv2, "setLogLevel"):
            previous_level = cv2.getLogLevel()
            cv2.setLogLevel(0)
    except Exception:
        previous_level = None

    try:
        for index, source in candidate_cameras(preferred, limit):
            try:
                if platform.system() == "Linux":
                    cap = cv2.VideoCapture(source, cv2.CAP_V4L2)
                else:
                    cap = cv2.VideoCapture(source)
            except Exception:
                continue

            try:
                if not cap.isOpened():
                    cap.release()
                    continue

                cap.set(cv2.CAP_PROP_FRAME_WIDTH, int(width))
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, int(height))
                cap.set(cv2.CAP_PROP_FPS, int(fps))
                cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

                good = False
                for _ in range(max(1, warmup_reads)):
                    ok, frame = cap.read()
                    if ok and frame is not None and getattr(frame, "size", 0):
                        good = True
                        break
                    time.sleep(0.03)

                if good:
                    return OpenedCamera(cap=cap, index=index, source=str(source))

                cap.release()
            except Exception:
                cap.release()
                continue
    finally:
        if previous_level is not None:
            try:
                cv2.setLogLevel(previous_level)
            except Exception:
                pass

    return None
