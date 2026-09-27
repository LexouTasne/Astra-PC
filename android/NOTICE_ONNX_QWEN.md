# Android local Qwen attribution

Astra's optional Android ONNX Qwen runtime in:

```text
android/app/src/main/java/dev/lex/astra/localai/
```

contains code adapted from Microsoft's **onnxruntime-inference-examples** repository,
specifically the Android Qwen QA example.

Upstream project:

```text
https://github.com/microsoft/onnxruntime-inference-examples
```

Upstream license: MIT.

Astra changes include:

- package integration into `dev.lex.astra.localai`
- loading imported model/tokenizer files from app-private storage
- Astra-specific Qwen3 0.6B configuration
- local/Mesh routing
- model lifecycle management
- Android UI integration

The Qwen model itself is not bundled in the Astra APK and retains its own upstream license.
