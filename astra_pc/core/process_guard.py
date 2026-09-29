from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

import psutil

from astra_pc.paths import data_dir


_LOCK = threading.RLock()


def _state_path() -> Path:
    return data_dir() / "runtime-processes.json"


def _read_state() -> dict:
    try:
        value = json.loads(_state_path().read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def _write_state(state: dict) -> None:
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _same_process(record: dict) -> psutil.Process | None:
    try:
        pid = int(record.get("pid", 0))
        created = float(record.get("create_time", 0.0))
    except Exception:
        return None
    if pid <= 0:
        return None

    try:
        proc = psutil.Process(pid)
        actual_created = float(proc.create_time())
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        return None

    # Protect against PID reuse. We only touch the exact process Astra recorded.
    if created and abs(actual_created - created) > 1.0:
        return None
    return proc


def register_process(role: str, pid: int | None = None) -> dict:
    target_pid = int(pid or os.getpid())
    proc = psutil.Process(target_pid)
    record = {
        "pid": target_pid,
        "create_time": float(proc.create_time()),
        "registered_at": time.time(),
    }
    try:
        record["name"] = proc.name()
        record["cmdline"] = proc.cmdline()[:12]
    except (psutil.AccessDenied, psutil.ZombieProcess):
        pass

    with _LOCK:
        state = _read_state()
        state[str(role)] = record
        _write_state(state)
    return record


def unregister_process(role: str, pid: int | None = None) -> None:
    with _LOCK:
        state = _read_state()
        record = state.get(str(role))
        if not isinstance(record, dict):
            return
        if pid is not None and int(record.get("pid", -1)) != int(pid):
            return
        state.pop(str(role), None)
        _write_state(state)


def terminate_recorded_process(
    role: str,
    *,
    timeout: float = 1.5,
) -> bool:
    """Terminate one Astra-owned process tree on Linux/macOS/Windows.

    The saved process creation timestamp prevents killing a different process
    that later happened to reuse the same PID.
    """

    with _LOCK:
        state = _read_state()
        record = state.get(str(role))
        if not isinstance(record, dict):
            return False

    proc = _same_process(record)
    if proc is None:
        unregister_process(role)
        return False

    # Never terminate the caller itself.
    if proc.pid == os.getpid():
        return False

    try:
        children = proc.children(recursive=True)
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        children = []

    targets = children + [proc]
    for item in reversed(targets):
        try:
            item.terminate()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    _gone, alive = psutil.wait_procs(
        targets,
        timeout=max(0.1, float(timeout)),
    )
    for item in alive:
        try:
            item.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    unregister_process(role)
    return True


def prepare_gesture_session() -> None:
    """Ensure only one Astra-owned gesture/DroidCam session survives."""

    # Kill the old gesture process first. Its normal cleanup may stop its helper.
    terminate_recorded_process("gestures", timeout=1.2)
    # If that runtime crashed before cleanup, remove its orphan bridge too.
    terminate_recorded_process("droidcam-cli", timeout=1.2)
    register_process("gestures", os.getpid())
