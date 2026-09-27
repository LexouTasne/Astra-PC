from __future__ import annotations

PROTOCOL_VERSION = 1

CLIENT_TYPES = {
    "hello",
    "ping",
    "ask",
    "context",
    "sensor",
    "clipboard.push",
    "camera.snapshot",
}

SERVER_TYPES = {
    "welcome",
    "pong",
    "reply",
    "context",
    "ack",
    "error",
    "notification",
    "device.command",
}


def envelope(message_type: str, **payload):
    return {
        "v": PROTOCOL_VERSION,
        "type": message_type,
        **payload,
    }
