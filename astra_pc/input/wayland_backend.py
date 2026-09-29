from __future__ import annotations

import os
import queue
import shutil
import subprocess
import threading

from .base import InputBackend


_KEYCODES = {
    "esc": 1,
    "1": 2, "2": 3, "3": 4, "4": 5, "5": 6, "6": 7, "7": 8, "8": 9, "9": 10, "0": 11,
    "-": 12, "=": 13, "backspace": 14, "tab": 15,
    "q": 16, "w": 17, "e": 18, "r": 19, "t": 20, "y": 21, "u": 22, "i": 23, "o": 24, "p": 25,
    "[": 26, "]": 27, "enter": 28, "ctrl": 29,
    "a": 30, "s": 31, "d": 32, "f": 33, "g": 34, "h": 35, "j": 36, "k": 37, "l": 38,
    ";": 39, "'": 40, chr(96): 41, "shift": 42, "\\": 43,
    "z": 44, "x": 45, "c": 46, "v": 47, "b": 48, "n": 49, "m": 50,
    ",": 51, ".": 52, "/": 53, "right_shift": 54, "alt": 56, "space": 57, "caps_lock": 58,
    "f1": 59, "f2": 60, "f3": 61, "f4": 62, "f5": 63, "f6": 64,
    "f7": 65, "f8": 66, "f9": 67, "f10": 68, "num_lock": 69, "scroll_lock": 70,
    "home": 102, "up": 103, "page_up": 104, "left": 105, "right": 106,
    "end": 107, "down": 108, "page_down": 109, "insert": 110, "delete": 111,
    "f11": 87, "f12": 88, "right_ctrl": 97, "right_alt": 100,
    "win": 125, "cmd": 125, "menu": 139,
    "numpad_7": 71, "numpad_8": 72, "numpad_9": 73, "numpad_minus": 74,
    "numpad_4": 75, "numpad_5": 76, "numpad_6": 77, "numpad_plus": 78,
    "numpad_1": 79, "numpad_2": 80, "numpad_3": 81, "numpad_0": 82, "numpad_decimal": 83,
    "numpad_enter": 96, "numpad_slash": 98, "numpad_asterisk": 55,
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
        self._keys_down: set[str] = set()
        self._commands: queue.Queue[tuple[str, ...]] = queue.Queue(maxsize=64)
        self._latest_move: tuple[int, int] | None = None
        self._relative_move: tuple[int, int] = (0, 0)
        self._move_lock = threading.Lock()
        self._pending_wheel = 0
        self._wheel_lock = threading.Lock()
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

    def _take_relative_move(self) -> tuple[int, int]:
        with self._move_lock:
            move = self._relative_move
            self._relative_move = (0, 0)
            return move

    def _take_wheel(self) -> int:
        with self._wheel_lock:
            amount = int(self._pending_wheel)
            self._pending_wheel = 0
            return amount

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

            wheel = self._take_wheel()
            if wheel and not self._stop.is_set():
                wheel = max(-24, min(24, int(wheel)))
                self._execute(
                    ("mousemove", "--wheel", "--", "0", str(wheel))
                )
                did_work = True

            relative = self._take_relative_move()
            if relative != (0, 0) and not self._stop.is_set():
                self._execute(
                    ("mousemove", "--", str(relative[0]), str(relative[1]))
                )
                did_work = True

            move = self._take_move()
            if move is not None and not self._stop.is_set():
                self._execute(
                    ("mousemove", "--absolute", str(move[0]), str(move[1]))
                )
                did_work = True

            if not did_work:
                self._wake.wait(0.003)
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

    def move_relative(self, dx: int, dy: int) -> None:
        dx, dy = int(dx), int(dy)
        if not dx and not dy:
            return
        # Keep the method safe for lightweight test/compatibility stubs that
        # instantiate the backend without running __init__.
        if not hasattr(self, "_move_lock"):
            self._move_lock = threading.Lock()
        if not hasattr(self, "_relative_move"):
            self._relative_move = (0, 0)
        with self._move_lock:
            old_x, old_y = self._relative_move
            self._relative_move = (
                max(-240, min(240, old_x + dx)),
                max(-240, min(240, old_y + dy)),
            )
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
        # pointer events. Sending releases is harmless even if nothing is held.
        self._execute(("click", "0x80"))
        self._left_down = False
        held = list(getattr(self, "_keys_down", set()))
        for key in held:
            code = _KEYCODES.get(key)
            if code is not None:
                self._execute(("key", f"{code}:0"))
        self._keys_down = set()

    def scroll(self, amount: int) -> None:
        if not amount:
            return
        # Wheel events are high-frequency during hand scroll. Coalesce them in
        # memory instead of spawning one ydotool process for every video frame.
        with self._wheel_lock:
            self._pending_wheel += int(amount)
            self._pending_wheel = max(-24, min(24, self._pending_wheel))
        self._wake.set()

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

    def key_down(self, key: str) -> None:
        key = str(key).lower()
        code = _KEYCODES.get(key)
        if code is None:
            raise ValueError(f"unsupported key: {key}")
        if not hasattr(self, "_keys_down"):
            self._keys_down = set()
        if key in self._keys_down:
            return
        self._queue_command("key", f"{code}:1")
        self._keys_down.add(key)

    def key_up(self, key: str) -> None:
        key = str(key).lower()
        code = _KEYCODES.get(key)
        if code is None:
            raise ValueError(f"unsupported key: {key}")
        self._queue_command("key", f"{code}:0")
        if hasattr(self, "_keys_down"):
            self._keys_down.discard(key)

    def type_text(self, text: str) -> None:
        self._queue_command("type", "--key-delay", "3", text)
