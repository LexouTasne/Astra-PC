# Astra Desktop

Astra Desktop is the primary Astra interface.

```bash
astra
```

The terminal interface remains available as:

```bash
astra tui
```

## Design

The shell intentionally follows the polished chat-first language of Hermes Desktop:

- persistent left navigation;
- central conversational workspace;
- contextual status/actions panel;
- soft cards and subtle borders;
- floating composer;
- dark/light themes;
- process output surfaced without requiring a terminal.

The implementation is Astra-specific. It talks to Astra's Python CLI, daemon, voice, gestures and Mesh rather than the Hermes gateway.

The visual derivation is permitted by the Hermes Agent MIT license. See:

- `apps/desktop/NOTICE`
- `apps/desktop/LICENSE-HERMES-MIT.txt`

## Pages

### Chat

Local conversation through the existing Astra daemon/Qwen path. Recent GUI conversations are retained locally in Electron's renderer storage.

### Voice

Start/stop foreground voice mode and run voice setup.

### Gestures

Start safe-mode gestures, replay the tutorial or diagnose camera/MediaPipe/input.

### Devices

Create Mesh pairing codes and list paired devices.

### Setup

Voice, Gestures, Camera, installation destination, Mesh and Git update controls.

### Activity

Live stdout/stderr from processes launched by the GUI.

## First launch

The Python launcher locates npm from PATH and common Linuxbrew/system locations. If Electron has not been installed for this checkout, Astra runs:

```bash
npm install --no-audit --no-fund --package-lock=false
```

inside `apps/desktop`, then launches Electron.

## Development

```bash
cd apps/desktop
npm install
npm start
```

Set these variables when launching manually:

```bash
ASTRA_ROOT=/path/to/Astra-PC
ASTRA_PYTHON=/path/to/Astra-PC/.venv/bin/python
```

## Architecture

Electron main process owns:

- native window;
- folder picker;
- child-process lifecycle;
- Python/Astra command bridge.

Preload exposes only a narrow IPC surface.

The renderer contains no Node.js integration and cannot execute arbitrary shell commands directly.
