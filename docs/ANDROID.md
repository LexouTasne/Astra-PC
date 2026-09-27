# Astra Android

The Android companion lives in `android/`.

## Compatibility

- Android 8.0+ (API 26)
- target/compile API 36
- JDK 17 for local builds
- Android Gradle Plugin 9.4
- Gradle 9.6
- Jetpack Compose / Material 3

Astra targets stable Android 16/API 36. The manifest and runtime flow are already prepared for Android 17's ACCESS_LOCAL_NETWORK permission when the platform enforces it.

## Install an APK from GitHub Actions

Every CI run builds:

```text
android/app/build/outputs/apk/debug/app-debug.apk
```

and uploads it as the artifact:

```text
astra-android-debug
```

GitHub Actions debug APKs are intended for testing. They are not a Play Store release build.

## Build with Android Studio

1. Clone Astra-PC.
2. Open the `android/` directory in Android Studio.
3. Let Gradle sync.
4. Select your Android phone.
5. Run `app`.

## Build from terminal

Requirements:

- JDK 17
- Android SDK API 36
- Android build tools 36.0.0
- Gradle 9.6

Then:

```bash
gradle -p android :app:assembleDebug
```

APK:

```text
android/app/build/outputs/apk/debug/app-debug.apk
```

Install with ADB:

```bash
adb install -r android/app/build/outputs/apk/debug/app-debug.apk
```

## First pairing

PC:

```bash
astra mesh pair-code
```

Android:

1. Open Astra.
2. Grant local-network access when Android asks.
3. Tap **ESCANEAR QR DO PC**.
4. Scan the QR printed by Astra.
5. The app pins the PC certificate fingerprint before sending the pairing code.
6. Astra issues a per-device token and stores only its hash on the desktop.
7. Android stores the token encrypted through Android Keystore.

Manual pairing is also available with:

- PC IP/host
- port (default 8767)
- TLS fingerprint
- six-digit code

## Controls

### VOZ

Launches Android's speech recognizer and sends the recognized text to the paired PC.

Astra asks Android to prefer offline recognition, but actual offline availability depends on the speech engine installed on the phone.

### CÂMERA

Uses the system camera flow to capture a snapshot and uploads the JPEG over the pinned HTTPS connection.

### PC

Requests current Astra Awareness/context from the PC.

### SENSORES ON

Starts a foreground service and streams:

- accelerometer
- gyroscope
- rotation vector

approximately up to 20 updates/second per sensor.

### CLIPBOARD

Sends the current Android clipboard to the paired PC only when the user taps the button.

Android clipboard access is intentionally not monitored continuously.

## Security notes

The app rejects a server certificate whose SHA-256 fingerprint does not match the fingerprint obtained during pairing.

If you reinstall/recreate the PC Mesh identity, pair the phone again.

Use **REMOVER PAREAMENTO** on Android and `astra mesh revoke` on PC when removing a device.


## Standalone local AI

The phone does not have to be only a remote control.

Astra Android supports an optional local **Qwen3 0.6B** fallback through ONNX Runtime:

```text
Mesh connected -> desktop/strong node
Mesh offline + model installed -> Qwen3 on the phone
Mesh offline + no model -> companion UI remains available but AI requests explain that no brain is reachable
```

In the app:

1. Tap **MODEL.ONNX** and select the Qwen3 ONNX model.
2. Tap **TOKENIZER** and select the matching `tokenizer.json`.
3. Wait for **Modelo local pronto**.
4. Disconnect from Mesh or leave the PC offline.
5. Chat normally; the button changes to **RODAR NO CELULAR**.

Recommended matching files and model details are in `docs/ANDROID_LOCAL_AI.md`.

The model files are copied into Android app-private storage. They are not bundled into Git and are not uploaded to the PC automatically.
