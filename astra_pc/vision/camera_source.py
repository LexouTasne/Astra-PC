from __future__ import annotations

import glob
import platform
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import cv2


class LatestFrameCapture:
    """Continuously consume camera frames and expose only the newest one.

    Gesture recognition should react to *now*, not process a FIFO of stale
    camera frames when MediaPipe briefly takes longer than the camera period.
    """

    def __init__(self, cap: cv2.VideoCapture):
        self._cap = cap
        self._lock = threading.Lock()
        self._condition = threading.Condition(self._lock)
        self._stop = threading.Event()
        self._frame = None
        self._ok = False
        self._version = 0
        self._last_read_version = -1
        self._thread = threading.Thread(
            target=self._reader,
            name="astra-camera-latest",
            daemon=True,
        )
        self._thread.start()

    def _reader(self) -> None:
        while not self._stop.is_set():
            ok, frame = self._cap.read()
            if not ok or frame is None:
                time.sleep(0.002)
                continue
            with self._condition:
                self._frame = frame
                self._ok = True
                self._version += 1
                self._condition.notify_all()

    def read(self):
        with self._condition:
            if self._version == self._last_read_version and not self._stop.is_set():
                self._condition.wait(timeout=0.025)
            if (
                not self._ok
                or self._frame is None
                or self._version == self._last_read_version
            ):
                return False, None
            self._last_read_version = self._version
            return True, self._frame

    def isOpened(self) -> bool:
        return bool(self._cap.isOpened())

    def release(self) -> None:
        self._stop.set()
        with self._condition:
            self._condition.notify_all()
        try:
            self._cap.release()
        finally:
            if self._thread.is_alive():
                self._thread.join(timeout=0.5)

    def set(self, prop, value):
        return self._cap.set(prop, value)

    def get(self, prop):
        return self._cap.get(prop)


@dataclass(slots=True)
class OpenedCamera:
    cap: LatestFrameCapture
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

    candidates.sort(key=lambda item: (item[0] != preferred, item[0]))
    return candidates


def open_first_camera(
    preferred: int = 0,
    width: int = 640,
    height: int = 360,
    fps: int = 60,
    limit: int = 16,
    warmup_reads: int = 5,
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

                # MJPG commonly unlocks 60 FPS at 640x360 on USB webcams while
                # keeping USB bandwidth and CPU conversion low. Unsupported
                # cameras simply ignore the request.
                try:
                    cap.set(
                        cv2.CAP_PROP_FOURCC,
                        cv2.VideoWriter_fourcc(*"MJPG"),
                    )
                except Exception:
                    pass
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
                    time.sleep(0.015)

                if good:
                    latest = LatestFrameCapture(cap)
                    deadline = time.monotonic() + 0.6
                    while time.monotonic() < deadline:
                        ok, fresh = latest.read()
                        if ok and fresh is not None:
                            return OpenedCamera(
                                cap=latest,
                                index=index,
                                source=str(source),
                            )
                        time.sleep(0.005)
                    latest.release()
                    continue

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
