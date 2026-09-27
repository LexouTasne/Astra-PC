# Astra-PC

**Astra** is a fast, local-first desktop assistant for Windows and Linux built around **gesture control first** and voice/AI second.

The project is designed so hand movement never waits for an LLM, cloud API, OCR pipeline or remote server.

## Astra v0.2

Implemented now:

- real-time MediaPipe hand tracking
- index-finger pointer control
- thumb + index pinch for click
- hold pinch to drag
- thumb + middle pinch for right click
- two-finger scrolling
- three-finger horizontal swipe actions
- two-hand zoom detection
- two-hand rotation detection
- configurable gesture -> hotkey mappings
- open-palm pause/resume
- cursor smoothing + dead-zone
- Windows / Linux X11 input via pynput
- Linux Wayland backend through ydotool
- optional offline Vosk voice recognition
- local command router with no API key
- guided `installer.py` with hardware checks and camera fallback
- dry-run mode for safe testing

## Why it stays fast

```text
webcam
  -> 21 hand landmarks
  -> deterministic gesture state machine
  -> native OS input
```

The real-time lane contains **no language model**.

Voice and future AI run separately, so the cursor/gestures keep responding while Astra is doing higher-level work.

## Recommended installation

Clone the repository and run the guided installer:

```bash
git clone https://github.com/LexouTasne/Astra-PC
cd Astra-PC
python3 installer.py
```

On Windows:

```powershell
py installer.py
```

The installer explains each component before installing it.

It checks:

- operating system and architecture
- supported Python version
- X11 / Wayland session
- package manager
- camera devices
- whether OpenCV can actually read the camera
- microphones
- ydotool availability on Wayland
- offline voice dependencies
- DroidCam fallback when no usable camera exists

Diagnostic only:

```bash
python3 installer.py --diagnose-only
```

Install recommended items without individual confirmations:

```bash
python3 installer.py --yes
```

Skip voice:

```bash
python3 installer.py --no-voice
```

## Camera fallback

If Astra cannot find a usable camera, the installer offers **DroidCam**.

### Windows

The installer uses the official winget package when winget is available.

### Linux

The installer resolves the current Linux package from Dev47Apps' official DroidCam page at install time.

It can install:

1. DroidCam desktop client
2. build/kernel dependencies when needed
3. DroidCam V4L2 video driver

On Fedora Atomic/Bazzite, package layering or kernel-module installation can require a reboot.

## Safe first test

Do this first:

```bash
python -m astra_pc --dry-run --show-camera
```

Astra detects your hands and gestures but does **not** control the computer.

Then:

```bash
python -m astra_pc
```

## Gestures

| Gesture | Action |
|---|---|
| Index finger only | Move cursor |
| Thumb + index pinch | Left click |
| Hold thumb + index pinch | Drag |
| Thumb + middle pinch | Right click |
| Index + middle | Scroll |
| Index + middle + ring horizontal movement | Swipe |
| Two hands move apart/together | Zoom |
| Two hands rotate relative to each other | Rotation event |
| Open palm | Pause/resume |

The thresholds and mappings live in `config/astra.json`.

Default v0.2 mappings:

- two-hand spread -> `Ctrl + +`
- two-hand close -> `Ctrl + -`
- swipe right -> `Alt + Tab`
- swipe left -> `Alt + Shift + Tab`

Rotation is detected already, but its hotkey mapping is empty by default because there is no universal desktop "rotate object" shortcut. It is ready for the future spatial workspace and can already be bound manually in the config.

## Linux Wayland

Astra prefers `ydotool` for input injection under Wayland.

On Fedora, ydotool is available as a native package. The installer can install and enable it.

On Bazzite/Fedora Atomic, this may involve `rpm-ostree` package layering and a reboot.

For unusual multi-monitor layouts, the current Wayland backend can be given a combined desktop size:

```bash
ASTRA_SCREEN_SIZE=3200x1080 python -m astra_pc
```

## Offline voice

Install through the guided installer or manually:

```bash
pip install -e ".[voice]"
```

Then provide a local Vosk model:

```bash
python -m astra_pc --voice-model /path/to/vosk-model
```

No OpenRouter, OpenAI or other API key is required.

## Architecture

```text
Astra
├── Realtime lane
│   ├── camera
│   ├── hand tracker
│   ├── one/two-hand gesture engine
│   └── native input backend
│
├── Voice lane (optional)
│   ├── microphone
│   ├── Vosk STT
│   └── local command router
│
└── Astra Agent (next)
    ├── accessibility / screen context
    ├── local planner
    ├── explicit tools
    ├── safety confirmation layer
    ├── spatial HUD
    └── 2D/3D workspace
```

## Performance philosophy

Order of priority:

1. latency
2. reliability
3. natural gestures
4. visual polish
5. AI complexity

Defaults are intentionally light:

- 640x360 camera processing
- 30 FPS target
- MediaPipe model complexity 0
- one-frame camera buffer
- no landmark drawing unless debug preview is enabled
- O(1) pointer smoothing
- voice isolated in a daemon thread
- no mandatory AI model in RAM

## Roadmap

### v0.2 — Natural interaction
- [x] right click
- [x] swipe actions
- [x] two-hand zoom
- [x] two-hand rotation detector
- [x] configurable gesture actions
- [x] guided installer
- [x] camera/mic diagnostics
- [x] DroidCam fallback
- [ ] improve two-hand gesture hysteresis
- [ ] per-app gesture profiles
- [ ] user-recorded gestures

### v0.3 — Astra interface
- [ ] transparent HUD
- [ ] radial hand menu
- [ ] floating hardware monitor
- [ ] window grabbing/snapping
- [ ] camera calibration UI
- [ ] gesture calibration UI

### v0.4 — Astra Voice
- [ ] wake word "Astra"
- [ ] local TTS
- [ ] richer command grammar
- [ ] voice + gesture combinations

### v0.5 — Astra Agent
- [ ] accessibility-tree understanding
- [ ] local-only LLM adapter
- [ ] planner + explicit tool layer
- [ ] confirmations for destructive actions
- [ ] memory and custom routines

### Future XR
- [ ] OpenXR bridge
- [ ] headset hand tracking
- [ ] true spatial workspace
- [ ] direct 3D object manipulation

## Privacy

Gesture processing is local. Astra does not require uploading webcam frames or microphone audio to a cloud service.

## License

MIT
