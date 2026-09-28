# Astra gestures v2

Astra's gesture system is a deterministic local controller. The LLM does not decide whether a hand movement is a click, scroll or pause gesture.

## Start

Run:

```bash
astra gestures
```

The first run opens the interactive calibration tutorial. Replay it at any time:

```bash
astra gestures --tutorial
```

Show the live camera/debug overlay:

```bash
astra gestures --show-camera
```

Repair the camera + input stack:

```bash
astra setup gestures
```

## Core gestures

| Gesture | Action |
| --- | --- |
| Only index finger raised | Pointer pose / air-mouse when enabled |
| Thumb + index pinch and release | Atomic left click |
| Thumb + index pinch and hold | Drag, only when explicitly enabled |
| Index + middle raised | Vertical scroll |
| Move the two-finger pose upward | Scroll up |
| Move the two-finger pose downward | Scroll down |
| Thumb + middle pinch | Right click |
| Three fingers raised + horizontal motion | Swipe left/right |
| Two open palms move apart/together | Zoom in/out |
| Two open palms rotate around each other | Rotate action |
| One open palm held briefly | Pause/resume gesture control |

Two-hand transforms require **two open hands**, which prevents an accidental second hand entering the camera from stealing pointer/click control.

The open-palm pause gesture requires a short hold. Simply showing an open hand for a moment should not toggle the system.

## Scroll v2

Vertical scroll is no longer based on a single noisy frame. Astra now uses:

- a smoothed hand center based on fingertips + finger bases;
- a deadzone for tiny camera jitter;
- accumulated motion before emitting a wheel step;
- direction reset when the hand reverses;
- a per-frame wheel clamp to prevent runaway scrolling.

On Wayland, negative wheel values are sent after the `--` option terminator:

```text
ydotool mousemove --wheel -- 0 3
ydotool mousemove --wheel -- 0 -3
```

This allows both scroll directions to reach ydotool reliably.

## Interactive calibration tutorial

Tutorial v4 validates the system one gesture at a time:

1. hand framing;
2. index-only pointer pose;
3. left click;
4. scroll up;
5. scroll down;
6. right click;
7. swipe left;
8. swipe right;
9. zoom in;
10. zoom out;
11. rotation;
12. open-palm pause.

If drag is enabled, an extra drag calibration step is inserted.

The tutorial sends **no real mouse or keyboard input**. It only validates recognition.

## Astra voice/chat controls

Gesture modules can be changed while the gesture runtime is running. The state is persisted locally and the runtime notices changes automatically.

Examples:

```text
Astra, desativa todos os gestos.
Astra, ativa os gestos.
Astra, desativa o scroll por gestos.
Astra, ativa o scroll por gestos.
Astra, ativa o cursor por gestos.
Astra, desativa o cursor por gestos.
Astra, ativa o clique direito por gestos.
Astra, desativa o zoom por gestos.
Astra, ativa a rotação por gestos.
Astra, desativa o swipe.
Astra, ativa o drag.
Astra, desativa a pausa por palma.
Astra, status dos gestos.
```

These commands are routed deterministically by the daemon instead of being left to the language model.

The live control file is stored in Astra's local data directory as `gesture-control.json`.

## Air mouse and drag

Air-mouse remains off by default:

```bash
astra gestures --air-mouse
```

Drag remains off by default:

```bash
astra gestures --air-mouse --drag
```

They can also be enabled/disabled live through Astra commands.

## Context-aware actions

Zoom, rotate and swipe are gesture events. The final keyboard binding can change based on the active application using `gesture_profiles` in `config/astra.json`.

Browser profiles, for example, can map swipe to browser back/forward while the default desktop profile can map it to application switching.

## Linux / Wayland

Astra uses ydotool/ydotoold.

Current mouse commands include:

```text
left down   ydotool click 0x40
left up     ydotool click 0x80
left click  ydotool click 0xC0
right click ydotool click 0xC1
wheel up    ydotool mousemove --wheel -- 0 <positive>
wheel down  ydotool mousemove --wheel -- 0 <negative>
```

Astra validates the ydotoold socket with `ydotool debug` before live control.

If input fails:

```bash
astra setup gestures
```

## Camera placement

For better tracking:

- keep wrist and fingertips visible;
- use light from the front or side;
- avoid a very bright background;
- leave some empty space around the hand;
- avoid motion blur;
- for DroidCam, prefer a stable USB/LAN connection.

Tracking now uses MediaPipe model complexity 1 with higher detection/tracking thresholds than the original gesture mode.

## Safety

Astra releases held mouse state when:

- tracking is lost;
- a gesture feature is disabled;
- all gestures are disabled;
- the runtime exits;
- a live control configuration changes.

This prevents a stale drag/button-down from remaining active after a camera or control-state transition.
