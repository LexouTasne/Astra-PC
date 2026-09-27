# Android standalone Qwen

Astra Android can operate in two modes:

```text
Mesh online
   ↓
use PC / strongest paired Astra node

Mesh offline
   ↓
Qwen3 0.6B local (when installed)
```

The local model is optional. The base Android app remains usable as a Mesh companion without it.

## Runtime

Astra uses ONNX Runtime Android and a Qwen3-compatible BPE/tokenizer path adapted from Microsoft's MIT-licensed Qwen Android inference example.

The local engine supports:

- Qwen3 0.6B ONNX
- float16 / quantized ONNX variants compatible with the model graph
- streaming token generation
- past-KV caching
- local-only inference
- no API key
- no telemetry from Astra

## Import

The model is deliberately not embedded in the APK.

In Astra Android:

1. Tap **MODEL.ONNX**.
2. Select the Qwen3 `model.onnx` file.
3. Tap **TOKENIZER**.
4. Select the matching `tokenizer.json`.
5. Astra copies both into its private app storage.
6. The status changes to **Modelo local pronto**.

When Mesh is unavailable, normal chat automatically falls back to the local model.

## Hardware

For Qwen3 0.6B, use a phone with enough free RAM. A quantized model is recommended for lower-memory devices.

If the OS kills the app under memory pressure, reconnect to Mesh or use a smaller/quantized ONNX model.

## Why the model is separate

This keeps:

- APK size reasonable
- Mesh-only installs lightweight
- upgrades independent from multi-hundred-MB model downloads
- model choice under user control
- low-end Android phones compatible with the companion UI

## Priority

Astra currently routes:

```text
connected Mesh -> strongest desktop Astra
offline Mesh + local model -> phone Qwen
offline Mesh + no local model -> clear offline error
```

This routing is intentional: the desktop can use the larger vision/reasoning stack, while Android keeps a fast 0.6B fallback.
