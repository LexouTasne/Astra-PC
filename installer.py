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
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parent


@dataclass(slots=True)
class Check:
    name: str
    ok: bool
    detail: str
    required: bool = True


def banner() -> None:
    print("=" * 66)
    print(" ASTRA-PC INSTALLER / DIAGNOSTIC")
    print("=" * 66)
    print("Local-first setup for gesture control, voice and cameras.\n")


def ask(question: str, default: bool = True, assume_yes: bool = False) -> bool:
    if assume_yes:
        print(f"{question} -> yes (--yes)")
        return True
    suffix = " [Y/n] " if default else " [y/N] "
    answer = input(question + suffix).strip().lower()
    if not answer:
        return default
    return answer in {"y", "yes", "s", "sim"}


def run(cmd: list[str], *, check: bool = False) -> subprocess.CompletedProcess:
    print("  $", " ".join(cmd))
    return subprocess.run(cmd, check=check)


def command_exists(name: str) -> bool:
    return shutil.which(name) is not None


def detect_session() -> str:
    if platform.system() != "Linux":
        return platform.system()
    if os.getenv("WAYLAND_DISPLAY"):
        return "Wayland"
    if os.getenv("DISPLAY"):
        return "X11"
    return os.getenv("XDG_SESSION_TYPE", "unknown")


def detect_package_manager() -> str | None:
    for name in ("rpm-ostree", "dnf", "apt", "pacman", "zypper", "winget"):
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
                ps, "-NoProfile", "-Command",
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
    print("\n[CORE] Installing Astra gesture engine dependencies")
    print("  - OpenCV: camera capture")
    print("  - MediaPipe: hand landmark tracking")
    print("  - pynput: mouse/keyboard input on Windows/X11")
    print("  - NumPy: lightweight numeric operations")
    p = run([sys.executable, "-m", "pip", "install", "-e", str(ROOT)])
    return p.returncode == 0


def install_voice() -> bool:
    print("\n[VOICE] Installing optional offline voice stack")
    print("  - Vosk: offline speech-to-text")
    print("  - sounddevice: microphone capture")
    p = run([sys.executable, "-m", "pip", "install", "-e", f"{ROOT}[voice]"])
    return p.returncode == 0


def install_ydotool(pm: str | None) -> bool:
    if command_exists("ydotool"):
        print("ydotool already installed.")
        return True

    print("\n[WAYLAND] ydotool injects mouse/keyboard events on Wayland.")
    if pm == "dnf":
        return run(["sudo", "dnf", "install", "-y", "ydotool"]).returncode == 0
    if pm == "rpm-ostree":
        print("Bazzite/Fedora Atomic detected.")
        print("This layers the Fedora ydotool package and may require a reboot.")
        return run(["sudo", "rpm-ostree", "install", "ydotool"]).returncode == 0
    if pm == "apt":
        return run(["sudo", "apt", "install", "-y", "ydotool"]).returncode == 0
    if pm == "pacman":
        return run(["sudo", "pacman", "-S", "--needed", "--noconfirm", "ydotool"]).returncode == 0
    if pm == "zypper":
        return run(["sudo", "zypper", "--non-interactive", "install", "ydotool"]).returncode == 0

    print("Automatic ydotool installation is not available for this system.")
    return False


def enable_ydotool_service() -> None:
    if platform.system() != "Linux" or not command_exists("systemctl"):
        return
    if not command_exists("ydotool"):
        return
    print("\n[WAYLAND] Enabling ydotool daemon...")
    p = run(["sudo", "systemctl", "enable", "--now", "ydotool"])
    if p.returncode != 0:
        print("Could not enable ydotool service automatically.")
        print("You can try: sudo systemctl enable --now ydotool")


def install_droidcam_windows() -> bool:
    if not command_exists("winget"):
        print("winget was not found. Open the official DroidCam page:")
        print("https://www.dev47apps.com/droidcam/windows/")
        return False
    print("\n[DROIDCAM] Installing DroidCam Classic through winget.")
    return run([
        "winget", "install", "--id", "dev47apps.DroidCam", "--exact",
        "--accept-source-agreements", "--accept-package-agreements"
    ]).returncode == 0


def _latest_droidcam_linux_url() -> str:
    page = urllib.request.urlopen(
        "https://www.dev47apps.com/droidcam/linux/", timeout=15
    ).read().decode("utf-8", "ignore")
    marker = "https://files.dev47apps.net/linux/droidcam_"
    start = page.find(marker)
    if start < 0:
        raise RuntimeError("Could not find current DroidCam Linux download URL")
    end = page.find(".zip", start)
    if end < 0:
        raise RuntimeError("Could not parse DroidCam Linux download URL")
    return page[start:end + 4]


def install_droidcam_linux(pm: str | None) -> bool:
    print("\n[DROIDCAM] Phone-as-webcam fallback for Linux.")
    print("Astra will download the current client from Dev47Apps' official page.")
    try:
        url = _latest_droidcam_linux_url()
    except Exception as exc:
        print("Could not resolve latest DroidCam package:", exc)
        print("Official instructions: https://www.dev47apps.com/droidcam/linux/")
        return False

    if pm in {"dnf", "rpm-ostree"} and not command_exists("unzip"):
        if pm == "dnf":
            run(["sudo", "dnf", "install", "-y", "unzip"])
        else:
            run(["sudo", "rpm-ostree", "install", "unzip"])
    elif pm == "apt" and not command_exists("unzip"):
        run(["sudo", "apt", "install", "-y", "unzip"])

    with tempfile.TemporaryDirectory(prefix="astra-droidcam-") as td:
        archive = Path(td) / "droidcam.zip"
        target = Path(td) / "droidcam"
        print("Downloading:", url)
        urllib.request.urlretrieve(url, archive)
        with zipfile.ZipFile(archive) as zf:
            zf.extractall(target)
        installer = target / "install-client"
        if not installer.exists():
            print("DroidCam archive did not contain install-client.")
            return False
        installer.chmod(installer.stat().st_mode | 0o111)
        return run(["sudo", str(installer)]).returncode == 0


def maybe_install_droidcam(pm: str | None, assume_yes: bool) -> None:
    print("\nNo working camera was detected.")
    print("Astra needs a camera for hand tracking.")
    print("You can connect a USB webcam, use your laptop camera, or use a phone.")
    if not ask("Install DroidCam so a phone can be used as the camera?", True, assume_yes):
        return
    if platform.system() == "Windows":
        install_droidcam_windows()
    elif platform.system() == "Linux":
        install_droidcam_linux(pm)
    else:
        print("Automatic DroidCam installation is only implemented for Windows/Linux.")


def summary(checks: list[Check]) -> None:
    print("\n" + "=" * 66)
    print(" ASTRA DIAGNOSTIC")
    print("=" * 66)
    for c in checks:
        icon = "OK " if c.ok else ("ERR" if c.required else "WARN")
        print(f"[{icon}] {c.name}: {c.detail}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Astra-PC guided installer")
    parser.add_argument("--yes", action="store_true", help="accept recommended installations")
    parser.add_argument("--no-voice", action="store_true", help="skip offline voice dependencies")
    parser.add_argument("--diagnose-only", action="store_true", help="do not install anything")
    args = parser.parse_args()

    banner()
    system = platform.system()
    session = detect_session()
    pm = detect_package_manager()

    checks = [
        Check("Operating system", system in {"Windows", "Linux"}, f"{system} {platform.release()}"),
        Check("Python", sys.version_info >= (3, 11), platform.python_version()),
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

    summary(checks)
    if args.diagnose_only:
        return 0

    if sys.version_info < (3, 11):
        print("\nPython 3.11+ is required. Install a supported Python version first.")
        return 2

    if not ask("\nInstall/update Astra core dependencies?", True, args.yes):
        print("Core dependency installation skipped.")
    elif not install_python_core():
        print("Core installation failed.")
        return 3

    cameras = probe_cameras_opencv()
    if cameras:
        print("\n[CAMERA] Working camera(s):")
        for idx, w, h in cameras:
            print(f"  camera {idx}: {w}x{h}")
    else:
        maybe_install_droidcam(pm, args.yes)

    if system == "Linux" and session.lower() == "wayland":
        if not command_exists("ydotool"):
            if ask("\nInstall ydotool for low-latency Wayland input?", True, args.yes):
                if install_ydotool(pm):
                    enable_ydotool_service()
        else:
            enable_ydotool_service()

    if not args.no_voice:
        if ask("\nInstall offline voice support (Vosk + microphone capture)?", True, args.yes):
            install_voice()

    microphones = probe_microphones()
    print("\n[MICROPHONE]")
    if microphones:
        for name in microphones[:8]:
            print(" ", name)
    else:
        print("  No microphone detected yet, or sounddevice was not installed.")

    print("\n[FINAL CHECK]")
    cameras = probe_cameras_opencv()
    print("  Cameras:", len(cameras))
    print("  Session:", session)
    print("  ydotool:", "yes" if command_exists("ydotool") else "no")
    print("  Voice libs:", "yes" if importlib.util.find_spec("vosk") else "no")

    print("\nRecommended first run:")
    print(f"  {sys.executable} -m astra_pc --dry-run --show-camera")
    print("\nThen enable real control:")
    print(f"  {sys.executable} -m astra_pc")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
