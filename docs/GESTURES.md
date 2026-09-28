# Astra gestures

Astra's gesture mode is designed to be taught inside the application.

## First run

Run:

```bash
astra gestures
```

If the current tutorial version has not been completed, Astra automatically opens the interactive camera tutorial before enabling real clicks/scroll/actions.

Replay it at any time:

```bash
astra gestures --tutorial
```

Repair/check the complete stack:

```bash
astra setup gestures
```

Skip the tutorial only when you already know the controls:

```bash
astra gestures --no-tutorial
```

## Core gestures

| Gesture | Action |
| --- | --- |
| Only index finger raised | Move pointer |
| Thumb + index pinch and release | Left click |
| Hold thumb + index pinch | Drag |
| Index + middle raised, other fingers down | Scroll |
| Thumb + middle pinch | Right click |
| Open palm once | Pause/resume gesture control |
| Two hands move apart/together | Zoom in/out |
| Rotate the line between two hands | Rotate |
| Three raised fingers + fast horizontal motion | Swipe left/right |

The tutorial validates the seven core gestures one by one. Advanced two-hand zoom/rotation and swipe are shown after the core tutorial.

## Safety during tutorial

The tutorial detects all gestures but only sends pointer movement to the operating system. It does not emit click/scroll/right-click while teaching, so learning the gesture cannot accidentally activate something on the desktop.

## Linux / Wayland

Astra uses ydotool/ydotoold. Current ydotool uses:

```text
left down   ydotool click 0x40
left up     ydotool click 0x80
right click ydotool click 0xC1
wheel       ydotool mousemove --wheel 0 <amount>
```

Astra validates the ydotoold socket with `ydotool debug` before live control. It no longer silently falls back to pynput on Wayland.

If gestures fail:

```bash
astra setup gestures
```

If that reports ydotool/ydotoold problems, fix/restart the service and rerun the setup.

## KDE multi-monitor

On KDE Wayland, Astra falls back to `kscreen-doctor -o` when generic monitor enumeration is unavailable. This lets the pointer mapper use the actual logical monitor geometry instead of assuming 1920x1080.

## Camera placement

For reliable tracking:

- keep the full hand inside the frame;
- use front/side lighting instead of a bright light directly behind the hand;
- place the camera far enough away to show wrist + fingertips;
- avoid very fast motions while learning;
- for DroidCam, prefer a stable LAN/USB connection.

## Preview

Use:

```bash
astra gestures --show-camera
```

The preview displays the recognized gesture label, hand count, pause state and key hand landmarks.

Press `Q` or `Esc` in the preview, or `Ctrl+C` in the terminal, to stop.
