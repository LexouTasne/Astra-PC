# Performance

Astra should feel immediate before it looks impressive.

## Default target

- 640x360 camera processing
- 30 FPS target
- MediaPipe model complexity 0
- camera buffer of one frame
- no landmark drawing unless debug preview is enabled
- O(1) pointer smoothing
- voice on a daemon thread
- AI models loaded only when explicitly enabled

## Principle

The pointer/click/drag/scroll path must stay deterministic and local. A language model should never sit between a hand movement and the OS input event.
