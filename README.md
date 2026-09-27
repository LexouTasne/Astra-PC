# Astra-PC

**Astra** is a fast, local-first desktop assistant for Windows and Linux.

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

## Default local AI

Astra uses **Qwen3-VL 2B Instruct** through Ollama by default:

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
      MediaPipe          Vosk          Qwen3-VL 2B
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

## Install

Recommended:

```bash
git clone https://github.com/LexouTasne/Astra-PC
cd Astra-PC
python3 installer.py
```

The installer checks and can configure:

- supported Python
- camera availability
- real OpenCV camera capture
- microphones
- X11 / Wayland
- ydotool
- Vosk
- local TTS
- Ollama
- Qwen3-VL 2B
- DroidCam fallback
- optional ComfyUI setup

Useful installer modes:

```bash
python3 installer.py --diagnose-only
python3 installer.py --no-voice
python3 installer.py --no-ai
python3 installer.py --media
python3 installer.py --yes
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

Install voice support with the installer, provide a local Vosk model, then:

```bash
python -m astra_pc voice --voice-model /path/to/vosk-model
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

### Astra 0.4

- [x] gesture engine
- [x] two-hand interaction
- [x] Windows/X11 control
- [x] Wayland backend
- [x] installer + diagnostics
- [x] DroidCam fallback
- [x] offline voice STT
- [x] offline TTS
- [x] Qwen3-VL 2B local brain
- [x] image understanding
- [x] screen understanding
- [x] video understanding
- [x] constrained visual desktop agent
- [x] ComfyUI workflow runner
- [x] generic image workflow
- [x] generic video-workflow support
- [ ] transparent spatial HUD
- [ ] radial gesture menu
- [ ] per-app gesture context
- [ ] user-recorded gestures
- [ ] accessibility-tree backend
- [ ] OpenXR bridge

## Privacy

Camera frames, screenshots, microphone audio and AI prompts can all stay on the local machine when using the default local stack.

## License

MIT
