# Astra Android

The Android companion lives in `android/`.

## Compatibility

- Android 8.0+ (API 26)
- target/compile API 37
- JDK 17 for local builds
- Android Gradle Plugin 9.4
- Gradle 9.6
- Jetpack Compose / Material 3

On Android 17, Astra requests the runtime local-network permission before discovering or connecting to LAN nodes.

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
- Android SDK API 37
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
