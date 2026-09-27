#!/usr/bin/env python3
from __future__ import annotations

import argparse
import glob
import importlib.util
import os
import platform
import shutil
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
    print(" ASTRA-PC 0.7 AWARENESS INSTALLER / DIAGNOSTIC")
    print("=" * 68)
    print("Resident context + fast voice + local multimodal AI + semantic memory.\n")


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
                urllib.request.urlretrieve("https://astral.sh/uv/install.sh", script)
                script.chmod(script.stat().st_mode | 0o111)
                result = run(["sh", str(script)])
        if result.returncode != 0:
            return None
    except Exception as exc:
        print("Could not install uv:", exc)
        return None

    return find_uv()


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

    print(f"\n[PYTHON RUNTIME] Ensuring Python {RUNTIME_PYTHON}...")
    if run([uv, "python", "install", RUNTIME_PYTHON]).returncode != 0:
        raise SystemExit("uv could not install the Astra Python runtime.")

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
            "--python",
            RUNTIME_PYTHON,
            str(ROOT / ".venv"),
        ])
        if result.returncode != 0 or not managed.exists():
            raise SystemExit("Could not create Astra's managed .venv.")

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

    found: list[tuple[int, int, int]] = []
    for index in range(limit):
        cap = cv2.VideoCapture(index)
        if not cap.isOpened():
            cap.release()
            continue
        ok, frame = cap.read()
        if ok and frame is not None:
            h, w = frame.shape[:2]
            found.append((index, w, h))
        cap.release()
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


def install_python_core() -> bool:
    print("\n[CORE] Components required by the gesture engine:")
    print("  OpenCV    -> capture frames from the camera")
    print("  MediaPipe -> track 21 hand landmarks")
    print("  pynput    -> native mouse/keyboard actions on Windows/X11")
    print("  NumPy     -> low-overhead numeric processing")
    return run([sys.executable, "-m", "pip", "install", "-e", str(ROOT)]).returncode == 0


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
                urllib.request.urlretrieve("https://ollama.com/install.sh", script)
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
        # Works on macOS and Bazzite/Homebrew Linux; failure is harmless because
        # we still fall back to a detached "ollama serve" below.
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
    if not venv.exists():
        if run([sys.executable, "-m", "venv", str(venv)]).returncode != 0:
            return False

    pip = venv / ("Scripts/pip.exe" if platform.system() == "Windows" else "bin/pip")
    if not pip.exists():
        return False

    print("Installing ComfyUI Python dependencies. This optional step can be large.")
    if run([str(pip), "install", "-r", str(target / "requirements.txt")]).returncode != 0:
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
        return run([
            sys.executable, "-m", "pip", "install", "-e", f"{ROOT}[accessibility]"
        ]).returncode == 0

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

    return False


def install_voice() -> bool:
    print("\n[FAST VOICE] Low-latency offline voice stack:")
    print("  faster-whisper -> accurate local transcription")
    print("  WebRTC VAD     -> detects speech/silence in ~30 ms frames")
    print("  sounddevice    -> microphone capture")
    print("  pyttsx3/system TTS -> local spoken replies")
    print("  Vosk remains available as a lightweight fallback")
    fast = run([
        sys.executable,
        "-m",
        "pip",
        "install",
        "-e",
        f"{ROOT}[voice-fast]",
    ]).returncode == 0
    if not fast:
        return False
    run([
        sys.executable,
        "-m",
        "pip",
        "install",
        "-e",
        f"{ROOT}[voice]",
    ])
    return True

def install_ydotool(pm: str | None) -> bool:
    if command_exists("ydotool"):
        print("ydotool already installed.")
        return True

    print("\n[WAYLAND] ydotool is used for low-latency mouse/keyboard injection.")
    if pm == "dnf":
        return run(["sudo", "dnf", "install", "-y", "ydotool"]).returncode == 0
    if pm == "rpm-ostree":
        print("Fedora Atomic/Bazzite detected.")
        print("Layering ydotool may require a reboot before it becomes available.")
        return run(["sudo", "rpm-ostree", "install", "ydotool"]).returncode == 0
    if pm == "apt":
        return run(["sudo", "apt", "install", "-y", "ydotool"]).returncode == 0
    if pm == "pacman":
        return run(["sudo", "pacman", "-S", "--needed", "--noconfirm", "ydotool"]).returncode == 0
    if pm == "zypper":
        return run(["sudo", "zypper", "--non-interactive", "install", "ydotool"]).returncode == 0

    print("Automatic ydotool installation is unavailable for this system.")
    return False


def enable_ydotool_service() -> None:
    if platform.system() != "Linux" or not command_exists("systemctl"):
        return
    if not command_exists("ydotool"):
        return

    print("\n[WAYLAND] Enabling ydotoold...")
    p = run(["sudo", "systemctl", "enable", "--now", "ydotool"])
    if p.returncode != 0:
        print("Could not enable ydotool automatically.")
        print("Try manually: sudo systemctl enable --now ydotool")


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


def install_linux_build_tools(pm: str | None) -> None:
    print("\n[DROIDCAM VIDEO] A virtual V4L2 camera requires kernel/build tools.")
    if pm == "dnf":
        run(["sudo", "dnf", "install", "-y", "gcc", "make", "kernel-devel", "kernel-headers"])
    elif pm == "apt":
        run(["sudo", "apt", "install", "-y", "gcc", "make", f"linux-headers-{platform.release()}"])
    elif pm == "pacman":
        run(["sudo", "pacman", "-S", "--needed", "--noconfirm", "base-devel", "linux-headers"])
    elif pm == "zypper":
        run(["sudo", "zypper", "--non-interactive", "install", "gcc", "make", "kernel-devel"])
    elif pm == "rpm-ostree":
        print("Bazzite/Fedora Atomic uses an immutable base system.")
        print("Kernel-module build dependencies can require package layering + reboot.")
        run(["sudo", "rpm-ostree", "install", "gcc", "make", "kernel-devel", "kernel-headers"])


def install_droidcam_linux(pm: str | None, assume_yes: bool) -> bool:
    print("\n[DROIDCAM] Phone-as-webcam fallback for Linux.")
    print("The client is resolved from Dev47Apps' official Linux page at install time.")

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
        urllib.request.urlretrieve(url, archive)

        with zipfile.ZipFile(archive) as zf:
            zf.extractall(target)

        client_installer = target / "install-client"
        video_installer = target / "install-video"

        if not client_installer.exists():
            print("The official archive did not contain install-client.")
            return False

        client_installer.chmod(client_installer.stat().st_mode | 0o111)
        if run(["sudo", str(client_installer)], cwd=target).returncode != 0:
            print("DroidCam client installation failed.")
            return False

        if not video_installer.exists():
            print("DroidCam client installed, but install-video was not present.")
            return True

        print("\nDroidCam's Linux client is installed.")
        print("For Astra to see the phone as /dev/video*, DroidCam normally needs")
        print("a V4L2 loopback camera driver.")
        if not ask("Install DroidCam's video driver too?", True, assume_yes):
            return True

        install_linux_build_tools(pm)

        kernel_build = Path("/usr/src/kernels") / platform.release()
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

        return True


def maybe_install_droidcam(pm: str | None, assume_yes: bool) -> None:
    print("\n[CAMERA FALLBACK]")
    print("No working camera was detected.")
    print("Astra's gesture engine requires a webcam-like video source.")
    print("You can connect a webcam, use a built-in camera, or turn a phone into one.")

    if not ask("Install DroidCam as a phone-camera fallback?", True, assume_yes):
        return

    if platform.system() == "Windows":
        install_droidcam_windows()
    elif platform.system() == "Linux":
        install_droidcam_linux(pm, assume_yes)
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
    parser.add_argument("--media", action="store_true", help="offer optional local ComfyUI setup")
    parser.add_argument("--strong-ai", action="store_true", help="also download optional Qwen3 4B reasoning model")
    parser.add_argument("--awareness-extras", action="store_true", help="install optional wake-word and browser DOM packages")
    parser.add_argument("--autostart", action="store_true", help="enable resident Astra daemon at login")
    parser.add_argument("--diagnose-only", action="store_true", help="inspect hardware without installing")
    parser.add_argument("--start", action="store_true", help="start Astra after installation")
    parser.add_argument("--allow-layering", action="store_true", help="allow rpm-ostree package layering on immutable Linux")
    args = parser.parse_args()

    ensure_runtime(args.yes)
    banner()

    system = platform.system()
    session = detect_session()
    pm = detect_package_manager()

    checks = [
        Check("Operating system", system in {"Windows", "Linux"}, f"{system} {platform.release()}"),
        Check("Architecture", True, platform.machine(), False),
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
            "ydotool found" if command_exists("ydotool") else "ydotool missing",
            False,
        ))

    summary(checks)

    if args.diagnose_only:
        return 0

    if system not in {"Windows", "Linux"}:
        print("\nAstra currently targets Windows and Linux.")
        return 2

    if ask("\nInstall/update Astra core dependencies?", True, args.yes):
        if not install_python_core():
            print("Core installation failed.")
            return 3
    else:
        print("Core dependency installation skipped.")

    cameras = probe_cameras_opencv()
    if cameras:
        print("\n[CAMERA] Working camera(s):")
        for idx, w, h in cameras:
            print(f"  camera {idx}: {w}x{h}")
    else:
        maybe_install_droidcam(pm, args.yes)

    if system == "Linux" and session.lower() == "wayland":
        if not command_exists("ydotool"):
            if ask("\nInstall ydotool for Wayland gesture control?", True, args.yes):
                if install_ydotool(pm):
                    enable_ydotool_service()
        else:
            enable_ydotool_service()

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
        print("\n[AWARENESS EXTRAS] Installing dedicated wake-word + optional browser DOM support.")
        run([sys.executable, "-m", "pip", "install", "-e", f"{ROOT}[wakeword,browser]"])

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
    print("Semantic embeddings:", "configured via qwen3-embedding:0.6b")
    print("Dedicated wake word:", "yes" if importlib.util.find_spec("openwakeword") else "optional")
    print("Browser DOM:", "yes" if importlib.util.find_spec("playwright") else "optional")
    print("Accessibility:", "yes" if (
        importlib.util.find_spec("pyatspi") or importlib.util.find_spec("pywinauto")
    ) else "visual fallback")

    if system == "Linux" and pm == "rpm-ostree":
        print("\nNOTE: package layering on Bazzite/Fedora Atomic may require a reboot.")

    print("\nSafe first run:")
    print(f"  {sys.executable} -m astra_pc gestures --dry-run --show-camera")
    print("\nReal gesture control:")
    print(f"  {sys.executable} -m astra_pc gestures")
    print("\nLocal Astra chat:")
    print(f'  {sys.executable} -m astra_pc ask "O que voce consegue fazer?"')
    print("\nUnderstand the screen:")
    print(f'  {sys.executable} -m astra_pc screen "O que esta acontecendo aqui?"')
    print("\nLatency benchmark:")
    print(f"  {sys.executable} -m astra_pc benchmark")
    print("\nFast voice:")
    print(f"  {sys.executable} -m astra_pc voice --engine fast")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
