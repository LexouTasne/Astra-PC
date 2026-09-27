#!/usr/bin/env python3
from __future__ import annotations

import argparse
import glob
import importlib.util
import os
import platform
import shutil
import shlex
import socket
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
import time
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parent
RUNTIME_PYTHON = "3.12"
SUPPORTED_PYTHON_MIN = (3, 11)
SUPPORTED_PYTHON_MAX = (3, 13)
BOOTSTRAP_ENV = "ASTRA_MANAGED_RUNTIME"


@dataclass(slots=True)
class Check:
    name: str
    ok: bool
    detail: str
    required: bool = True


def banner() -> None:
    print("=" * 68)
    print(" ASTRA-PC 0.8 MESH INSTALLER / DIAGNOSTIC")
    print("=" * 68)
    print("Distributed Astra: desktop + Android + secure local Mesh + local AI.\n")


def ask(question: str, default: bool = True, assume_yes: bool = False) -> bool:
    if assume_yes:
        print(f"{question} -> yes (--yes)")
        return True
    suffix = " [Y/n] " if default else " [y/N] "
    answer = input(question + suffix).strip().lower()
    if not answer:
        return default
    return answer in {"y", "yes", "s", "sim"}


def run(cmd: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess:
    print("  $", " ".join(cmd))
    return subprocess.run(cmd, check=False, cwd=str(cwd) if cwd else None)


def command_exists(name: str) -> bool:
    return shutil.which(name) is not None


def download_file(url: str, target: Path, timeout: int = 30) -> bool:
    target.parent.mkdir(parents=True, exist_ok=True)

    if command_exists("curl"):
        p = subprocess.run(
            ["curl", "-fL", "--retry", "3", "--connect-timeout", "10", "-o", str(target), url],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if p.returncode == 0 and target.exists():
            return True

    if command_exists("wget"):
        p = subprocess.run(
            ["wget", "-q", "--timeout", str(timeout), "-O", str(target), url],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if p.returncode == 0 and target.exists():
            return True

    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Astra-PC/0.8 (+https://github.com/LexouTasne/Astra-PC)"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as response:
            target.write_bytes(response.read())
        return target.exists()
    except Exception as exc:
        print(f"Download failed: {url}: {exc}")
        return False


def runtime_supported() -> bool:
    return SUPPORTED_PYTHON_MIN <= sys.version_info[:2] < SUPPORTED_PYTHON_MAX


def venv_python() -> Path:
    if platform.system() == "Windows":
        return ROOT / ".venv" / "Scripts" / "python.exe"
    return ROOT / ".venv" / "bin" / "python"


def find_uv() -> str | None:
    direct = shutil.which("uv")
    if direct:
        return direct
    candidates = [
        Path.home() / ".local" / "bin" / ("uv.exe" if platform.system() == "Windows" else "uv"),
        Path.home() / ".cargo" / "bin" / ("uv.exe" if platform.system() == "Windows" else "uv"),
    ]
    if platform.system() == "Windows":
        local = os.getenv("LOCALAPPDATA")
        if local:
            candidates.append(Path(local) / "Programs" / "uv" / "uv.exe")
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return None


def install_uv() -> str | None:
    existing = find_uv()
    if existing:
        return existing

    print("\n[PYTHON RUNTIME] Installing uv in user space...")
    try:
        if platform.system() == "Windows":
            ps = shutil.which("powershell") or shutil.which("pwsh")
            if not ps:
                print("PowerShell was not found, so uv cannot be bootstrapped automatically.")
                return None
            command = (
                "$ErrorActionPreference='Stop'; "
                "irm https://astral.sh/uv/install.ps1 | iex"
            )
            result = run([ps, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command])
        else:
            with tempfile.TemporaryDirectory(prefix="astra-uv-") as td:
                script = Path(td) / "uv-install.sh"
                if not download_file("https://astral.sh/uv/install.sh", script):
                    return None
                script.chmod(script.stat().st_mode | 0o111)
                result = run(["sh", str(script)])
        if result.returncode != 0:
            return None
    except Exception as exc:
        print("Could not install uv:", exc)
        return None

    return find_uv()


def uv_install_into(
    python_exe: str | Path,
    *packages: str,
) -> bool:
    """Install packages into an interpreter without requiring pip inside it."""
    uv = find_uv() or install_uv()
    if uv:
        return run([
            uv,
            "pip",
            "install",
            "--python",
            str(python_exe),
            *packages,
        ]).returncode == 0

    # Last-resort fallback for environments where uv cannot be installed.
    probe = subprocess.run(
        [str(python_exe), "-m", "pip", "--version"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if probe.returncode != 0:
        seed = subprocess.run(
            [str(python_exe), "-m", "ensurepip", "--upgrade"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        if seed.returncode != 0:
            print("Neither uv nor pip/ensurepip is available for:", python_exe)
            return False

    return run([
        str(python_exe),
        "-m",
        "pip",
        "install",
        *packages,
    ]).returncode == 0


def ensure_seed_packages(python_exe: str | Path) -> bool:
    """Repair old uv-created virtualenvs that were created without pip."""
    probe = subprocess.run(
        [str(python_exe), "-m", "pip", "--version"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if probe.returncode == 0:
        return True

    print("[PYTHON RUNTIME] Existing .venv has no pip; repairing it...")
    return uv_install_into(
        python_exe,
        "pip",
        "setuptools",
        "wheel",
    )


def ensure_runtime(assume_yes: bool = False) -> None:
    if runtime_supported():
        return

    managed = venv_python()
    print("\n" + "=" * 68)
    print(" PYTHON COMPATIBILITY")
    print("=" * 68)
    print(f"System Python: {platform.python_version()}")
    print(f"Astra's tested runtime: Python {RUNTIME_PYTHON}")
    print("Your system Python will NOT be replaced or modified.")
    print("Astra can create its own .venv with a managed Python automatically.")

    if os.getenv(BOOTSTRAP_ENV) == "1":
        raise SystemExit(
            "Managed Astra runtime is still incompatible. "
            "Delete .venv and rerun the installer."
        )

    if not ask(
        f"Create/use Astra's isolated Python {RUNTIME_PYTHON} runtime?",
        True,
        assume_yes,
    ):
        raise SystemExit(2)

    uv = find_uv() or install_uv()
    if not uv:
        print("\nCould not provision a compatible Python automatically.")
        print("Install uv manually, then rerun installer.py.")
        raise SystemExit(2)

    print(f"\n[PYTHON RUNTIME] Ensuring isolated Python {RUNTIME_PYTHON}...")
    print("uv will reuse an existing compatible interpreter or download one if needed.")

    needs_create = True
    if managed.exists():
        probe = subprocess.run(
            [str(managed), "-c", "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"],
            capture_output=True,
            text=True,
            check=False,
        )
        needs_create = probe.stdout.strip() != RUNTIME_PYTHON

    if needs_create:
        print("[PYTHON RUNTIME] Creating isolated .venv...")
        result = run([
            uv,
            "venv",
            "--clear",
            "--seed",
            "--python",
            RUNTIME_PYTHON,
            str(ROOT / ".venv"),
        ])
        if result.returncode != 0 or not managed.exists():
            raise SystemExit("Could not create Astra's managed .venv.")

    if not ensure_seed_packages(managed):
        raise SystemExit(
            "Astra created/found Python 3.12, but could not prepare package installation."
        )

    env = os.environ.copy()
    env[BOOTSTRAP_ENV] = "1"
    print(f"\n[PYTHON RUNTIME] Relaunching installer with {managed}")
    child = subprocess.run(
        [str(managed), str(ROOT / "installer.py"), *sys.argv[1:]],
        cwd=str(ROOT),
        env=env,
        check=False,
    )
    raise SystemExit(child.returncode)


def detect_session() -> str:
    if platform.system() != "Linux":
        return platform.system()
    if os.getenv("WAYLAND_DISPLAY"):
        return "Wayland"
    if os.getenv("DISPLAY"):
        return "X11"
    return os.getenv("XDG_SESSION_TYPE", "unknown")


def linux_os_release() -> dict[str, str]:
    path = Path("/etc/os-release")
    if not path.exists():
        return {}
    data: dict[str, str] = {}
    try:
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            if "=" not in line or line.lstrip().startswith("#"):
                continue
            key, value = line.split("=", 1)
            data[key] = value.strip().strip('"')
    except Exception:
        return {}
    return data


def is_immutable_linux() -> bool:
    if platform.system() != "Linux":
        return False
    info = linux_os_release()
    image = " ".join([
        info.get("ID", ""),
        info.get("VARIANT_ID", ""),
        info.get("PRETTY_NAME", ""),
        info.get("IMAGE_ID", ""),
    ]).lower()
    return command_exists("rpm-ostree") or any(
        name in image for name in ("bazzite", "silverblue", "kinoite", "ublue", "atomic")
    )


def detect_package_manager() -> str | None:
    if platform.system() == "Windows":
        return "winget" if command_exists("winget") else None
    if platform.system() == "Darwin":
        return "brew" if command_exists("brew") else None
    for name in ("rpm-ostree", "dnf", "apt", "pacman", "zypper", "brew"):
        if command_exists(name):
            return name
    return None


def basic_camera_candidates() -> list[str]:
    system = platform.system()
    if system == "Linux":
        return sorted(glob.glob("/dev/video*"))

    if system == "Windows":
        ps = shutil.which("powershell") or shutil.which("pwsh")
        if ps:
            cmd = [
                ps,
                "-NoProfile",
                "-Command",
                "Get-PnpDevice -PresentOnly | Where-Object { "
                "$_.Class -eq 'Camera' -or $_.FriendlyName -match 'camera|webcam|droidcam' "
                "} | Select-Object -ExpandProperty FriendlyName",
            ]
            p = subprocess.run(cmd, capture_output=True, text=True)
            return [x.strip() for x in p.stdout.splitlines() if x.strip()]

    return []


def probe_cameras_opencv(limit: int = 8) -> list[tuple[int, int, int]]:
    if importlib.util.find_spec("cv2") is None:
        return []

    import cv2

    # OpenCV can print several backend errors for every invalid index.
    # Keep diagnostics readable while we probe.
    previous_level = None
    try:
        if hasattr(cv2, "getLogLevel") and hasattr(cv2, "setLogLevel"):
            previous_level = cv2.getLogLevel()
            cv2.setLogLevel(0)
    except Exception:
        previous_level = None

    if platform.system() == "Linux":
        candidates: list[tuple[int, str | int]] = []
        for path in sorted(glob.glob("/dev/video*"))[:limit]:
            name = Path(path).name
            suffix = name.removeprefix("video")
            if suffix.isdigit():
                candidates.append((int(suffix), path))
    else:
        candidates = [(index, index) for index in range(limit)]

    found: list[tuple[int, int, int]] = []
    try:
        for index, source in candidates:
            try:
                if platform.system() == "Linux":
                    cap = cv2.VideoCapture(source, cv2.CAP_V4L2)
                else:
                    cap = cv2.VideoCapture(source)
            except Exception:
                continue
            try:
                if not cap.isOpened():
                    continue
                ok, frame = cap.read()
                if ok and frame is not None and getattr(frame, "size", 0):
                    h, w = frame.shape[:2]
                    found.append((index, w, h))
            finally:
                cap.release()
    finally:
        if previous_level is not None:
            try:
                cv2.setLogLevel(previous_level)
            except Exception:
                pass

    return found


def probe_microphones() -> list[str]:
    if importlib.util.find_spec("sounddevice") is None:
        return []

    try:
        import sounddevice as sd

        result = []
        for dev in sd.query_devices():
            if int(dev.get("max_input_channels", 0)) > 0:
                result.append(str(dev.get("name", "microphone")))
        return result
    except Exception:
        return []


def gesture_platform_supported() -> tuple[bool, str]:
    system = platform.system()
    machine = platform.machine().lower()

    if system == "Windows" and machine in {"amd64", "x86_64", "arm64", "aarch64"}:
        return True, f"{system}/{machine}"
    if system == "Linux":
        libc = (platform.libc_ver()[0] or "").lower()
        if machine in {"x86_64", "amd64", "aarch64", "arm64"} and libc in {"glibc", "gnu libc", ""}:
            return True, f"{system}/{machine}"
        return False, f"{system}/{machine} libc={libc or 'unknown'}"
    if system == "Darwin" and machine in {"arm64", "aarch64"}:
        return True, "macOS Apple Silicon"
    return False, f"{system}/{machine}"


def install_python_core() -> bool:
    gestures_ok, platform_detail = gesture_platform_supported()
    print("\n[CORE] Astra Python environment:")
    print("  OpenCV    -> screen/video/camera processing")
    print("  pynput    -> mouse/keyboard on supported desktop sessions")
    print("  NumPy     -> low-overhead numeric processing")
    print("  MediaPipe -> gesture/pose tracking when a compatible wheel exists")
    print("  platform  ->", platform_detail)

    target = f"{ROOT}[gesture,mesh]" if gestures_ok else f"{ROOT}[mesh]"
    print("  Astra Mesh -> TLS/WebSocket/mDNS connection between PCs and Android")
    if not gestures_ok:
        print("  gesture engine: unavailable on this platform; installing the rest of Astra.")

    return uv_install_into(sys.executable, "-e", target)


def ollama_api_available() -> bool:
    try:
        with urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=2) as r:
            return r.status == 200
    except Exception:
        return False


def install_ollama() -> bool:
    if command_exists("ollama"):
        print("Ollama already installed.")
        return True

    system = platform.system()
    print("\n[LOCAL AI] Ollama runs Astra's local Qwen models.")
    print("No API key or cloud account is required.")

    if system == "Windows":
        if command_exists("winget"):
            return run([
                "winget", "install", "--id", "Ollama.Ollama", "--exact",
                "--accept-source-agreements", "--accept-package-agreements"
            ]).returncode == 0
        print("winget was not found.")
        print("Install Ollama manually from the official website and rerun Astra.")
        return False

    if system == "Darwin":
        if command_exists("brew"):
            return run(["brew", "install", "ollama"]).returncode == 0
        print("Homebrew was not found. Install Homebrew/Ollama, then rerun Astra.")
        return False

    if system == "Linux":
        # Bazzite/Atomic: prefer user-space Homebrew instead of modifying /usr.
        if is_immutable_linux() and command_exists("brew"):
            print("Immutable Linux detected; using Homebrew for Ollama.")
            return run(["brew", "install", "ollama"]).returncode == 0

        print("Downloading the current official Ollama installer script.")
        with tempfile.TemporaryDirectory(prefix="astra-ollama-") as td:
            script = Path(td) / "install.sh"
            try:
                if not download_file("https://ollama.com/install.sh", script):
                    return False
            except Exception as exc:
                print("Could not download Ollama installer:", exc)
                return False
            script.chmod(script.stat().st_mode | 0o111)
            return run(["sh", str(script)]).returncode == 0

    print("Automatic Ollama installation is unavailable on this platform.")
    return False


def start_ollama() -> bool:
    if ollama_api_available():
        return True
    if not command_exists("ollama"):
        return False

    if platform.system() == "Linux" and command_exists("systemctl") and not is_immutable_linux():
        run(["sudo", "systemctl", "enable", "--now", "ollama"])
        if ollama_api_available():
            return True

    if command_exists("brew"):
        owned_by_brew = subprocess.run(
            ["brew", "list", "--formula", "ollama"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        ).returncode == 0
        if owned_by_brew:
            run(["brew", "services", "start", "ollama"])
            for _ in range(8):
                if ollama_api_available():
                    return True
                time.sleep(0.25)

    print("Starting local Ollama server...")
    try:
        subprocess.Popen(
            ["ollama", "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except Exception as exc:
        print("Could not start Ollama:", exc)
        return False

    for _ in range(20):
        if ollama_api_available():
            return True
        time.sleep(0.25)
    return False


def ensure_astra_models() -> bool:
    if not command_exists("ollama"):
        return False
    if not start_ollama():
        print("Ollama was installed but its local service is not reachable yet.")
        return False

    models = [
        ("qwen3:0.6b", "fast text/voice brain", "~523 MB"),
        ("qwen3-vl:2b-instruct", "vision/screen/video brain", "~1.9 GB"),
        ("qwen3-embedding:0.6b", "semantic memory embeddings", "~639 MB"),
    ]

    listed = subprocess.run(
        ["ollama", "list"],
        capture_output=True,
        text=True,
        check=False,
    ).stdout

    ok = True
    for model, role, size in models:
        print(f"\n[LOCAL AI] {model}")
        print(f"  role: {role}")
        print(f"  size: {size}")
        if model in listed:
            print("  already installed")
            continue
        print("  downloading once...")
        if run(["ollama", "pull", model]).returncode != 0:
            ok = False
    return ok

def comfyui_available() -> bool:
    try:
        with urllib.request.urlopen("http://127.0.0.1:8188/system_stats", timeout=2) as r:
            return r.status == 200
    except Exception:
        return False


def comfyui_location() -> Path:
    if platform.system() == "Windows":
        base = Path(os.getenv("LOCALAPPDATA", Path.home()))
        return base / "Astra-PC" / "ComfyUI"
    return Path.home() / ".local" / "share" / "astra-pc" / "ComfyUI"


def install_comfyui() -> bool:
    target = comfyui_location()
    print("\n[MEDIA GENERATION] ComfyUI is optional and runs locally.")
    print("It is kept separate from the gesture engine because diffusion/video models")
    print("are much heavier than Astra's 2B vision model.")
    if not command_exists("git"):
        print("git is required to set up ComfyUI automatically.")
        return False

    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        if run(["git", "clone", "--depth", "1", "https://github.com/comfyanonymous/ComfyUI.git", str(target)]).returncode != 0:
            return False

    venv = target / ".venv"
    comfy_python = venv / (
        "Scripts/python.exe" if platform.system() == "Windows" else "bin/python"
    )
    uv = find_uv() or install_uv()
    if not comfy_python.exists():
        if uv:
            if run([
                uv,
                "venv",
                "--seed",
                "--python",
                str(sys.executable),
                str(venv),
            ]).returncode != 0:
                return False
        elif run([sys.executable, "-m", "venv", str(venv)]).returncode != 0:
            return False

    print("Installing ComfyUI Python dependencies. This optional step can be large.")
    if not uv_install_into(
        comfy_python,
        "-r",
        str(target / "requirements.txt"),
    ):
        return False

    print("ComfyUI installed at:", target)
    print("No diffusion/video checkpoint is bundled by Astra.")
    print("Put a compatible model in ComfyUI/models/checkpoints and set")
    print("media.comfyui.checkpoint in config/astra.json.")
    return True


def install_accessibility_support() -> bool:
    print("\n[ACCESSIBILITY] Structural UI understanding:")
    if platform.system() == "Windows":
        print("  pywinauto/UI Automation -> buttons, fields, windows and controls")
        return uv_install_into(
            sys.executable,
            "-e",
            f"{ROOT}[accessibility]",
        )

    if platform.system() == "Linux":
        if importlib.util.find_spec("pyatspi"):
            print("  AT-SPI Python bindings already available.")
            return True
        print("  Linux uses AT-SPI when pyatspi is available.")
        print("  Astra will still work with visual fallback if AT-SPI bindings are unavailable.")
        pm = detect_package_manager()
        if pm == "dnf":
            run(["sudo", "dnf", "install", "-y", "python3-pyatspi"])
        elif pm == "apt":
            run(["sudo", "apt", "install", "-y", "python3-pyatspi"])
        elif pm == "pacman":
            run(["sudo", "pacman", "-S", "--needed", "--noconfirm", "python-pyatspi"])
        elif pm == "zypper":
            run(["sudo", "zypper", "--non-interactive", "install", "python3-pyatspi"])
        return importlib.util.find_spec("pyatspi") is not None

    return False


def install_user_launcher() -> Path | None:
    if platform.system() == "Windows":
        base = Path(os.getenv("LOCALAPPDATA", Path.home())) / "Astra-PC" / "bin"
        base.mkdir(parents=True, exist_ok=True)
        launcher = base / "astra.cmd"
        launcher.write_text(
            "@echo off\r\n"
            f'"{sys.executable}" -m astra_pc %*\r\n',
            encoding="utf-8",
        )
        ps = shutil.which("powershell") or shutil.which("pwsh")
        if ps:
            script = (
                f"$p='{str(base).replace(chr(39), chr(39)*2)}'; "
                "$old=[Environment]::GetEnvironmentVariable('Path','User'); "
                "if (-not (($old -split ';') -contains $p)) { "
                "[Environment]::SetEnvironmentVariable('Path', "
                "($old.TrimEnd(';') + ';' + $p), 'User') }"
            )
            run([ps, "-NoProfile", "-Command", script])
        print("Astra launcher:", launcher)
        print("Open a new terminal if the 'astra' command is not visible yet.")
        return launcher

    base = Path.home() / ".local" / "bin"
    base.mkdir(parents=True, exist_ok=True)
    launcher = base / "astra"
    launcher.write_text(
        "#!/usr/bin/env sh\n"
        f"exec {shlex.quote(str(sys.executable))} -m astra_pc \"$@\"\n",
        encoding="utf-8",
    )
    launcher.chmod(0o755)
    print("Astra launcher:", launcher)
    if str(base) not in os.getenv("PATH", "").split(os.pathsep):
        print(f"NOTE: add {base} to PATH to run 'astra' from any terminal.")
    return launcher


def install_autostart(with_voice: bool = True) -> bool:
    args = ["-m", "astra_pc", "daemon"]
    if with_voice:
        args.append("--voice")

    if platform.system() == "Linux":
        service_dir = Path.home() / ".config" / "systemd" / "user"
        service_dir.mkdir(parents=True, exist_ok=True)
        service = service_dir / "astra-pc.service"
        command = " ".join([str(sys.executable), *args])
        service.write_text(
            "[Unit]\n"
            "Description=Astra-PC resident local assistant\n"
            "After=graphical-session.target network.target\n\n"
            "[Service]\n"
            "Type=simple\n"
            f"WorkingDirectory={ROOT}\n"
            f"ExecStart={command}\n"
            "Restart=on-failure\n"
            "RestartSec=2\n"
            "Environment=PYTHONUNBUFFERED=1\n\n"
            "[Install]\n"
            "WantedBy=default.target\n",
            encoding="utf-8",
        )
        if not command_exists("systemctl"):
            print("systemctl was not found; service file was written but not enabled.")
            return False
        run(["systemctl", "--user", "daemon-reload"])
        return run(["systemctl", "--user", "enable", "--now", "astra-pc.service"]).returncode == 0

    if platform.system() == "Windows":
        appdata = os.getenv("APPDATA")
        if not appdata:
            return False
        startup = Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
        startup.mkdir(parents=True, exist_ok=True)
        script = startup / "Astra-PC.cmd"
        extra = " --voice" if with_voice else ""
        script.write_text(
            "@echo off\r\n"
            f'cd /d "{ROOT}"\r\n'
            f'start "" /min "{sys.executable}" -m astra_pc daemon{extra}\r\n',
            encoding="utf-8",
        )
        print("Startup script installed:", script)
        return True

    if platform.system() == "Darwin":
        launch_dir = Path.home() / "Library" / "LaunchAgents"
        launch_dir.mkdir(parents=True, exist_ok=True)
        plist = launch_dir / "com.astra.pc.plist"
        args_xml = [
            str(sys.executable),
            "-m",
            "astra_pc",
            "daemon",
        ]
        if with_voice:
            args_xml.append("--voice")
        arg_lines = "\n".join(f"      <string>{x}</string>" for x in args_xml)
        log_dir = Path.home() / "Library" / "Logs" / "Astra-PC"
        log_dir.mkdir(parents=True, exist_ok=True)
        plist.write_text(
            "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n"
            "<!DOCTYPE plist PUBLIC \"-//Apple//DTD PLIST 1.0//EN\" "
            "\"http://www.apple.com/DTDs/PropertyList-1.0.dtd\">\n"
            "<plist version=\"1.0\"><dict>\n"
            "  <key>Label</key><string>com.astra.pc</string>\n"
            "  <key>ProgramArguments</key><array>\n"
            f"{arg_lines}\n"
            "  </array>\n"
            f"  <key>WorkingDirectory</key><string>{ROOT}</string>\n"
            "  <key>RunAtLoad</key><true/>\n"
            "  <key>KeepAlive</key><true/>\n"
            f"  <key>StandardOutPath</key><string>{log_dir / 'astra.log'}</string>\n"
            f"  <key>StandardErrorPath</key><string>{log_dir / 'astra.err.log'}</string>\n"
            "</dict></plist>\n",
            encoding="utf-8",
        )
        uid = str(os.getuid())
        run(["launchctl", "bootout", f"gui/{uid}", str(plist)])
        result = run(["launchctl", "bootstrap", f"gui/{uid}", str(plist)])
        if result.returncode == 0:
            print("Astra LaunchAgent enabled:", plist)
            return True
        print("LaunchAgent was written but could not be started automatically.")
        return False

    return False


def _daemon_reachable() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", 8765), timeout=0.4):
            return True
    except Exception:
        return False


def _print_linux_service_diagnostics() -> None:
    if not command_exists("systemctl"):
        return
    print("\n[Astra service diagnostics]")
    subprocess.run(
        ["systemctl", "--user", "--no-pager", "--full", "status", "astra-pc.service"],
        check=False,
    )
    if command_exists("journalctl"):
        subprocess.run(
            ["journalctl", "--user", "-u", "astra-pc.service", "-n", "40", "--no-pager"],
            check=False,
        )


def start_astra(with_voice: bool = True) -> bool:
    """Start Astra now and verify that local IPC becomes reachable."""
    if _daemon_reachable():
        print("Astra daemon is already running.")
        return True

    cmd = [str(sys.executable), "-m", "astra_pc", "daemon"]
    if with_voice:
        cmd.append("--voice")

    # When autostart is installed, systemd owns the process. Do not spawn a
    # second daemon while the service is still starting/warming models.
    service = Path.home() / ".config" / "systemd" / "user" / "astra-pc.service"
    if platform.system() == "Linux" and command_exists("systemctl") and service.exists():
        print("Starting/restarting Astra through systemd --user...")
        run(["systemctl", "--user", "restart", "astra-pc.service"])
        for _ in range(120):
            if _daemon_reachable():
                print("Astra daemon started.")
                return True
            state = subprocess.run(
                ["systemctl", "--user", "is-failed", "astra-pc.service"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
            if state.returncode == 0:
                break
            time.sleep(0.25)
        print("Astra systemd service did not become reachable.")
        _print_linux_service_diagnostics()
        return False

    log_dir = (
        Path(os.getenv("LOCALAPPDATA", Path.home())) / "Astra-PC" / "logs"
        if platform.system() == "Windows"
        else Path.home() / ".local" / "state" / "astra-pc"
    )
    log_dir.mkdir(parents=True, exist_ok=True)
    stdout = open(log_dir / "astra.log", "a", encoding="utf-8")
    stderr = open(log_dir / "astra.err.log", "a", encoding="utf-8")

    kwargs = {
        "cwd": str(ROOT),
        "stdout": stdout,
        "stderr": stderr,
        "stdin": subprocess.DEVNULL,
    }
    if platform.system() == "Windows":
        kwargs["creationflags"] = (
            getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
        )
    else:
        kwargs["start_new_session"] = True

    try:
        subprocess.Popen(cmd, **kwargs)
    except Exception as exc:
        print("Could not start Astra:", exc)
        return False

    for _ in range(120):
        if _daemon_reachable():
            print("Astra daemon started.")
            return True
        time.sleep(0.25)

    print("Astra was launched, but the daemon did not become reachable after 30 seconds.")
    print("Check log:", log_dir / "astra.err.log")
    try:
        tail = (log_dir / "astra.err.log").read_text(encoding="utf-8", errors="ignore").splitlines()[-25:]
        if tail:
            print("\nLast Astra errors:")
            print("\n".join(tail))
    except Exception:
        pass
    return False


def mesh_port_available(port: int = 8767) -> bool:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("0.0.0.0", port))
        return True
    except OSError:
        return False
    finally:
        sock.close()


def configure_mesh_firewall(port: int, assume_yes: bool = False) -> None:
    if platform.system() == "Linux":
        if command_exists("firewall-cmd"):
            state = subprocess.run(
                ["firewall-cmd", "--state"],
                capture_output=True,
                text=True,
                check=False,
            )
            if state.returncode == 0:
                if ask(
                    f"Allow Astra Mesh TCP {port} through firewalld?",
                    True,
                    assume_yes,
                ):
                    run(["sudo", "firewall-cmd", "--permanent", f"--add-port={port}/tcp"])
                    run(["sudo", "firewall-cmd", "--reload"])
                return
        if command_exists("ufw"):
            status = subprocess.run(
                ["ufw", "status"],
                capture_output=True,
                text=True,
                check=False,
            )
            if "Status: active" in status.stdout:
                if ask(
                    f"Allow Astra Mesh TCP {port} through UFW?",
                    True,
                    assume_yes,
                ):
                    run(["sudo", "ufw", "allow", f"{port}/tcp"])
                return

    if platform.system() == "Windows":
        ps = shutil.which("powershell") or shutil.which("pwsh")
        if ps and ask(
            f"Create Windows Firewall rule for Astra Mesh TCP {port}?",
            True,
            assume_yes,
        ):
            command = (
                "$name='Astra Mesh'; "
                "Get-NetFirewallRule -DisplayName $name -ErrorAction SilentlyContinue | "
                "Remove-NetFirewallRule -ErrorAction SilentlyContinue; "
                f"New-NetFirewallRule -DisplayName $name -Direction Inbound "
                f"-Action Allow -Protocol TCP -LocalPort {port} | Out-Null"
            )
            run([ps, "-NoProfile", "-Command", command])


def install_awareness_extras() -> bool:
    print("\n[AWARENESS EXTRAS]")
    print("  Browser DOM -> Playwright")
    print("  Dedicated wake word -> openWakeWord ONNX backend")

    browser_ok = uv_install_into(
        sys.executable,
        "-e",
        f"{ROOT}[browser]",
    )

    wake_deps_ok = uv_install_into(
        sys.executable,
        "-e",
        f"{ROOT}[wakeword]",
    )

    wake_pkg_ok = True
    if platform.system() == "Linux" and sys.version_info >= (3, 12):
        print("  Linux/Python 3.12: installing openWakeWord without broken TFLite dependency.")
        print("  Astra uses .onnx wake-word models on this runtime.")
        wake_pkg_ok = uv_install_into(
            sys.executable,
            "--no-deps",
            "openwakeword>=0.6.0,<1",
        )

    return browser_ok and wake_deps_ok and wake_pkg_ok


def install_voice() -> bool:
    print("\n[FAST VOICE] Low-latency offline voice stack:")
    print("  faster-whisper -> accurate local transcription")
    print("  WebRTC VAD     -> detects speech/silence in ~30 ms frames")
    print("  sounddevice    -> microphone capture")
    print("  pyttsx3/system TTS -> local spoken replies")
    print("  Vosk remains available as a lightweight fallback")
    fast = uv_install_into(
        sys.executable,
        "-e",
        f"{ROOT}[voice-fast]",
    )
    if not fast:
        return False
    uv_install_into(
        sys.executable,
        "-e",
        f"{ROOT}[voice]",
    )
    return True

def install_ydotool(pm: str | None, allow_layering: bool = False) -> bool:
    if command_exists("ydotool"):
        print("ydotool already installed.")
        return True

    print("\n[WAYLAND] ydotool is used for low-latency mouse/keyboard injection.")
    if pm == "dnf":
        return run(["sudo", "dnf", "install", "-y", "ydotool"]).returncode == 0
    if pm == "rpm-ostree":
        print("Fedora Atomic/Bazzite detected.")
        if not allow_layering:
            print("Astra will not modify the immutable base automatically.")
            print("ydotool can be layered manually, or rerun with --allow-layering.")
            return False
        print("Layering ydotool; a reboot may be required.")
        return run(["sudo", "rpm-ostree", "install", "ydotool"]).returncode == 0
    if pm == "apt":
        return run(["sudo", "apt", "install", "-y", "ydotool"]).returncode == 0
    if pm == "pacman":
        return run(["sudo", "pacman", "-S", "--needed", "--noconfirm", "ydotool"]).returncode == 0
    if pm == "zypper":
        return run(["sudo", "zypper", "--non-interactive", "install", "ydotool"]).returncode == 0

    print("Automatic ydotool installation is unavailable for this system.")
    return False


def ydotool_daemon_status() -> tuple[bool, str]:
    if not command_exists("ydotool"):
        return False, "ydotool binary missing"

    sockets = [
        Path("/tmp/.ydotool_socket"),
        Path(os.getenv("XDG_RUNTIME_DIR", "")) / ".ydotool_socket"
        if os.getenv("XDG_RUNTIME_DIR") else None,
    ]
    sockets = [p for p in sockets if p is not None]
    if any(p.exists() for p in sockets):
        return True, "socket ready"

    if command_exists("pgrep"):
        p = subprocess.run(
            ["pgrep", "-x", "ydotoold"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if p.returncode == 0:
            return True, "ydotoold process running"

    return False, "daemon/socket not detected"


def enable_ydotool_service() -> bool:
    if platform.system() != "Linux" or not command_exists("systemctl"):
        return False
    if not command_exists("ydotool"):
        return False

    ready, detail = ydotool_daemon_status()
    if ready:
        print(f"[WAYLAND] ydotool: {detail}")
        return True

    print("\n[WAYLAND] Starting ydotool daemon...")
    for service in ("ydotool.service", "ydotoold.service"):
        exists = subprocess.run(
            ["systemctl", "list-unit-files", service, "--no-legend"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            check=False,
        )
        if service not in exists.stdout:
            continue
        p = run(["sudo", "systemctl", "enable", "--now", service])
        if p.returncode == 0:
            time.sleep(0.5)
            ready, detail = ydotool_daemon_status()
            if ready:
                print(f"[WAYLAND] ydotool ready: {detail}")
                return True

    print("ydotool is installed, but its daemon/socket is not usable yet.")
    print("Astra will keep running; native Wayland input may be unavailable until ydotoold is configured.")
    return False


def kernel_module_loaded(name: str) -> bool:
    try:
        modules = Path("/proc/modules").read_text(encoding="utf-8", errors="ignore")
        return any(line.split()[0] == name for line in modules.splitlines() if line.strip())
    except Exception:
        return False


def kernel_module_available(name: str) -> bool:
    if not command_exists("modinfo"):
        return False
    return subprocess.run(
        ["modinfo", name],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    ).returncode == 0


def configure_v4l2loopback_boot(assume_yes: bool) -> None:
    if platform.system() != "Linux":
        return

    load_file = Path("/etc/modules-load.d/astra-v4l2loopback.conf")
    option_file = Path("/etc/modprobe.d/astra-v4l2loopback.conf")
    already = False
    try:
        already = (
            load_file.exists()
            and "v4l2loopback" in load_file.read_text(encoding="utf-8", errors="ignore")
        )
    except Exception:
        pass

    if already:
        return

    if not ask("Load the Astra/DroidCam virtual camera automatically after reboot?", True, assume_yes):
        return

    script = (
        "printf '%s\\n' 'v4l2loopback' > /etc/modules-load.d/astra-v4l2loopback.conf && "
        "printf '%s\\n' 'options v4l2loopback exclusive_caps=1 card_label=DroidCam' "
        "> /etc/modprobe.d/astra-v4l2loopback.conf"
    )
    result = run(["sudo", "sh", "-c", script])
    if result.returncode == 0:
        print("[DROIDCAM VIDEO] v4l2loopback configured for future boots.")
    else:
        print("Could not persist v4l2loopback boot configuration; current session can still work.")


def ensure_v4l2loopback(
    pm: str | None,
    assume_yes: bool,
    allow_layering: bool = False,
) -> tuple[bool, bool]:
    """Return (driver_ready_now, reboot_required)."""
    if platform.system() != "Linux":
        return False, False

    for module in ("v4l2loopback", "v4l2loopback_dc"):
        if kernel_module_loaded(module):
            print(f"[DROIDCAM VIDEO] {module} already loaded.")
            if module == "v4l2loopback":
                configure_v4l2loopback_boot(assume_yes)
            return True, False

    # Prefer the standard module: DroidCam officially supports it and Bazzite
    # commonly ships a prebuilt v4l2loopback kmod.
    if kernel_module_available("v4l2loopback"):
        if ask("Load the existing v4l2loopback camera driver now?", True, assume_yes):
            result = run([
                "sudo",
                "modprobe",
                "v4l2loopback",
                "exclusive_caps=1",
                "card_label=DroidCam",
            ])
            if result.returncode == 0 and kernel_module_loaded("v4l2loopback"):
                time.sleep(0.5)
                print("[DROIDCAM VIDEO] v4l2loopback loaded.")
                configure_v4l2loopback_boot(assume_yes)
                return True, False
            print("The installed v4l2loopback module could not be loaded.")

    if kernel_module_available("v4l2loopback_dc"):
        if ask("Load DroidCam's v4l2loopback_dc driver now?", True, assume_yes):
            result = run(["sudo", "modprobe", "v4l2loopback_dc"])
            if result.returncode == 0 and kernel_module_loaded("v4l2loopback_dc"):
                time.sleep(0.5)
                return True, False

    if pm == "rpm-ostree":
        print("\nBazzite/Fedora Atomic: no usable V4L2 loopback module is active.")
        print("Astra can layer RPM Fusion's v4l2loopback packages, but that changes")
        print("the immutable host and normally requires a reboot.")

        permitted = allow_layering
        if not permitted and not assume_yes:
            permitted = ask(
                "Layer v4l2loopback + akmod-v4l2loopback on the host?",
                False,
                False,
            )

        if not permitted:
            print("Host layering skipped.")
            print("You can retry later with: astra setup camera --allow-layering")
            return False, False

        result = run([
            "sudo",
            "rpm-ostree",
            "install",
            "v4l2loopback",
            "akmod-v4l2loopback",
        ])
        if result.returncode == 0:
            print("V4L2 packages layered. Reboot is required before the driver is usable.")
            return False, True
        print("rpm-ostree could not layer the V4L2 packages.")
        return False, False

    return False, False


def launch_droidcam_and_wait(
    assume_yes: bool,
    timeout: int = 75,
) -> list[tuple[int, int, int]]:
    binary = droidcam_binary()
    if binary is None:
        return []

    if os.getenv("DISPLAY") or os.getenv("WAYLAND_DISPLAY"):
        if ask("Open DroidCam now so you can connect the phone?", True, assume_yes):
            try:
                subprocess.Popen(
                    [str(binary)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
                print("DroidCam launched:", binary)
            except Exception as exc:
                print("Could not launch DroidCam automatically:", exc)

    print("\nOn your phone:")
    print("  1. Open the DroidCam app.")
    print("  2. Connect it to this PC using Wi-Fi/USB.")
    print("  3. Make sure video is visible in DroidCam.")
    print("Astra will look for the video device after that.")

    if not ask("Wait for DroidCam video and test it now?", True, assume_yes):
        return []

    deadline = time.monotonic() + max(10, timeout)
    last_note = 0.0
    while time.monotonic() < deadline:
        cameras = probe_cameras_opencv(limit=24)
        if cameras:
            print("\n[DROIDCAM] Working camera detected:")
            for idx, w, h in cameras:
                print(f"  camera {idx}: {w}x{h}")
            return cameras
        now = time.monotonic()
        if now - last_note >= 10:
            remaining = max(0, int(deadline - now))
            print(f"Waiting for camera frames... ({remaining}s remaining)")
            last_note = now
        time.sleep(1.0)

    print("No camera frames arrived before the timeout.")
    return []


def droidcam_binary() -> Path | None:
    names = ("droidcam", "droidcam-cli")
    for name in names:
        resolved = shutil.which(name)
        if resolved:
            return Path(resolved)
    for candidate in (
        Path("/usr/local/bin/droidcam"),
        Path("/usr/local/bin/droidcam-cli"),
        Path("/usr/bin/droidcam"),
        Path("/usr/bin/droidcam-cli"),
        Path("/opt/droidcam/droidcam"),
    ):
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


def droidcam_client_installed() -> bool:
    return droidcam_binary() is not None


def install_droidcam_windows() -> bool:
    if not command_exists("winget"):
        print("winget was not found.")
        print("Official installer: https://www.dev47apps.com/droidcam/windows/")
        return False

    print("\n[DROIDCAM] Installing DroidCam Classic using winget.")
    return run([
        "winget",
        "install",
        "--id",
        "dev47apps.DroidCam",
        "--exact",
        "--accept-source-agreements",
        "--accept-package-agreements",
    ]).returncode == 0


def _latest_droidcam_linux_url() -> str:
    page = urllib.request.urlopen(
        "https://www.dev47apps.com/droidcam/linux/",
        timeout=15,
    ).read().decode("utf-8", "ignore")

    marker = "https://files.dev47apps.net/linux/droidcam_"
    start = page.find(marker)
    if start < 0:
        raise RuntimeError("current DroidCam Linux download was not found")
    end = page.find(".zip", start)
    if end < 0:
        raise RuntimeError("DroidCam Linux download URL could not be parsed")
    return page[start:end + 4]


def install_linux_build_tools(pm: str | None, allow_layering: bool = False) -> bool:
    print("\n[DROIDCAM VIDEO] A virtual V4L2 camera requires kernel/build tools.")
    if pm == "dnf":
        return run(["sudo", "dnf", "install", "-y", "gcc", "make", "kernel-devel", "kernel-headers"]).returncode == 0
    if pm == "apt":
        return run(["sudo", "apt", "install", "-y", "gcc", "make", f"linux-headers-{platform.release()}"]).returncode == 0
    if pm == "pacman":
        return run(["sudo", "pacman", "-S", "--needed", "--noconfirm", "base-devel", "linux-headers"]).returncode == 0
    if pm == "zypper":
        return run(["sudo", "zypper", "--non-interactive", "install", "gcc", "make", "kernel-devel"]).returncode == 0
    if pm == "rpm-ostree":
        print("Bazzite/Fedora Atomic uses an immutable base system.")
        if not allow_layering:
            print("Skipping kernel/build package layering. Re-run with --allow-layering only if you want it.")
            return False
        print("Kernel-module build dependencies require package layering + reboot.")
        return run(["sudo", "rpm-ostree", "install", "gcc", "make", "kernel-devel", "kernel-headers"]).returncode == 0
    return False


def install_droidcam_linux(pm: str | None, assume_yes: bool, allow_layering: bool = False) -> bool:
    print("\n[DROIDCAM] Phone-as-webcam fallback for Linux.")
    print("The client is resolved from Dev47Apps' official Linux page at install time.")

    already_installed = droidcam_client_installed()
    if already_installed:
        print("DroidCam client already installed:", droidcam_binary())
        driver_ready, reboot_required = ensure_v4l2loopback(
            pm,
            assume_yes,
            allow_layering,
        )
        if reboot_required:
            print("\nReboot the PC, then run: astra setup camera")
            return True
        if driver_ready:
            launch_droidcam_and_wait(assume_yes)
            return True

    try:
        url = _latest_droidcam_linux_url()
    except Exception as exc:
        print("Could not resolve latest DroidCam package:", exc)
        print("Official instructions: https://www.dev47apps.com/droidcam/linux/")
        return False

    with tempfile.TemporaryDirectory(prefix="astra-droidcam-") as td:
        archive = Path(td) / "droidcam.zip"
        target = Path(td) / "droidcam"

        print("Downloading official package:")
        print(" ", url)
        if not download_file(url, archive):
            print("DroidCam download failed.")
            return False

        with zipfile.ZipFile(archive) as zf:
            zf.extractall(target)

        client_installer = target / "install-client"
        video_installer = target / "install-video"

        if not client_installer.exists():
            print("The official archive did not contain install-client.")
            return False

        if not already_installed:
            client_installer.chmod(client_installer.stat().st_mode | 0o111)
            client_result = run(["sudo", str(client_installer)], cwd=target)
            if client_result.returncode != 0:
                # Dev47 may fail at xdg-desktop-menu after /usr/local/bin files
                # were already copied. Flatpak/VS Code terminals can also omit
                # /usr/local/bin from PATH, so check the filesystem directly.
                if droidcam_client_installed():
                    print(
                        "DroidCam binaries are installed; desktop-menu integration "
                        "failed and was ignored."
                    )
                else:
                    print(
                        "DroidCam client installation failed before a usable binary "
                        "was installed."
                    )
                    return False
        else:
            print("Skipping DroidCam client reinstall.")

        print("\nDroidCam's Linux client is installed.")

        driver_ready, reboot_required = ensure_v4l2loopback(
            pm,
            assume_yes,
            allow_layering,
        )
        if reboot_required:
            print("\nReboot the PC, then run: astra setup camera")
            return True

        if driver_ready:
            launch_droidcam_and_wait(assume_yes)
            return True

        if not video_installer.exists():
            print("No usable V4L2 driver was found and install-video was not present.")
            return True

        print("Astra can build DroidCam's own v4l2loopback-dc driver as fallback.")
        if not ask("Build/install DroidCam's own video driver?", True, assume_yes):
            return True

        build_ready = install_linux_build_tools(pm, allow_layering)

        kernel_build = Path("/usr/src/kernels") / platform.release()
        if pm == "rpm-ostree" and not build_ready and not allow_layering:
            print("DroidCam client is installed, but Astra left the immutable OS unchanged.")
            print("Connect another webcam, or rerun with --allow-layering if you want the V4L2 driver.")
            return True
        if pm == "rpm-ostree" and not (command_exists("gcc") and command_exists("make") and kernel_build.exists()):
            print("\nBazzite/Fedora Atomic needs the newly layered build packages active first.")
            print("Reboot, then run installer.py again; it will continue the DroidCam driver setup.")
            return True

        video_installer.chmod(video_installer.stat().st_mode | 0o111)
        result = run(["sudo", str(video_installer)], cwd=target)

        if result.returncode != 0:
            print("\nThe video driver could not be installed automatically.")
            print("Common reasons: missing matching kernel headers or Secure Boot.")
            if pm == "rpm-ostree":
                print("On Bazzite/Fedora Atomic, reboot after package layering and run installer.py again.")
            return True

        launch_droidcam_and_wait(assume_yes)
        return True


def maybe_install_droidcam(pm: str | None, assume_yes: bool, allow_layering: bool = False) -> None:
    print("\n[CAMERA FALLBACK]")
    print("No working camera was detected.")
    print("Astra's gesture engine requires a webcam-like video source.")
    print("You can connect a webcam, use a built-in camera, or turn a phone into one.")

    if not ask("Install DroidCam as a phone-camera fallback?", True, assume_yes):
        return

    if platform.system() == "Windows":
        if install_droidcam_windows():
            launch_droidcam_and_wait(assume_yes)
    elif platform.system() == "Linux":
        install_droidcam_linux(pm, assume_yes, allow_layering)
    else:
        print("Automatic DroidCam installation is currently implemented for Windows/Linux.")


def summary(checks: list[Check]) -> None:
    print("\n" + "=" * 68)
    print(" ASTRA DIAGNOSTIC")
    print("=" * 68)
    for c in checks:
        icon = "OK " if c.ok else ("ERR" if c.required else "WARN")
        print(f"[{icon}] {c.name}: {c.detail}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Astra-PC guided installer")
    parser.add_argument("--yes", action="store_true", help="accept recommended installations")
    parser.add_argument("--no-voice", action="store_true", help="skip offline voice dependencies")
    parser.add_argument("--no-ai", action="store_true", help="skip Ollama/Qwen local AI")
    parser.add_argument("--no-mesh", action="store_true", help="disable Astra Mesh LAN setup")
    parser.add_argument("--media", action="store_true", help="offer optional local ComfyUI setup")
    parser.add_argument("--strong-ai", action="store_true", help="also download optional Qwen3 4B reasoning model")
    parser.add_argument("--awareness-extras", action="store_true", help="install optional wake-word and browser DOM packages")
    parser.add_argument("--autostart", action="store_true", help="enable resident Astra daemon at login")
    parser.add_argument("--diagnose-only", action="store_true", help="inspect hardware without installing")
    parser.add_argument("--camera-only", action="store_true", help="repair/test only camera and DroidCam setup")
    parser.add_argument("--start", action="store_true", help="start Astra after installation")
    parser.add_argument("--full", action="store_true", help="install all Astra features, autostart and start now")
    parser.add_argument("--allow-layering", action="store_true", help="allow rpm-ostree package layering on immutable Linux")
    args = parser.parse_args()

    if args.full:
        args.yes = True
        args.strong_ai = True
        args.awareness_extras = True
        args.autostart = True
        args.media = True
        args.start = True

    ensure_runtime(args.yes)
    banner()

    system = platform.system()
    session = detect_session()
    pm = detect_package_manager()

    checks = [
        Check("Operating system", system in {"Windows", "Linux", "Darwin"}, f"{system} {platform.release()}"),
        Check("Architecture", True, platform.machine(), False),
        Check(
            "Gesture platform",
            gesture_platform_supported()[0],
            gesture_platform_supported()[1],
            False,
        ),
        Check(
            "Python runtime",
            runtime_supported(),
            f"{platform.python_version()} (isolated Astra runtime)",
        ),
        Check("Desktop session", True, session, False),
        Check("Package manager", pm is not None, pm or "not detected", False),
    ]

    camera_hint = basic_camera_candidates()
    checks.append(Check(
        "Camera candidate",
        bool(camera_hint),
        ", ".join(camera_hint[:4]) if camera_hint else "none found before OpenCV probe",
        False,
    ))

    if system == "Linux" and session.lower() == "wayland":
        checks.append(Check(
            "Wayland input backend",
            command_exists("ydotool"),
            (
                "ydotool found; " + ydotool_daemon_status()[1]
                if command_exists("ydotool")
                else "ydotool missing"
            ),
            False,
        ))

    summary(checks)

    if args.diagnose_only:
        return 0

    if args.camera_only:
        print("\n[CAMERA-ONLY MODE]")
        cameras = probe_cameras_opencv()
        if cameras:
            print("Working camera source(s):")
            for idx, w, h in cameras:
                print(f"  camera {idx}: {w}x{h}")
            return 0

        maybe_install_droidcam(pm, args.yes, args.allow_layering)
        cameras = probe_cameras_opencv()
        if cameras:
            print("\nCamera repair successful:")
            for idx, w, h in cameras:
                print(f"  camera {idx}: {w}x{h}")
            return 0

        print("\nNo OpenCV camera source is usable yet.")
        if system == "Linux" and pm == "rpm-ostree" and not args.allow_layering:
            print("Bazzite may need the DroidCam V4L2 driver.")
            print("If you want Astra to layer the required host packages, rerun:")
            print("  python installer.py --camera-only --yes --allow-layering")
            print("A reboot may be required after rpm-ostree changes.")
        return 4

    if system not in {"Windows", "Linux", "Darwin"}:
        print("\nAstra currently targets Windows, Linux and Apple Silicon macOS.")
        return 2

    if system == "Darwin" and platform.machine().lower() not in {"arm64", "aarch64"}:
        print("\nIntel macOS detected.")
        print("Astra AI/voice can work, but current MediaPipe releases do not ship an Intel Mac wheel.")
        print("Gesture/pose features are therefore not guaranteed on this machine.")

    if ask("\nInstall/update Astra core dependencies?", True, args.yes):
        if not install_python_core():
            print("Core installation failed.")
            return 3
    else:
        print("Core dependency installation skipped.")

    try:
        install_user_launcher()
    except Exception as exc:
        print("Could not create the 'astra' launcher:", exc)

    cameras = probe_cameras_opencv()
    if cameras:
        print("\n[CAMERA] Working camera(s):")
        for idx, w, h in cameras:
            print(f"  camera {idx}: {w}x{h}")
    else:
        maybe_install_droidcam(pm, args.yes, args.allow_layering)

    if system == "Linux" and session.lower() == "wayland":
        if not command_exists("ydotool"):
            if ask("\nInstall ydotool for Wayland gesture control?", True, args.yes):
                if install_ydotool(pm, args.allow_layering):
                    enable_ydotool_service()
        else:
            enable_ydotool_service()

    if not args.no_mesh:
        print("\n[MESH] Secure PC/Android network")
        print("  HTTPS + WebSocket + one-time pairing + per-device permissions")
        if mesh_port_available(8767):
            configure_mesh_firewall(8767, args.yes)
        else:
            print("  Port 8767 is already in use. If Astra is already running, this is expected.")

    if not args.no_voice:
        if ask("\nInstall ultra-low-latency offline voice support?", True, args.yes):
            install_voice()

    if ask("\nInstall structural accessibility support for more reliable UI control?", True, args.yes):
        install_accessibility_support()

    if not args.no_ai:
        if ask("\nInstall Astra low-latency local AI (Qwen3 0.6B + Qwen3-VL 2B)?", True, args.yes):
            if install_ollama():
                ensure_astra_models()
                if args.strong_ai:
                    print("\n[STRONG AI] Optional Qwen3 4B reasoning model")
                    run(["ollama", "pull", "qwen3:4b"])

    want_autostart = args.autostart
    if not args.yes and not args.autostart:
        want_autostart = ask("\nStart Astra automatically with the desktop?", False, False)
    if want_autostart:
        if install_autostart(with_voice=not args.no_voice):
            print("Astra resident daemon autostart enabled.")

    if args.awareness_extras:
        if not install_awareness_extras():
            print("Awareness extras were only partially installed; core Astra remains usable.")

    if args.media:
        if comfyui_available():
            print("\n[MEDIA GENERATION] A local ComfyUI server is already reachable.")
        elif ask("\nSet up optional local ComfyUI media generation?", False, args.yes):
            install_comfyui()

    microphones = probe_microphones()
    print("\n[MICROPHONE]")
    if microphones:
        for name in microphones[:8]:
            print(" ", name)
    else:
        print("  No usable microphone reported.")

    print("\n" + "=" * 68)
    print(" FINAL CHECK")
    print("=" * 68)
    cameras = probe_cameras_opencv()
    print("Cameras usable by OpenCV:", len(cameras))
    print("Desktop session:", session)
    print("ydotool:", "yes" if command_exists("ydotool") else "no")
    print("Fast voice:", "yes" if importlib.util.find_spec("faster_whisper") else "no")
    print("Vosk fallback:", "yes" if importlib.util.find_spec("vosk") else "no")
    print("Ollama:", "yes" if command_exists("ollama") else "no")
    print("Ollama API:", "yes" if ollama_api_available() else "no")
    print("ComfyUI API:", "yes" if comfyui_available() else "no")
    print("Astra Mesh:", "yes" if importlib.util.find_spec("aiohttp") and importlib.util.find_spec("cryptography") else "no")
    print("Mesh port 8767:", "available" if mesh_port_available(8767) else "in use / Astra running")
    print("Semantic embeddings:", "configured via qwen3-embedding:0.6b")
    print("Dedicated wake word:", "yes" if importlib.util.find_spec("openwakeword") else "optional")
    print("Browser DOM:", "yes" if importlib.util.find_spec("playwright") else "optional")
    print("Accessibility:", "yes" if (
        importlib.util.find_spec("pyatspi") or importlib.util.find_spec("pywinauto")
    ) else "visual fallback")

    if system == "Linux" and pm == "rpm-ostree":
        print("\nNOTE: package layering on Bazzite/Fedora Atomic may require a reboot.")

    if cameras:
        print("\nSafe first run:")
        print(f"  {sys.executable} -m astra_pc gestures --dry-run --show-camera")
        print("\nReal gesture control:")
        print(f"  {sys.executable} -m astra_pc gestures")
    else:
        print("\nGesture control: waiting for a working camera source.")
        print("Voice, AI, screen understanding and Astra Mesh can run without a camera.")
    print("\nLocal Astra chat:")
    print(f'  {sys.executable} -m astra_pc ask "O que voce consegue fazer?"')
    print("\nUnderstand the screen:")
    print(f'  {sys.executable} -m astra_pc screen "O que esta acontecendo aqui?"')
    print("\nLatency benchmark:")
    print(f"  {sys.executable} -m astra_pc benchmark")
    print("\nFast voice:")
    print(f"  {sys.executable} -m astra_pc voice --engine fast")
    print("\nMesh pairing:")
    print("  astra mesh pair-code")

    if args.start:
        print("\n[START]")
        start_astra(with_voice=not args.no_voice)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
