# Astra-PC

**Astra** is a fast, local-first desktop assistant for Windows, Linux/Bazzite and macOS.

It combines:

- real-time hand gestures
- offline voice
- local multimodal AI
- screen understanding
- image understanding
- video understanding
- local desktop-agent actions
- optional local image/video generation through ComfyUI

No OpenRouter/OpenAI/API key is required.

## Astra 0.8 — Mesh

Astra is now designed as a **multi-device assistant**.

```text
                       ASTRA MESH
                           │
          ┌────────────────┼────────────────┐
          │                │                │
        PC #1          Android            PC #2
          │                │                │
       local AI         sensors         another node
       gestures         voice           dev/workstation
       screen           camera          local tools
       files/git        clipboard       context
          │                │                │
          └────────────────┼────────────────┘
                           │
                  one shared Astra
```

Devices do not join automatically. Pairing is explicit and authenticated.

### What Android can do

- chat with the same Astra running on the PC
- push-to-talk voice commands
- discover Astra PCs on the LAN
- pair by QR or manual code
- stream accelerometer / gyroscope / rotation data
- send clipboard text on explicit user action
- send a camera snapshot to Astra
- request PC Awareness/context
- receive Astra notifications while connected

### Secure pairing

Mesh uses:

- HTTPS + WSS
- per-PC TLS certificate
- SHA-256 certificate fingerprint pinning
- one-time six-digit pairing codes
- random per-device tokens
- token hashes stored on the PC
- Android Keystore for the phone token
- per-device capability scopes

Default Android pairing does **not** grant shell, destructive file access, password management, or unrestricted PC control.

Full docs:

- `docs/MESH.md`
- `docs/ANDROID.md`


## Install in one command

The universal bootstrap does the steps in order:

```text
download/update Astra
      ↓
install/find uv
      ↓
install managed Python 3.12
      ↓
create .venv
      ↓
run hardware diagnostics
      ↓
install Astra + voice + local AI
      ↓
configure autostart
      ↓
start Astra
```

### Linux / Bazzite / Fedora Atomic / macOS

Recommended install:

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/LexouTasne/Astra-PC/main/install.sh)
```

Everything, including the optional 4B model and ComfyUI setup:

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/LexouTasne/Astra-PC/main/install.sh) --full
```

### Windows PowerShell

Recommended install:

```powershell
irm https://raw.githubusercontent.com/LexouTasne/Astra-PC/main/install.ps1 | iex
```

Full install:

```powershell
$env:ASTRA_FULL="1"; irm https://raw.githubusercontent.com/LexouTasne/Astra-PC/main/install.ps1 | iex
```

The bootstrap can work even when the system Python is newer than Astra's tested runtime.
For example, a machine with Python 3.14 does **not** need to downgrade or replace it:
Astra installs its own isolated Python 3.12 under `.venv`.

### Already cloned the repository?

Just run:

```bash
python installer.py --yes --autostart --start --awareness-extras
```

If that `python` is 3.13/3.14 or another unsupported runtime, `installer.py`
automatically provisions Python 3.12 with `uv` and relaunches itself.

Full setup from an existing clone:

```bash
python installer.py --full
```

### Manual install

If you do not want to execute a remote bootstrap script:

```bash
git clone --recursive https://github.com/LexouTasne/Astra-PC.git
cd Astra-PC
python installer.py
```

The guided installer can bootstrap the isolated runtime itself.

## Connect Android

After desktop installation, Astra Mesh starts with the normal daemon.

Create a one-time pairing QR:

```bash
astra mesh pair-code
```

Optional PNG:

```bash
astra mesh pair-code --qr ~/.cache/astra-pair.png
```

Then install/open the Android companion and scan the QR.

### Android APK

Every GitHub Actions run builds a debug APK artifact named:

```text
astra-android-debug
```

Local build:

```bash
gradle -p android :app:assembleDebug
```

APK path:

```text
android/app/build/outputs/apk/debug/app-debug.apk
```

See `docs/ANDROID.md` for the complete guide.

## Compatibility

| Platform | Astra core | Voice / AI | Gestures | Mesh | Notes |
|---|---:|---:|---:|---:|---|
| Windows 10/11 x64 | ✅ | ✅ | ✅ | ✅ | Native input via pynput/UI Automation |
| Windows ARM64 | ✅ | ✅ | ✅ | ✅ | Current MediaPipe publishes Windows ARM64 wheels |
| Linux x86_64 glibc | ✅ | ✅ | ✅ | ✅ | X11 native; Wayland prefers ydotool |
| Linux ARM64 glibc | ✅ | ✅ | ✅ | ✅ | Current MediaPipe publishes Linux ARM64 wheels |
| Bazzite / Fedora Atomic | ✅ | ✅ | ✅ | ✅ | User-space Python/Ollama preferred; no rpm-ostree layering by default |
| macOS Apple Silicon | ✅ | ✅ | ✅ | ✅ | Grant Accessibility/camera/microphone permissions when requested |
| macOS Intel | ✅ | ✅ | ⚠️ | ✅ | Gesture/pose support depends on MediaPipe availability |

Astra targets a **managed Python 3.12 runtime** regardless of the host Python version.
This avoids breaking the OS Python and makes machines with Python 3.13/3.14 usable without a downgrade.

On immutable Linux such as Bazzite, Astra avoids `rpm-ostree` package layering by default.
If a system-level dependency is truly required, the installer explains it and only layers when
explicitly run with `--allow-layering`.


## Astra 0.7 — Awareness

Astra now behaves more like a resident operating-system assistant than a chatbot.

New in 0.7:

- semantic local memory with `qwen3-embedding:0.6b`
- response cache for repeated stable questions
- context-aware reference resolution for "isso/aquilo/essa janela"
- accessibility + screenshot fusion
- optional browser DOM through Chromium CDP
- optional strong Qwen3 4B routing for complex text
- adaptive performance governor
- true multi-monitor geometry
- context-specific gesture mappings
- native active-window snap/move/maximize/minimize skill
- continuous voice conversation window
- optional dedicated openWakeWord model for "Astra"
- action verification in the visual desktop agent
- clipboard, notifications, coding and controlled terminal skills
- plug-in Skill SDK
- explicit "learn this" mouse/keyboard recorder + replay
- optional gaze estimation
- optional monocular/stereo depth
- optional multi-camera support
- optional OpenXR bridge
- local mobile sensor companion bridge

Start the full resident mode:

```bash
python -m astra_pc daemon --voice
```

Inspect what Astra currently knows:

```bash
python -m astra_pc awareness
```

Semantic memory search:

```bash
python -m astra_pc memory "aquele erro do Practice no git"
```

Teach an explicit desktop routine by demonstration:

```bash
python -m astra_pc learn atualizar-practice
# perform the task, then press ESC

python -m astra_pc replay atualizar-practice
```

Run the phone/sensor bridge:

```bash
python -m astra_pc mobile
```

See `docs/AWARENESS.md` and `docs/SKILLS.md`.


## Astra 0.6 — Resident Core

Astra can now run as a resident local service instead of reloading itself for every request.

```text
                    ASTRA DAEMON
                         │
        ┌────────────────┼─────────────────┐
        │                │                 │
     Context          Event Bus         Memory
        │                │              SQLite
        │                │                 │
        └─────────── Planner ──────────────┘
                         │
                  Permission Layer
                         │
          ┌──────────────┼──────────────┐
          │              │              │
       Skills       Accessibility     Vision
          │          UIA / AT-SPI     fallback
          │
   Apps / Files / Git /
   System / Media / Routines
```

Start the resident core:

```bash
python -m astra_pc daemon --voice
```

Ping it:

```bash
python -m astra_pc ctl ping
```

Ask through the already-hot daemon:

```bash
python -m astra_pc ctl ask "status do PC"
```

Normal `astra ask` and `astra chat` automatically try the daemon first and fall back to local mode when it is not running.

### Context and accessibility

The daemon continuously keeps cheap context such as:

- active window/process
- operating system/session
- current Astra profile
- structural UI elements when Windows UI Automation or Linux AT-SPI is available

Visual Qwen analysis remains a fallback for things accessibility APIs cannot describe.

### Profiles

```bash
python -m astra_pc profile dev
python -m astra_pc profile gaming
python -m astra_pc profile study
python -m astra_pc profile default
```

Voice also understands exact profile commands such as:

```text
Astra, modo dev
Astra, modo gaming
Astra, modo estudo
```

### Persistent routines

Save a routine:

```bash
python -m astra_pc routine save dev '[{"skill":"apps","action":"open_app","args":{"name":"vscode"}},{"skill":"apps","action":"open_app","args":{"name":"terminal"}}]'
```

Run it:

```bash
python -m astra_pc routine run dev
```

The daemon stores routines and recent context in a local SQLite database.

### Skills

Current resident skills include:

- apps and URLs
- live CPU/RAM/process status
- media playback and volume
- safe file search/read inside the user's home
- Git status/diff/branch and confirmed commits
- persistent routines

Actions pass through a central permission layer. Destructive or unknown actions are not silently executed.

### Proactive events

The resident core watches lightweight system thresholds without calling an LLM. CPU/RAM threshold events enter Astra's event bus and local memory, ready for future notification/routine rules.

### Autostart

The installer can configure the resident daemon to start at login:

```bash
python3 installer.py --autostart
```

Linux uses a user-level systemd service. Windows installs a startup command file.

### Barge-in

While Astra is speaking, saying the wake word again interrupts queued speech. Commands such as:

```text
Astra, para
Astra, silêncio
```

cancel spoken output immediately where the local TTS backend supports cancellation.


## Default local AI

Astra uses two local Qwen models through Ollama:

- **Qwen3 0.6B** for fast text/voice replies
- **Qwen3-VL 2B Instruct** only for screenshots, images, video frames and visual-agent work

Vision model:

```text
qwen3-vl:2b-instruct
```

The quantized Ollama model is about 1.9 GB and supports text + image input.

Astra keeps it completely outside the latency-sensitive gesture loop.

## Architecture

```text
                         ASTRA
                           │
           ┌───────────────┼────────────────┐
           │               │                │
       GESTURES          VOICE             AI
           │               │                │
      MediaPipe      faster-whisper     model router
           │               │                │
   deterministic FSM       │       ┌────────┼────────┐
           │               │       │        │        │
     native OS input       │     image    screen    video
                           │                │
                           └────────────── agent
                                            │
                                   constrained tools

Optional heavy lane:

prompt -> ComfyUI -> local image/video model
```

## Installer options

```bash
python installer.py --diagnose-only
python installer.py --yes
python installer.py --autostart --start
python installer.py --strong-ai
python installer.py --awareness-extras
python installer.py --media
python installer.py --full
```

`--full` enables the optional strong model, Awareness extras, ComfyUI setup,
autostart, and starts Astra after installation.

On immutable Linux, system package layering is disabled unless you explicitly add:

```bash
python installer.py --allow-layering
```

## Gesture control

Safe test:

```bash
python -m astra_pc gestures --dry-run --show-camera
```

Real control:

```bash
python -m astra_pc gestures
```

Implemented gestures:

| Gesture | Action |
|---|---|
| index finger | pointer |
| thumb + index pinch | left click |
| hold pinch | drag |
| thumb + middle pinch | right click |
| index + middle | scroll |
| three-finger horizontal swipe | window switching |
| two hands apart/together | zoom |
| two-hand relative rotation | rotation event |
| open palm | pause/resume |

All thresholds and mappings are configurable in `config/astra.json`.

## Local AI

Text:

```bash
python -m astra_pc ask "Explique o que é Linux Wayland"
```

Interactive chat:

```bash
python -m astra_pc chat
```

Image understanding:

```bash
python -m astra_pc see foto.png "O que tem nessa imagem?"
```

Screen understanding:

```bash
python -m astra_pc screen "O que está acontecendo na minha tela?"
```

Video understanding:

```bash
python -m astra_pc video video.mp4 "Resume esse vídeo" --frames 8
```

Video understanding is intentionally lightweight: Astra samples representative frames instead of loading the whole video into RAM.

## Astra desktop agent

Example:

```bash
python -m astra_pc agent "abra o navegador e vá para github.com"
```

By default Astra asks before every desktop action.

Allowed tool surface:

- click
- right click
- type text
- safe hotkeys
- scroll
- open http/https URL
- wait
- finish

It does **not** receive unrestricted shell access.

To skip per-step confirmation for allowed actions:

```bash
python -m astra_pc agent "abra github.com" --yes
```

The agent is deliberately prevented from autonomously performing irreversible actions such as purchases, password changes, file deletion or sending messages.

## Voice Astra

Astra can operate as a local wake-word assistant.

Fast voice is the default:

```bash
python -m astra_pc voice --engine fast
```

The faster-whisper model remains loaded while Astra is listening. Vosk is still available as a fallback:

```bash
python -m astra_pc voice --engine vosk --voice-model /path/to/vosk-model
```

Example:

```text
"Astra, explica o que é essa janela."

"Astra, o que tem na minha tela?"

"Astra, abra o navegador."
```

The current lightweight wake word is detected from offline Vosk transcription, avoiding another always-running neural model.

## Local image/video generation

Qwen3-VL understands images/video but does not generate pixels.

Astra therefore uses a separate **ComfyUI** backend for local generation.

Optional setup:

```bash
python3 installer.py --media
```

Then place a compatible checkpoint in ComfyUI and set:

```json
"media": {
  "comfyui": {
    "checkpoint": "your-model.safetensors"
  }
}
```

Basic local image generation:

```bash
python -m astra_pc generate "futuristic holographic computer interface"
```

Astra also accepts any ComfyUI API workflow:

```bash
python -m astra_pc generate "cinematic robot walking" --workflow workflows/my-video.json
```

This is how video generation is supported without forcing a giant video model into Astra's core.

## Why generation is separate

Gesture control should remain fast even on modest computers.

The default lanes are lightweight:

- 640x360 camera
- 30 FPS target
- MediaPipe complexity 0
- Qwen model loaded only when AI is requested
- voice on a separate worker
- no diffusion/video model loaded unless generation is explicitly requested

## Linux / Bazzite / Wayland

Astra uses `ydotool` where available under Wayland.

On Bazzite/Fedora Atomic the installer understands `rpm-ostree` and warns when package layering requires a reboot.

For a non-standard multi-monitor virtual desktop:

```bash
ASTRA_SCREEN_SIZE=3200x1080 python -m astra_pc gestures
```

## Current status

### Astra 0.8

- [x] real-time gesture engine
- [x] two-hand zoom/rotation
- [x] multi-monitor geometry
- [x] per-app gesture context
- [x] Windows / X11 input
- [x] Wayland ydotool backend
- [x] Bazzite/Fedora Atomic-aware installer
- [x] automatic isolated Python 3.12 runtime
- [x] one-command Linux/macOS/Windows bootstrap
- [x] DroidCam fallback
- [x] faster-whisper + VAD voice
- [x] continuous conversation + barge-in
- [x] optional dedicated wake word
- [x] optional Piper neural TTS
- [x] local Qwen model routing
- [x] semantic memory + response cache
- [x] accessibility-tree backends
- [x] browser DOM integration
- [x] vision/accessibility fusion
- [x] verified visual desktop agent
- [x] learned mouse/keyboard macro replay
- [x] plug-in Skill SDK
- [x] gaze / pose / multi-camera modules
- [x] depth and stereo-depth extension points
- [x] OpenXR bridge
- [x] spatial workspace model
- [x] mobile sensor bridge
- [x] secure Astra Mesh HTTPS/WSS server
- [x] mDNS discovery
- [x] one-time QR/code pairing
- [x] Android companion app
- [x] Android Keystore token storage
- [x] Android live sensors / clipboard / camera snapshot
- [ ] polished transparent spatial HUD
- [ ] production radial gesture menu
- [ ] calibrated gaze+pinch selection wizard

## Privacy

Camera frames, screenshots, microphone audio and AI prompts can all stay on the local machine when using the default local stack.

## License

MIT


## Ultra-low-latency profile

Astra 0.7 is tuned around a response-time budget instead of maximum model size.

### Voice fast path

```text
microphone
 -> WebRTC VAD (30 ms frames)
 -> end-of-speech after ~330 ms silence
 -> resident faster-whisper
 -> command router OR Qwen3 0.6B
 -> asynchronous local TTS
```

Start it with:

```bash
python -m astra_pc voice --engine fast
```

The first time faster-whisper runs, its selected Whisper model may need to download.
Default is `base`. For lower latency use `tiny`; for better recognition use `small`:

```bash
python -m astra_pc voice --engine fast --whisper-model tiny
python -m astra_pc voice --engine fast --whisper-model small
```

The old Vosk engine remains available:

```bash
python -m astra_pc voice --engine vosk --voice-model /path/to/vosk-model
```

### Latency strategy

- gesture path never touches an LLM
- camera queue stays at one frame
- text requests use 0.6B instead of the vision model
- text context is intentionally small
- voice replies are capped to short responses
- Ollama models use persistent keep-alive
- text model is preloaded before listening starts
- vision model warms in a background thread
- TTS runs outside the reasoning path
- VAD avoids transcribing silence
- video analysis downsamples and samples frames
- generation remains a separate heavy process

### Benchmark

Run:

```bash
python -m astra_pc benchmark
```

It preloads the fast text brain and measures multiple local response rounds.

The **sub-7-second goal is a target, not a universal guarantee**. Actual speed depends on CPU/GPU,
memory bandwidth, model placement and whether a model is already hot in RAM/VRAM. Astra reports
latency so performance can be tuned for the actual machine.


## Optional high-end perception

These features are implemented as opt-in modules so the normal daemon stays light:

- `BodyPoseTracker`: local MediaPipe body pose landmarks.
- `LocalFaceProfiles`: explicit local-only OpenCV LBPH enrollment/recognition.
- `GazeEstimator`: lightweight iris-based gaze direction estimate.
- `DepthEstimator`: user-provided ONNX monocular depth.
- `StereoDepth`: classical two-camera disparity.
- `MultiCamera`: multiple local camera streams.
- `SpatialWorkspace`: common translate/rotate/scale object state for HUD/OpenXR.
- `OpenXRBridge`: optional XR runtime detection/extension point.
- `PiperSpeaker`: optional local neural Piper voice when a model is configured.

None of these are required by the low-latency gesture/voice core.


## Camera / DroidCam repair

Astra no longer assumes that `/dev/video0` is a working camera.

The gesture runtime probes actual video devices and only loads MediaPipe after one produces frames.

Run the guided camera setup:

```bash
astra setup camera
```

The guided flow asks before each relevant step:

1. use an existing working webcam if one exists;
2. install DroidCam if no camera produces frames;
3. reuse an already installed DroidCam client;
4. detect/load `v4l2loopback` or `v4l2loopback_dc`;
5. on Bazzite/Atomic, ask before host package layering;
6. launch DroidCam;
7. wait for the phone connection;
8. verify that OpenCV receives real frames.

For fully automatic recommended answers:

```bash
astra setup camera --yes
```

Host package layering on immutable Linux is still explicit:

```bash
astra setup camera --yes --allow-layering
```

Running just:

```bash
astra
```

opens Astra's lightweight launcher/status menu. It does **not** start gesture tracking blindly.


### Fast DroidCam discovery

Astra no longer waits blindly for a virtual camera.

```bash
astra setup camera
```

The guided setup now:

1. tries a previously saved DroidCam endpoint first;
2. checks known LAN neighbours;
3. scans the local private subnet in parallel on port `4747`;
4. stops automatic discovery after **10 seconds maximum**;
5. if nothing is found, offers a manual `IP:port` prompt;
6. starts `droidcam-cli` directly with the detected v4l2loopback device;
7. verifies real OpenCV frames before declaring success;
8. saves the working endpoint for the next run.

If you already know the phone address, skip discovery completely:

```bash
astra setup camera --droidcam 192.168.1.50:4747
```

Change the address to the one shown by DroidCam on your phone.


## Install anywhere: SSD / HDD / USB

Astra no longer requires `~/Astra-PC`.

### Fresh Linux/macOS install

The normal installer asks for the application folder:

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/LexouTasne/Astra-PC/main/install.sh)
```

Direct path:

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/LexouTasne/Astra-PC/main/install.sh) \
  --dest "/mnt/My SSD/Astra-PC"
```

USB example:

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/LexouTasne/Astra-PC/main/install.sh) \
  --dest "/run/media/$USER/MYUSB/Astra-PC" \
  --portable-data
```

### Move/reinstall an existing Astra

Interactive:

```bash
astra
```

Choose **8 - Instalar/migrar Astra para outra pasta/disco**.

Direct:

```bash
astra setup location "/mnt/My SSD/Astra-PC"
```

Portable data:

```bash
astra setup location "/run/media/$USER/MYUSB/Astra-PC" --portable-data
```

Astra does a safe reinstall into the new destination and rewrites the user launcher/autostart. The old checkout is left untouched until you choose to remove it.

### Storage layout

Astra separates:

```text
Application   source code / Astra package
Runtime       isolated Python 3.12 environment
Data          memory, Mesh identity, skills, macros
Cache         response/cache databases
```

On normal Linux filesystems the runtime can live beside Astra.

On FAT/vfat/exFAT/NTFS-style removable mounts under Linux, Astra automatically keeps the Python runtime on the local user filesystem while leaving the application and optional portable data on the selected drive. This avoids broken executable/symlink semantics on removable filesystems.

Custom advanced paths:

```bash
install.sh --dest /disk/Astra-PC \
  --runtime-dir ~/.local/share/astra-pc/runtime-custom/.venv \
  --data-dir /disk/AstraData \
  --cache-dir /disk/AstraCache
```

If a removable drive is absent, the `astra` launcher prints a clear mount/drive error instead of a Python traceback, and Linux systemd will not start the service while the application path is missing.
