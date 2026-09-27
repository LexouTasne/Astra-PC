# Astra-PC

**Astra** is a fast, local-first desktop assistant for Windows and Linux, built around **gesture control first** and voice/AI second.

The project is designed to feel immediate: moving your hand should move the PC without waiting for an LLM, cloud API, OCR pipeline or remote server.

## Current v0.1

The first working core is already implemented:

- hand tracking with MediaPipe
- index-finger pointer control
- thumb + index pinch for click
- hold pinch to drag
- two-finger scrolling
- open-palm pause/resume
- exponential smoothing + dead-zone against jitter
- native Windows / Linux X11 mouse control through pynput
- Wayland support through ydotool when available
- offline command router
- optional offline Vosk speech recognition
- camera preview only when requested
- dry-run mode for safe testing
- zero API keys

## Fast path

```text
webcam
  -> 21 hand landmarks
  -> deterministic gesture state machine
  -> native OS input
```

That path contains **no language model**.

Voice and future AI run separately, so they cannot stall pointer movement.

## Install

Recommended: Python 3.11 or 3.12.

```bash
git clone https://github.com/LexouTasne/Astra-PC
cd Astra-PC
python -m venv .venv
```

Linux:

```bash
source .venv/bin/activate
pip install -e .
python -m astra_pc
```

Windows:

```powershell
.venv\Scripts\activate
pip install -e .
python -m astra_pc
```

Debug without controlling your PC:

```bash
python -m astra_pc --dry-run --show-camera
```

## Linux Wayland

Astra tries to use `ydotool` under Wayland. If your compositor/XWayland allows pynput, Astra can fall back automatically.

For multi-monitor Wayland setups you can explicitly define the desktop size:

```bash
ASTRA_SCREEN_SIZE=3200x1080 python -m astra_pc
```

## Optional offline voice

```bash
pip install -e ".[voice]"
python -m astra_pc --voice-model /path/to/vosk-model
```

No OpenRouter, OpenAI or other API key is required.

Example local commands already routed:

- "abra o navegador"
- "abra o terminal"
- "pausar controle"
- "retomar controle"

## Default gestures

| Gesture | Action |
|---|---|
| Index finger only | Move pointer |
| Thumb + index pinch | Click |
| Hold pinch | Drag |
| Index + middle fingers | Scroll |
| Open palm | Pause / resume |

Thresholds are configurable in `config/astra.json`.

## Architecture

```text
Astra
├── Realtime lane
│   ├── camera
│   ├── hand tracker
│   ├── gesture engine
│   └── native input backend
│
├── Voice lane (optional)
│   ├── microphone
│   ├── Vosk STT
│   └── local command router
│
└── Future Astra Agent
    ├── accessibility/screen context
    ├── local planner
    ├── explicit tool layer
    ├── spatial HUD
    └── 2D/3D workspace
```

## Performance philosophy

Astra is being built in this order:

1. latency
2. reliability
3. natural gestures
4. visual polish
5. AI complexity

Default choices are intentionally light:

- 640x360 camera processing
- 30 FPS target
- MediaPipe model complexity 0
- one-frame camera buffer
- no landmark drawing unless debug mode is enabled
- O(1) pointer smoothing
- voice isolated in its own daemon thread
- no mandatory AI model in RAM

## Roadmap

### Phase 1 — Gesture core
- [x] hand tracking
- [x] pointer
- [x] click
- [x] drag
- [x] scroll
- [x] pause
- [x] Windows/X11 backend
- [x] Wayland backend

### Phase 2 — Natural interaction
- [ ] right click gesture
- [ ] two-hand zoom
- [ ] two-hand rotation
- [ ] swipe actions
- [ ] per-app/context-aware gesture profiles
- [ ] user-recorded gestures

### Phase 3 — Astra Voice
- [x] offline STT adapter
- [x] local command router
- [ ] wake word "Astra"
- [ ] local TTS
- [ ] richer command grammar

### Phase 4 — Spatial desktop
- [ ] transparent HUD
- [ ] radial hand menu
- [ ] window grabbing/snapping
- [ ] floating system panels
- [ ] virtual 2D/3D objects

### Phase 5 — Astra Agent
- [ ] accessibility-tree understanding
- [ ] local-only LLM adapter
- [ ] planner + explicit tools
- [ ] safe confirmations for destructive actions
- [ ] memory and custom routines

### Phase 6 — XR
- [ ] OpenXR bridge
- [ ] headset hand tracking
- [ ] true spatial workspace

## Project docs

- `docs/ARCHITECTURE.md`
- `docs/PERFORMANCE.md`

## Privacy

The gesture core processes webcam frames locally. Astra does not require uploading webcam frames or microphone audio to a cloud service.

## License

MIT
