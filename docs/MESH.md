# Astra 0.8 Mesh

Astra Mesh connects the same Astra instance across your own devices without turning the project into a self-replicating agent.

## Mental model

```text
                    ASTRA MESH
                       HUB
                       │
         ┌─────────────┼─────────────┐
         │             │             │
       PC #1        Android        PC #2
         │             │             │
   desktop tools    sensors       dev machine
   local AI         voice         files/git
   screen/vision    camera        local AI
```

A device does not join automatically. Pairing is explicit.

## Transport and trust

Desktop Mesh uses:

- HTTPS with a self-signed per-node certificate
- SHA-256 certificate fingerprint pinning
- one-time 6-digit pairing code
- long random per-device token after pairing
- stored token hashes on the PC
- per-device capability scopes
- WebSocket for live events
- mDNS/DNS-SD for discovery on the LAN

The Android app stores its bearer token encrypted with Android Keystore.

Default Android scopes:

```text
assistant.ask
context.read
sensor.write
clipboard.push
camera.snapshot
notifications.receive
```

Android does **not** receive shell/file-delete/password-management authority by pairing.

## Start Mesh

The normal daemon starts Mesh automatically when `mesh.enabled=true`:

```bash
astra daemon --voice
```

Default ports:

```text
127.0.0.1:8765   Astra local IPC
0.0.0.0:8767     Astra Mesh HTTPS/WSS
```

## Pair Android

On the PC:

```bash
astra mesh pair-code
```

Astra prints:

- PC LAN address
- Mesh port
- TLS fingerprint
- one-time code
- terminal QR

Optional PNG:

```bash
astra mesh pair-code --qr ~/.cache/astra-pair.png
```

Open Astra Android and scan the QR.

The code expires after five minutes by default and is single-use.

## Discover nodes

```bash
astra mesh discover
```

The Android app also discovers `_astra-mesh._tcp.local.` nodes with Android NSD.

## Paired devices

```bash
astra mesh devices
```

Revoke a phone/PC:

```bash
astra mesh revoke <device-id>
```

Revocation invalidates the token on the next request/reconnect.

## PC-to-PC pairing

Generate a code on PC A:

```bash
astra mesh pair-code
```

On PC B:

```bash
astra mesh pair <host> <port> <fingerprint> <code> --name "Notebook"
```

The current desktop-to-desktop client intentionally keeps the same trust model as Android.

## Android capabilities

The companion can currently:

- ask the PC Astra questions
- receive replies over WSS
- request current PC context
- stream accelerometer data
- stream gyroscope data
- stream rotation vector data
- send clipboard text to the PC on explicit user action
- take a camera snapshot and upload it to the paired PC
- use Android speech recognition as push-to-talk input
- receive Astra notifications while connected
- discover Astra nodes on the local network

Sensor streaming runs as an Android foreground service only after the user taps **SENSORES ON**.

## Remote use away from home

Mesh does not open a public cloud relay or punch holes through your router.

For remote access, connect both devices through a VPN you control (for example Tailscale/WireGuard), then pair using that reachable VPN address.

Do not port-forward 8767 directly to the public internet.

## Firewall

The installer detects active firewalld/UFW/Windows Firewall and can add a narrow TCP 8767 rule.

mDNS discovery also depends on the OS/network allowing multicast DNS. If discovery is blocked, manual IP + fingerprint + code pairing still works.

## State

Desktop Mesh files:

```text
~/.local/share/astra-pc/mesh/
├── identity.json
├── mesh-cert.pem
├── mesh-key.pem
├── devices.json
├── pairing.json
└── inbox/
```

The private TLS key is created locally and never sent to Android.
