from __future__ import annotations

import tempfile
from pathlib import Path

import cv2

from astra_pc.ai.agent import AstraBrain


def sample_video_frames(
    video: str | Path,
    *,
    frame_count: int = 6,
    max_width: int = 960,
) -> tuple[list[Path], tempfile.TemporaryDirectory]:
    video = Path(video)
    if not video.exists():
        raise FileNotFoundError(video)

    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        raise RuntimeError(f"Could not open video: {video}")

    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    if total <= 0:
        cap.release()
        raise RuntimeError("Video has no readable frames.")

    frame_count = max(1, min(frame_count, 12, total))
    indexes = [
        int(round(i * (total - 1) / max(1, frame_count - 1)))
        for i in range(frame_count)
    ]

    temp = tempfile.TemporaryDirectory(prefix="astra-video-")
    paths: list[Path] = []

    for n, idx in enumerate(indexes):
        cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
        ok, frame = cap.read()
        if not ok:
            continue
        h, w = frame.shape[:2]
        if w > max_width:
            scale = max_width / float(w)
            frame = cv2.resize(frame, (max_width, int(h * scale)))
        path = Path(temp.name) / f"frame-{n:02d}.jpg"
        cv2.imwrite(str(path), frame, [int(cv2.IMWRITE_JPEG_QUALITY), 82])
        paths.append(path)

    cap.release()
    return paths, temp


def understand_video(
    brain: AstraBrain,
    video: str | Path,
    prompt: str,
    *,
    frame_count: int = 6,
) -> str:
    frames, temp = sample_video_frames(video, frame_count=frame_count)
    try:
        if not frames:
            raise RuntimeError("No frames could be sampled.")
        return brain.inspect_frames(frames, prompt)
    finally:
        temp.cleanup()
