# Astra 0.7 Awareness

Astra 0.7 turns the resident daemon into a lightweight awareness layer.

## Core loop

- ContextEngine tracks cheap desktop state.
- Accessibility providers expose structural UI when available.
- SemanticMemory retrieves relevant past context using local embeddings.
- ReferenceResolver helps with phrases such as "isso" and "essa janela".
- BrowserDOM optionally reads a Chromium page through CDP.
- PerceptionFusion combines accessibility data with Qwen-VL screenshots.
- PerformanceGovernor lowers expensive perception work under heavy CPU/RAM load.
- PredictionEngine learns likely context transitions but never executes predicted actions.

## Optional perception

Heavy or hardware-specific systems are off by default:

- gaze estimation
- monocular ONNX depth
- stereo depth with two cameras
- OpenXR bridge
- mobile sensor bridge
- dedicated openWakeWord model

This preserves low idle CPU usage.

## Awareness command

Run the daemon, then:

```bash
python -m astra_pc awareness
```

It returns context, monitors, accessibility state, performance mode, routines, skills and predicted next windows.

## Semantic memory

```bash
python -m astra_pc memory "erro do Practice no git"
```

The default embedding model is `qwen3-embedding:0.6b`. If embeddings are unavailable, Astra falls back to lexical similarity.

## Learn / replay

Explicit observation mode:

```bash
python -m astra_pc learn atualizar-practice
```

Perform the task and press ESC.

Replay later:

```bash
python -m astra_pc replay atualizar-practice
```

Global mouse/keyboard observation is intentionally disabled on unsupported native Wayland setups instead of silently pretending it recorded correctly.

## Mobile companion

```bash
python -m astra_pc mobile
```

Astra prints a random token. A phone/controller can POST local sensor JSON to `/sensor` with that token. The bridge is local infrastructure for gyro/accelerometer/camera companion work.

## Model routing

- fast text/voice -> Qwen3 0.6B
- image/screen/video -> Qwen3-VL 2B
- semantic retrieval -> Qwen3-Embedding 0.6B
- complex text -> optional Qwen3 4B, loaded only on demand when installed

## Safety

Skills go through the central permission layer. Running tests, terminal commands, commits and other consequential actions require confirmation. Destructive autonomous operations remain blocked.
