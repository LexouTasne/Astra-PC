from __future__ import annotations

import os
import queue
import shutil
import subprocess
import threading

from .base import InputBackend


_KEYCODES = {
    "ctrl": 29,
    "shift": 42,
    "alt": 56,
    "win": 125,
    "tab": 15,
    "enter": 28,
    "esc": 1,
    "space": 57,
    "backspace": 14,
    "delete": 111,
    "up": 103,
    "down": 108,
    "left": 105,
    "right": 106,
    "+": 13,
    "-": 12,
    "[": 26,
    "]": 27,
}


class YdotoolBackend(InputBackend):
    """Wayland input through ydotoold with a non-blocking/coalesced worker.

    The realtime hand-tracking loop must never wait for a subprocess. Pointer
    moves are coalesced so a slow ydotool invocation cannot build a huge queue.
    """

    def __init__(self):
        binary = shutil.which("ydotool")
        if not binary:
            raise RuntimeError("ydotool is required for native Wayland input")
        self.binary = binary
        self._left_down = False
        self._commands: queue.Queue[tuple[str, ...]] = queue.Queue(maxsize=64)
        self._latest_move: tuple[int, int] | None = None
        self._move_lock = threading.Lock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._last_error = ""
        self._env = os.environ.copy()
        self._socket = self._discover_socket()
        self._worker = threading.Thread(
            target=self._run_worker,
            name="astra-ydotool",
            daemon=True,
        )
        self._worker.start()

    def _discover_socket(self) -> str:
        candidates: list[str] = []
        explicit = os.getenv("YDOTOOL_SOCKET")
        runtime = os.getenv("XDG_RUNTIME_DIR")
        if explicit:
            candidates.append(explicit)
        if runtime:
            candidates.append(str(os.path.join(runtime, ".ydotool_socket")))
        candidates.append("/tmp/.ydotool_socket")

        last_detail = "ydotoold unavailable"
        seen = set()
        for socket_path in candidates:
            if socket_path in seen:
                continue
            seen.add(socket_path)
            env = os.environ.copy()
            env["YDOTOOL_SOCKET"] = socket_path
            try:
                probe = subprocess.run(
                    [self.binary, "debug"],
                    capture_output=True,
                    text=True,
                    timeout=1.5,
                    check=False,
                    env=env,
                )
            except Exception as exc:
                last_detail = str(exc)
                continue
            if probe.returncode == 0:
                self._env = env
                os.environ["YDOTOOL_SOCKET"] = socket_path
                print(f"[input] ydotool socket: {socket_path}")
                return socket_path
            last_detail = (
                probe.stderr or probe.stdout or "ydotoold unavailable"
            ).strip()

        raise RuntimeError(last_detail)

    def health(self) -> tuple[bool, str]:
        if self._last_error:
            return False, self._last_error
        return True, f"ydotool ready ({self.binary}, socket={self._socket})"

    def close(self) -> None:
        try:
            if self._left_down:
                self.left_button(False)
        except Exception:
            pass
        self._stop.set()
        self._wake.set()
        if hasattr(self, "_worker"):
            self._worker.join(timeout=1.0)

    def _execute(self, args: tuple[str, ...]) -> None:
        try:
            p = subprocess.run(
                [self.binary, *args],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
                timeout=1.5,
                env=self._env,
            )
            if p.returncode != 0:
                self._last_error = (p.stderr or "ydotool command failed").strip()
        except Exception as exc:
            self._last_error = str(exc)

    def _take_move(self) -> tuple[int, int] | None:
        with self._move_lock:
            move = self._latest_move
            self._latest_move = None
            return move

    def _queue_command(self, *args: str) -> None:
        move = self._take_move()
        if move is not None:
            try:
                self._commands.put_nowait(
                    ("mousemove", "--absolute", str(move[0]), str(move[1]))
                )
            except queue.Full:
                pass
        try:
            self._commands.put_nowait(tuple(args))
        except queue.Full:
            self._last_error = "ydotool command queue saturated"
        self._wake.set()

    def _run_worker(self) -> None:
        while not self._stop.is_set():
            did_work = False
            while not self._stop.is_set():
                try:
                    command = self._commands.get_nowait()
                except queue.Empty:
                    break
                self._execute(command)
                did_work = True

            move = self._take_move()
            if move is not None and not self._stop.is_set():
                self._execute(
                    ("mousemove", "--absolute", str(move[0]), str(move[1]))
                )
                did_work = True

            if not did_work:
                self._wake.wait(0.008)
                self._wake.clear()

    def screen_size(self) -> tuple[int, int]:
        raw = os.getenv("ASTRA_SCREEN_SIZE", "1920x1080").lower().split("x", 1)
        try:
            return int(raw[0]), int(raw[1])
        except Exception:
            return (1920, 1080)

    def move(self, x: int, y: int) -> None:
        with self._move_lock:
            self._latest_move = (int(x), int(y))
        self._wake.set()

    def left_button(self, down: bool) -> None:
        if down == self._left_down:
            return
        self._queue_command("click", "0x40" if down else "0x80")
        self._left_down = down

    def left_click(self) -> None:
        # Atomic left click: down+up in one ydotool command. This avoids a
        # persistent drag state when tracking is lost between separate events.
        self._queue_command("click", "0xC0")
        self._left_down = False

    def right_click(self) -> None:
        self._queue_command("click", "0xC1")

    def failsafe_release(self) -> None:
        # Bypass the async queue so emergency release is not stuck behind stale
        # pointer events. Sending left-up is harmless even if nothing is held.
        self._execute(("click", "0x80"))
        self._left_down = False

    def scroll(self, amount: int) -> None:
        if amount:
            self._queue_command(
                "mousemove",
                "--wheel",
                "0",
                str(int(amount)),
            )

    def hotkey(self, keys: list[str]) -> None:
        sequence = []
        for key in keys:
            code = _KEYCODES.get(key.lower())
            if code is None:
                return
            sequence.append(f"{code}:1")
        for key in reversed(keys):
            code = _KEYCODES.get(key.lower())
            if code is not None:
                sequence.append(f"{code}:0")
        if sequence:
            self._queue_command("key", *sequence)

    def type_text(self, text: str) -> None:
        self._queue_command("type", "--key-delay", "3", text)
