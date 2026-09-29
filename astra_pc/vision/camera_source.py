from __future__ import annotations

import concurrent.futures
import glob
import ipaddress
import json
import os
import platform
import shutil
import socket
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import cv2

from astra_pc.paths import data_dir


class LatestFrameCapture:
    """Continuously consume frames and expose only the newest real frame."""

    def __init__(
        self,
        cap: cv2.VideoCapture,
        *,
        owner_process: subprocess.Popen | None = None,
    ):
        self._cap = cap
        self._owner_process = owner_process
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
            if not ok or frame is None or not getattr(frame, "size", 0):
                time.sleep(0.004)
                continue
            with self._condition:
                self._frame = frame
                self._ok = True
                self._version += 1
                self._condition.notify_all()

    def read(self):
        with self._condition:
            if self._version == self._last_read_version and not self._stop.is_set():
                self._condition.wait(timeout=0.030)
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
                self._thread.join(timeout=0.7)
            process = self._owner_process
            if process is not None and process.poll() is None:
                try:
                    process.terminate()
                    process.wait(timeout=1.0)
                except Exception:
                    try:
                        process.kill()
                    except Exception:
                        pass

    def set(self, prop, value):
        return self._cap.set(prop, value)

    def get(self, prop):
        return self._cap.get(prop)


@dataclass(slots=True)
class OpenedCamera:
    cap: LatestFrameCapture
    index: int | None
    source: str


def _state_path() -> Path:
    return data_dir() / "camera.json"


DROIDCAM_DEFAULT_PORT = 4747


def _droidcam_state_path() -> Path:
    return data_dir() / "droidcam.json"


def _load_saved_droidcam_source() -> str | None:
    try:
        value = json.loads(_droidcam_state_path().read_text(encoding="utf-8"))
        host = str(value.get("host", "")).strip()
        port = int(value.get("port", DROIDCAM_DEFAULT_PORT))
        if host and 1 <= port <= 65535:
            return f"http://{host}:{port}/video"
    except Exception:
        pass
    return None


def _parse_droidcam_endpoint(value: str | int | None) -> tuple[str, int] | None:
    if value is None or isinstance(value, int):
        return None
    text = str(value).strip()
    if not text:
        return None

    lowered = text.lower()
    if lowered.startswith("droidcam://"):
        text = text[len("droidcam://"):]
    elif lowered.startswith(("http://", "https://")):
        text = text.split("//", 1)[1]
    elif "://" in text:
        return None

    text = text.split("/", 1)[0].strip()
    if not text:
        return None

    host = text
    port = DROIDCAM_DEFAULT_PORT
    if text.count(":") == 1:
        maybe_host, maybe_port = text.rsplit(":", 1)
        if maybe_port.isdigit():
            host = maybe_host.strip()
            port = int(maybe_port)

    if not host or not (1 <= int(port) <= 65535):
        return None

    # Port 4747 is DroidCam Classic's normal endpoint. A raw private IP/IP:port
    # entered through Astra's manual camera dialog is also intentionally treated
    # as DroidCam.
    if (
        int(port) != DROIDCAM_DEFAULT_PORT
        and not lowered.startswith("droidcam://")
        and not lowered.startswith(("http://", "https://"))
    ):
        return None
    return host, int(port)


def _droidcam_cli_binary() -> Path | None:
    for candidate in (
        shutil.which("droidcam-cli"),
        "/usr/local/bin/droidcam-cli",
        "/usr/bin/droidcam-cli",
    ):
        if candidate and Path(candidate).exists():
            return Path(candidate)
    return None


def _droidcam_virtual_devices() -> list[Path]:
    if platform.system() != "Linux":
        return []

    root = Path("/sys/class/video4linux")
    if not root.exists():
        return []

    preferred: list[Path] = []
    other_virtual: list[Path] = []
    for entry in sorted(root.glob("video*")):
        device = Path("/dev") / entry.name
        if not device.exists():
            continue
        try:
            name = (entry / "name").read_text(
                encoding="utf-8",
                errors="ignore",
            ).strip().lower()
        except Exception:
            name = ""

        if "droidcam" in name:
            preferred.append(device)
        elif any(token in name for token in ("v4l2loopback", "virtual")):
            other_virtual.append(device)

    return preferred + other_virtual


def _start_droidcam_cli(
    host: str,
    port: int,
    device: Path,
) -> subprocess.Popen | None:
    cli = _droidcam_cli_binary()
    if cli is None:
        print("[camera] DROIDCAM_ERROR droidcam-cli not installed", flush=True)
        return None

    log_path = data_dir() / "droidcam-runtime.log"
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log = log_path.open("ab", buffering=0)
    except Exception:
        log = subprocess.DEVNULL

    cmd = [
        str(cli),
        "-nocontrols",
        f"-dev={device}",
        host,
        str(int(port)),
    ]
    print(
        f"[camera] DROIDCAM_CONNECT {host}:{port} -> {device}",
        flush=True,
    )
    try:
        process = subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=log,
            start_new_session=True,
        )
    except Exception as exc:
        try:
            if log is not subprocess.DEVNULL:
                log.close()
        except Exception:
            pass
        print(f"[camera] DROIDCAM_ERROR start failed: {exc}", flush=True)
        return None
    finally:
        try:
            if log is not subprocess.DEVNULL:
                log.close()
        except Exception:
            pass

    time.sleep(0.20)
    if process.poll() is not None:
        print(
            f"[camera] DROIDCAM_ERROR cli exited code={process.returncode}",
            flush=True,
        )
        return None
    return process


def _open_droidcam_via_cli(
    source: str,
    *,
    width: int,
    height: int,
    fps: int,
    timeout_seconds: float = 3.5,
) -> OpenedCamera | None:
    endpoint = _parse_droidcam_endpoint(source)
    if endpoint is None or platform.system() != "Linux":
        return None

    host, port = endpoint
    devices = _droidcam_virtual_devices()
    if not devices:
        print(
            "[camera] DROIDCAM_ERROR no V4L2 loopback/DroidCam device found",
            flush=True,
        )
        return None

    print(
        "[camera] DROIDCAM_DEVICES "
        + ",".join(str(device) for device in devices),
        flush=True,
    )
    deadline = time.monotonic() + max(0.6, float(timeout_seconds))

    for device in devices:
        if time.monotonic() >= deadline:
            break

        process = _start_droidcam_cli(host, port, device)
        if process is None:
            continue

        transferred = False
        try:
            while time.monotonic() < deadline and process.poll() is None:
                opened = _try_open_candidate(
                    str(device),
                    width=width,
                    height=height,
                    fps=fps,
                    warmup_seconds=min(
                        0.65,
                        max(0.18, deadline - time.monotonic()),
                    ),
                )
                if opened is not None:
                    # Transfer lifecycle ownership: when gestures stop, the CLI
                    # connection we created is terminated too.
                    opened.cap._owner_process = process
                    opened.source = f"droidcam://{host}:{port}"
                    transferred = True
                    print(
                        f"[camera] DROIDCAM_READY {device}",
                        flush=True,
                    )
                    return opened
                time.sleep(0.10)
        finally:
            if not transferred and process.poll() is None:
                try:
                    process.terminate()
                    process.wait(timeout=0.7)
                except Exception:
                    try:
                        process.kill()
                    except Exception:
                        pass

    print(
        "[camera] DROIDCAM_ERROR connected but virtual camera produced no frames",
        flush=True,
    )
    return None


def _local_private_hosts(max_hosts: int = 512) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()

    def add(value: str) -> None:
        if value in seen:
            return
        try:
            addr = ipaddress.IPv4Address(value)
        except ValueError:
            return
        if not addr.is_private or addr.is_loopback:
            return
        seen.add(value)
        ordered.append(value)

    if platform.system() == "Linux" and shutil.which("ip"):
        try:
            p = subprocess.run(
                ["ip", "-4", "neigh", "show"],
                capture_output=True,
                text=True,
                timeout=0.8,
                check=False,
            )
            for line in p.stdout.splitlines():
                add(line.split(" ", 1)[0].strip())
        except Exception:
            pass

    try:
        import psutil

        for _name, addresses in psutil.net_if_addrs().items():
            for item in addresses:
                if item.family != socket.AF_INET or not item.address:
                    continue
                try:
                    local = ipaddress.IPv4Address(item.address)
                    network = ipaddress.IPv4Network(
                        f"{item.address}/{item.netmask or '255.255.255.0'}",
                        strict=False,
                    )
                except ValueError:
                    continue
                if not local.is_private or local.is_loopback:
                    continue

                # Never fan out across a huge corporate/private subnet.
                if network.prefixlen < 24:
                    network = ipaddress.IPv4Network(
                        f"{local}/24",
                        strict=False,
                    )
                for addr in network.hosts():
                    if addr != local:
                        add(str(addr))
                        if len(ordered) >= max_hosts:
                            return ordered
    except Exception:
        pass

    return ordered


def discover_droidcam_source(timeout_seconds: float = 2.5) -> str | None:
    """Discover a DroidCam-compatible HTTP endpoint on the local LAN only."""

    saved = _load_saved_droidcam_source()
    if saved:
        try:
            host_port = saved.split("//", 1)[1].split("/", 1)[0]
            host, port_text = host_port.rsplit(":", 1)
            with socket.create_connection(
                (host, int(port_text)),
                timeout=0.25,
            ):
                return saved
        except Exception:
            pass

    hosts = _local_private_hosts()
    if not hosts:
        return None

    deadline = time.monotonic() + max(0.2, float(timeout_seconds))
    workers = min(64, max(8, len(hosts)))
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=workers)
    futures = {
        executor.submit(
            socket.create_connection,
            (host, DROIDCAM_DEFAULT_PORT),
            0.18,
        ): host
        for host in hosts
    }
    try:
        while futures and time.monotonic() < deadline:
            remaining = max(0.01, deadline - time.monotonic())
            done, _ = concurrent.futures.wait(
                futures,
                timeout=min(0.20, remaining),
                return_when=concurrent.futures.FIRST_COMPLETED,
            )
            if not done:
                continue
            for future in done:
                host = futures.pop(future)
                try:
                    connection = future.result()
                    connection.close()
                    for pending in futures:
                        pending.cancel()
                    return f"http://{host}:{DROIDCAM_DEFAULT_PORT}/video"
                except Exception:
                    pass
    finally:
        for future in futures:
            future.cancel()
        executor.shutdown(wait=False, cancel_futures=True)

    return None


def load_camera_state() -> dict:
    try:
        value = json.loads(_state_path().read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def save_camera_state(source: str | int, index: int | None = None) -> None:
    try:
        path = _state_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "source": str(source),
                    "index": index,
                    "last_success_at": time.time(),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    except Exception:
        pass


def _coerce_source(value: str | int | None):
    if value is None:
        return None
    if isinstance(value, int):
        return value
    text = str(value).strip()
    if not text:
        return None
    if text.isdigit():
        return int(text)
    return text


def _source_key(source: str | int) -> str:
    if isinstance(source, int):
        return f"index:{source}"
    endpoint = _parse_droidcam_endpoint(source)
    if endpoint is not None:
        return f"droidcam:{endpoint[0]}:{endpoint[1]}"
    text = str(source)
    try:
        if text.startswith("/dev/"):
            return "dev:" + str(Path(text).resolve())
    except Exception:
        pass
    return "source:" + text


def _index_for_source(source: str | int) -> int | None:
    if isinstance(source, int):
        return source
    text = str(source)
    try:
        resolved = Path(text).resolve().name
    except Exception:
        resolved = Path(text).name
    suffix = resolved.removeprefix("video")
    return int(suffix) if suffix.isdigit() else None


def candidate_cameras(
    preferred: int = 0,
    limit: int = 16,
    *,
    configured_source: str | int | None = None,
    remembered_source: str | int | None = None,
) -> list[tuple[int | None, str | int]]:
    """Return stable candidates in the order Astra should try them."""

    raw: list[str | int] = []
    for value in (
        configured_source,
        remembered_source,
        _load_saved_droidcam_source(),
    ):
        source = _coerce_source(value)
        if source is not None:
            raw.append(source)

    if platform.system() == "Linux":
        preferred_path = f"/dev/video{int(preferred)}"
        if Path(preferred_path).exists():
            raw.append(preferred_path)

        # Stable by-id paths are preferable to volatile /dev/videoN numbers.
        raw.extend(sorted(glob.glob("/dev/v4l/by-id/*-video-index0"))[:limit])
        raw.extend(sorted(glob.glob("/dev/video*"))[:limit])
    else:
        raw.extend(range(max(0, int(limit))))

    seen: set[str] = set()
    result: list[tuple[int | None, str | int]] = []
    for source in raw:
        key = _source_key(source)
        if key in seen:
            continue
        seen.add(key)
        result.append((_index_for_source(source), source))

    configured = _coerce_source(configured_source)
    remembered = _coerce_source(remembered_source)
    configured_key = _source_key(configured) if configured is not None else None
    remembered_key = _source_key(remembered) if remembered is not None else None

    result.sort(
        key=lambda item: (
            0 if configured_key and _source_key(item[1]) == configured_key else
            1 if remembered_key and _source_key(item[1]) == remembered_key else
            2 if item[0] == int(preferred) else
            3,
            item[0] if item[0] is not None else 9999,
        )
    )
    return result


def _is_local_linux_source(source: str | int) -> bool:
    if platform.system() != "Linux":
        return False
    if isinstance(source, int):
        return True
    return str(source).startswith("/dev/")


def _create_capture(source: str | int):
    if _is_local_linux_source(source):
        return cv2.VideoCapture(source, cv2.CAP_V4L2)

    text = str(source)
    if text.lower().startswith(("http://", "https://", "rtsp://", "rtmp://")):
        params = []
        if hasattr(cv2, "CAP_PROP_OPEN_TIMEOUT_MSEC"):
            params.extend([cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 1200])
        if hasattr(cv2, "CAP_PROP_READ_TIMEOUT_MSEC"):
            params.extend([cv2.CAP_PROP_READ_TIMEOUT_MSEC, 1200])
        if params and hasattr(cv2, "CAP_FFMPEG"):
            try:
                return cv2.VideoCapture(text, cv2.CAP_FFMPEG, params)
            except Exception:
                pass

    return cv2.VideoCapture(source)


def _configure_capture(
    cap,
    *,
    width: int,
    height: int,
    fps: int,
) -> None:
    try:
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    except Exception:
        pass

    # Local USB/V4L2 cameras commonly reach higher FPS with MJPG. Network
    # streams ignore this harmlessly.
    try:
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
    except Exception:
        pass

    for prop, value in (
        (cv2.CAP_PROP_FRAME_WIDTH, int(width)),
        (cv2.CAP_PROP_FRAME_HEIGHT, int(height)),
        (cv2.CAP_PROP_FPS, int(fps)),
    ):
        try:
            cap.set(prop, value)
        except Exception:
            pass


def _try_open_candidate(
    source: str | int,
    *,
    width: int,
    height: int,
    fps: int,
    warmup_seconds: float = 0.75,
) -> OpenedCamera | None:
    cap = None
    try:
        cap = _create_capture(source)
        if not cap or not cap.isOpened():
            if cap:
                cap.release()
            return None

        _configure_capture(cap, width=width, height=height, fps=fps)

        deadline = time.monotonic() + max(0.15, float(warmup_seconds))
        good_frames = 0
        while time.monotonic() < deadline:
            ok, frame = cap.read()
            if ok and frame is not None and getattr(frame, "size", 0):
                good_frames += 1
                # Two actual frames avoids accepting metadata/broken V4L nodes.
                if good_frames >= 2:
                    latest = LatestFrameCapture(cap)
                    verify_deadline = time.monotonic() + 0.7
                    while time.monotonic() < verify_deadline:
                        fresh_ok, fresh = latest.read()
                        if fresh_ok and fresh is not None and getattr(fresh, "size", 0):
                            return OpenedCamera(
                                cap=latest,
                                index=_index_for_source(source),
                                source=str(source),
                            )
                        time.sleep(0.006)
                    latest.release()
                    return None
            else:
                time.sleep(0.012)

        cap.release()
        return None
    except Exception:
        try:
            if cap is not None:
                cap.release()
        except Exception:
            pass
        return None


def open_first_camera(
    preferred: int = 0,
    width: int = 640,
    height: int = 360,
    fps: int = 60,
    limit: int = 16,
    warmup_reads: int = 5,
    *,
    configured_source: str | int | None = None,
) -> OpenedCamera | None:
    """Single-pass camera probe kept for callers/tests that need it."""

    remembered = load_camera_state().get("source")
    for _, source in candidate_cameras(
        preferred,
        limit,
        configured_source=configured_source,
        remembered_source=remembered,
    ):
        opened = _try_open_candidate(
            source,
            width=width,
            height=height,
            fps=fps,
            warmup_seconds=max(0.30, min(1.0, warmup_reads * 0.08)),
        )
        if opened is not None:
            save_camera_state(opened.source, opened.index)
            return opened
    return None


def _manual_prompt_text(previous_error: bool = False) -> str:
    lead = (
        "A fonte anterior não entregou vídeo.\n\n"
        if previous_error
        else
        "Astra não encontrou uma câmera automaticamente em 10 segundos.\n\n"
    )
    return (
        lead
        + "Digite a câmera manualmente:\n"
        + "• webcam: 0, 1, 2... ou /dev/videoX\n"
        + "• DroidCam: IP:porta (ex. 192.168.1.50:4747)\n"
        + "• câmera IP genérica: URL HTTP/RTSP\n\n"
        + "Cancelar deixa os gestos desligados."
    )


def request_manual_camera_source(*, previous_error: bool = False) -> str | int | None:
    """Ask for a camera source without depending on Astra's frontend."""

    env_source = _coerce_source(os.getenv("ASTRA_CAMERA_SOURCE"))
    if env_source is not None:
        return env_source

    prompt = _manual_prompt_text(previous_error)
    system = platform.system()

    if system == "Linux" and (os.getenv("DISPLAY") or os.getenv("WAYLAND_DISPLAY")):
        kdialog = shutil.which("kdialog")
        if kdialog:
            try:
                p = subprocess.run(
                    [
                        kdialog,
                        "--title",
                        "Astra · Câmera",
                        "--inputbox",
                        prompt,
                        "192.168.1.50:4747",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=180,
                    check=False,
                )
                if p.returncode == 0:
                    return _coerce_source(p.stdout.strip())
                return None
            except Exception:
                pass

        zenity = shutil.which("zenity")
        if zenity:
            try:
                p = subprocess.run(
                    [
                        zenity,
                        "--entry",
                        "--title=Astra · Câmera",
                        "--text=" + prompt,
                        "--entry-text=192.168.1.50:4747",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=180,
                    check=False,
                )
                if p.returncode == 0:
                    return _coerce_source(p.stdout.strip())
                return None
            except Exception:
                pass

    if system == "Windows":
        powershell = shutil.which("powershell") or shutil.which("pwsh")
        if powershell:
            try:
                escaped = prompt.replace("'", "''")
                script = (
                    "Add-Type -AssemblyName Microsoft.VisualBasic; "
                    "$v=[Microsoft.VisualBasic.Interaction]::InputBox("
                    f"'{escaped}','Astra - Camera','0'); "
                    "Write-Output $v"
                )
                p = subprocess.run(
                    [powershell, "-NoProfile", "-Command", script],
                    capture_output=True,
                    text=True,
                    timeout=180,
                    check=False,
                )
                return _coerce_source(p.stdout.strip()) if p.returncode == 0 else None
            except Exception:
                pass

    if system == "Darwin" and shutil.which("osascript"):
        try:
            safe = prompt.replace('"', r'\"')
            script = (
                'text returned of (display dialog "'
                + safe
                + '" default answer "0" with title "Astra · Câmera")'
            )
            p = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                text=True,
                timeout=180,
                check=False,
            )
            return _coerce_source(p.stdout.strip()) if p.returncode == 0 else None
        except Exception:
            pass

    if sys.stdin is not None and sys.stdin.isatty():
        try:
            print("\n" + prompt)
            return _coerce_source(input("Câmera: ").strip())
        except (EOFError, KeyboardInterrupt):
            return None

    return None


def open_camera_resilient(
    preferred: int = 0,
    width: int = 640,
    height: int = 360,
    fps: int = 60,
    limit: int = 16,
    *,
    configured_source: str | int | None = None,
    auto_timeout: float = 10.0,
    manual_fallback: bool = True,
) -> OpenedCamera | None:
    """Find a working camera, retrying hotplug/startup for up to 10 seconds.

    Order:
      1. explicit/configured source
      2. last known working source
      3. stable Linux /dev/v4l/by-id source
      4. local camera indexes
      5. native manual dialog after the automatic deadline
    """

    state = load_camera_state()
    remembered = state.get("source")
    deadline = time.monotonic() + max(0.0, float(auto_timeout))
    pass_number = 0
    last_reported_second = None
    droidcam_scanned = False

    previous_level = None
    try:
        if hasattr(cv2, "getLogLevel") and hasattr(cv2, "setLogLevel"):
            previous_level = cv2.getLogLevel()
            cv2.setLogLevel(0)
    except Exception:
        previous_level = None

    try:
        print(
            f"[camera] AUTO_SEARCH timeout={float(auto_timeout):.0f}s",
            flush=True,
        )

        while time.monotonic() < deadline:
            pass_number += 1
            remaining = max(0.0, deadline - time.monotonic())
            elapsed = max(0.0, float(auto_timeout) - remaining)
            second = int(elapsed)
            if second != last_reported_second:
                last_reported_second = second
                print(
                    f"[camera] searching {min(int(auto_timeout), second)}/{int(auto_timeout)}s",
                    flush=True,
                )

            candidates = candidate_cameras(
                preferred,
                limit,
                configured_source=configured_source,
                remembered_source=remembered,
            )
            for _, source in candidates:
                if time.monotonic() >= deadline:
                    break

                droidcam_endpoint = _parse_droidcam_endpoint(source)
                if droidcam_endpoint is not None and platform.system() == "Linux":
                    opened = _open_droidcam_via_cli(
                        str(source),
                        width=width,
                        height=height,
                        fps=fps,
                        timeout_seconds=min(
                            3.5,
                            max(0.5, deadline - time.monotonic()),
                        ),
                    )
                else:
                    # Give remembered/configured sources more warmup time; new
                    # local devices still get retried on the next scan pass.
                    important = (
                        _source_key(source) == _source_key(_coerce_source(configured_source))
                        or _source_key(source) == _source_key(_coerce_source(remembered))
                    )
                    opened = _try_open_candidate(
                        source,
                        width=width,
                        height=height,
                        fps=fps,
                        warmup_seconds=0.95 if important else 0.45,
                    )
                if opened is not None:
                    save_camera_state(opened.source, opened.index)
                    print(
                        f"[camera] AUTO_FOUND source={opened.source}",
                        flush=True,
                    )
                    return opened

            if not droidcam_scanned and time.monotonic() < deadline:
                droidcam_scanned = True
                remaining = max(0.0, deadline - time.monotonic())
                print("[camera] searching DroidCam on local LAN", flush=True)
                droidcam_source = discover_droidcam_source(
                    timeout_seconds=min(2.5, remaining)
                )
                if droidcam_source and time.monotonic() < deadline:
                    endpoint = _parse_droidcam_endpoint(droidcam_source)
                    if endpoint is not None:
                        host, port = endpoint
                        source = f"droidcam://{host}:{port}"
                        opened = _open_droidcam_via_cli(
                            source,
                            width=width,
                            height=height,
                            fps=fps,
                            timeout_seconds=min(
                                3.5,
                                max(0.5, deadline - time.monotonic()),
                            ),
                        )
                        if opened is not None:
                            save_camera_state(opened.source, opened.index)
                            print(
                                f"[camera] AUTO_FOUND DroidCam={opened.source}",
                                flush=True,
                            )
                            return opened

            if time.monotonic() < deadline:
                time.sleep(min(0.25, max(0.01, deadline - time.monotonic())))

        print("[camera] AUTO_TIMEOUT", flush=True)

        if not manual_fallback:
            return None

        previous_error = False
        while True:
            print("[camera] MANUAL_REQUIRED", flush=True)
            source = request_manual_camera_source(previous_error=previous_error)
            if source is None:
                print("[camera] MANUAL_CANCELLED", flush=True)
                return None

            print(f"[camera] manual probe: {source}", flush=True)
            if (
                _parse_droidcam_endpoint(source) is not None
                and platform.system() == "Linux"
            ):
                opened = _open_droidcam_via_cli(
                    str(source),
                    width=width,
                    height=height,
                    fps=fps,
                    timeout_seconds=5.0,
                )
            else:
                opened = _try_open_candidate(
                    source,
                    width=width,
                    height=height,
                    fps=fps,
                    warmup_seconds=2.0,
                )
            if opened is not None:
                save_camera_state(opened.source, opened.index)
                print(
                    f"[camera] MANUAL_FOUND source={opened.source}",
                    flush=True,
                )
                return opened

            previous_error = True
            print(
                f"[camera] manual source failed: {source}",
                flush=True,
            )
    finally:
        if previous_level is not None:
            try:
                cv2.setLogLevel(previous_level)
            except Exception:
                pass
