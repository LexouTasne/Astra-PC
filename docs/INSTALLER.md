# Astra installer

Astra 0.8 uses a two-stage installer so it does not depend on the Python version that happens to be installed by the operating system.

## One-command install

### Linux / Bazzite / Fedora Atomic / macOS

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/LexouTasne/Astra-PC/main/install.sh)
```

### Windows PowerShell

```powershell
irm https://raw.githubusercontent.com/LexouTasne/Astra-PC/main/install.ps1 | iex
```

### Full install

Linux/macOS:

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/LexouTasne/Astra-PC/main/install.sh) --full
```

Windows:

```powershell
$env:ASTRA_FULL="1"; irm https://raw.githubusercontent.com/LexouTasne/Astra-PC/main/install.ps1 | iex
```

## Installation order

```text
repository
  ↓
uv
  ↓
managed Python 3.12
  ↓
Astra .venv
  ↓
core + Mesh
  ↓
camera/input diagnostics
  ↓
voice
  ↓
accessibility
  ↓
Ollama/Qwen
  ↓
firewall rule for Mesh
  ↓
autostart
  ↓
Astra daemon
```

The system Python is not replaced.

A host with Python 3.14, for example, is automatically re-launched through Astra's isolated Python 3.12 runtime.

## What gets checked

- OS and CPU architecture
- system/managed Python
- desktop session
- package manager
- immutable Fedora/Bazzite status
- cameras and real OpenCV capture
- microphones
- X11 / Wayland
- ydotool binary + daemon/socket
- MediaPipe platform support
- accessibility backend
- Ollama availability
- Astra local models
- Astra Mesh packages
- Mesh TCP port
- active firewall
- optional wake-word/browser extras
- optional ComfyUI

## Astra command

The installer creates a per-user launcher:

```bash
astra
```

Linux/macOS path:

```text
~/.local/bin/astra
```

Windows path:

```text
%LOCALAPPDATA%\Astra-PC\bin\astra.cmd
```

On Windows the installer also adds that directory to the user PATH.

## Bazzite / Atomic Linux

Astra avoids modifying the immutable OS base by default.

It prefers:

- managed Python through `uv`
- Python virtual environment in the repo
- Homebrew for Ollama when available
- existing system tools
- visual fallback if an optional system integration is unavailable

`rpm-ostree` layering only happens when explicitly requested:

```bash
python installer.py --allow-layering
```

This also applies to DroidCam kernel/build dependencies.

## Wayland

Astra checks more than the presence of the `ydotool` executable.

It verifies:

- `ydotool`
- `ydotoold`
- expected socket/process state

The installer tries both common service names:

```text
ydotool.service
ydotoold.service
```

If native Wayland injection is unavailable, Astra can still run AI, voice, Mesh, screen understanding and other non-input features.

## Astra Mesh firewall

Mesh defaults to:

```text
TCP 8767
```

When firewalld, UFW or Windows Firewall is active, the installer can create a narrow inbound TCP rule for that port.

The local daemon IPC remains bound to loopback:

```text
127.0.0.1:8765
```

## Core modes

```bash
python installer.py --diagnose-only
python installer.py --yes
python installer.py --no-voice
python installer.py --no-ai
python installer.py --no-mesh
python installer.py --awareness-extras
python installer.py --strong-ai
python installer.py --media
python installer.py --autostart
python installer.py --start
python installer.py --full
```

`--full` enables the optional strong local model, Awareness extras, media generation setup, autostart and immediate startup.

## Camera fallback

If no usable camera is detected, Astra offers DroidCam.

On immutable Linux, the desktop DroidCam client may be installed while its kernel/V4L2 driver is skipped unless the user explicitly allows OS layering.

## Security

The installer does not intentionally:

- disable Secure Boot
- disable firewall protection
- replace the operating-system Python
- expose Astra local IPC to the network
- grant Android devices destructive PC permissions

Mesh pairing remains explicit even after installation.


## Guided camera setup

Use:

```bash
astra setup camera
```

This is interactive by default. Astra asks before installing DroidCam, loading a kernel camera module, changing an immutable Bazzite host, launching DroidCam, or waiting for phone video.

The camera path is validated by actual decoded OpenCV frames, not merely the presence of `/dev/video0`.

On Linux Astra prefers an already installed standard `v4l2loopback` module because DroidCam supports it directly. If unavailable, Astra can fall back to DroidCam's own `v4l2loopback_dc` installer.

On Bazzite/Fedora Atomic, Astra first tries an existing/prebuilt loopback module. Host layering is never silently performed; interactive mode asks first, while non-interactive `--yes` still requires `--allow-layering` for immutable-host changes.

After DroidCam is launched, Astra can wait for the phone and repeatedly probe until real frames arrive.


### Network discovery and manual IP

DroidCam discovery is bounded to 10 seconds by default.

Astra checks, in order:

- an endpoint passed with `--droidcam`;
- the last successfully used endpoint;
- known LAN neighbours;
- the local private subnet in parallel on port `4747`.

If interactive discovery finds nothing, Astra offers:

```text
1 - Enter IP:port manually
2 - Search the network again
3 - Wait for video without network discovery
0 - Cancel
```

Direct endpoint:

```bash
astra setup camera --droidcam 192.168.1.50:4747
```

Custom scan window:

```bash
astra setup camera --scan-timeout 5
```

The endpoint is only remembered after Astra successfully starts the DroidCam CLI path; the next setup attempts that saved endpoint before scanning.
