# Astra architecture

## Core rule

The real-time gesture loop never waits for voice, network, OCR or a language model.

## Runtime lanes

### Lane A — Realtime
Camera -> hand landmarks -> deterministic gesture state machine -> input backend.

### Lane B — Voice
Microphone -> offline STT -> local command router -> explicit tools.

### Lane C — Future Astra Agent
Accessibility tree / screen context -> local planner -> explicit tools -> confirmation layer.

## Spatial direction

Future HUD objects will share a SpatialObject abstraction:
- position
- rotation
- scale
- focus
- grab owner
- gesture bindings

That lets Astra use the same gesture vocabulary for desktop overlays now and OpenXR later.
