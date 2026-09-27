# Astra installer

Run:

```bash
python3 installer.py
```

The installer is deliberately interactive. It explains why a component is useful before asking permission to install it.

## Checks

The installer looks at:

- OS and architecture
- Python compatibility
- desktop session
- package manager
- camera candidates
- actual OpenCV camera capture
- microphone inputs
- Wayland input requirements
- optional voice dependencies

## Core components

### OpenCV
Reads webcam frames.

### MediaPipe
Produces the 21 hand landmarks used by Astra's deterministic gesture engine.

### pynput
Controls mouse and keyboard on Windows/X11.

### ydotool
Used on Wayland for system-level input injection. Fedora packages ydotool directly. A ydotool daemon/service is normally required.

### Vosk + sounddevice
Optional offline voice stack.

## DroidCam fallback

When no camera is usable, Astra offers DroidCam rather than failing immediately.

Windows uses the DroidCam winget package when possible.

Linux resolves the current official package URL from Dev47Apps, installs the desktop client, and can also install its V4L2 loopback video driver.

Kernel modules are special: Secure Boot or immutable/Atomic Linux installations can require additional setup or a reboot. The installer reports this instead of pretending the install succeeded.

## Modes

```bash
python3 installer.py --diagnose-only
python3 installer.py --no-voice
python3 installer.py --yes
```

The installer never intentionally disables Secure Boot or weakens OS security settings.
