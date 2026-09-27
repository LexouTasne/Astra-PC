from __future__ import annotations

import asyncio
import base64
import json
import ssl
import threading
import time
from pathlib import Path
from typing import Any, Callable

from aiohttp import WSMsgType, web

from .discovery import MeshDiscovery
from .identity import ensure_identity, local_ip
from .pairing import PairingManager
from .protocol import envelope
from .registry import DeviceRegistry


class AstraMeshServer:
    """Authenticated HTTPS/WebSocket bridge between Astra devices."""

    def __init__(
        self,
        *,
        root: str | Path,
        host: str,
        port: int,
        name: str,
        request_handler: Callable[[dict[str, Any]], dict[str, Any]],
        event_handler: Callable[[str, dict[str, Any]], None] | None = None,
    ):
        self.root = Path(root).expanduser()
        self.root.mkdir(parents=True, exist_ok=True)
        self.host = host
        self.port = int(port)
        self.identity = ensure_identity(self.root, name)
        self.registry = DeviceRegistry(self.root / "devices.json")
        self.pairing = PairingManager(self.root / "pairing.json")
        self.request_handler = request_handler
        self.event_handler = event_handler
        self.discovery = MeshDiscovery(
            name=self.identity.name,
            port=self.port,
            node_id=self.identity.node_id,
            fingerprint=self.identity.fingerprint,
        )
        self._loop: asyncio.AbstractEventLoop | None = None
        self._runner: web.AppRunner | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._sockets: dict[str, web.WebSocketResponse] = {}
        self._sockets_lock = threading.RLock()

    @property
    def fingerprint(self) -> str:
        return self.identity.fingerprint

    def pair_code(self, ttl_seconds: int = 300) -> dict[str, Any]:
        data = self.pairing.create(ttl_seconds)
        host = local_ip()
        uri = (
            "astramesh://pair"
            f"?host={host}&port={self.port}"
            f"&fingerprint={self.identity.fingerprint}"
            f"&code={data['code']}&node={self.identity.node_id}"
        )
        return {
            **data,
            "host": host,
            "port": self.port,
            "fingerprint": self.identity.fingerprint,
            "node_id": self.identity.node_id,
            "name": self.identity.name,
            "uri": uri,
        }

    def pair_qr(self, output: str | Path) -> dict[str, Any]:
        data = self.pair_code()
        try:
            import qrcode
        except ImportError as exc:
            raise RuntimeError("Install Astra mesh extras to generate QR codes.") from exc
        path = Path(output).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        image = qrcode.make(data["uri"])
        image.save(path)
        data["qr_path"] = str(path)
        return data

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self.run,
            name="astra-mesh",
            daemon=True,
        )
        self._thread.start()

    def run(self) -> None:
        loop = asyncio.new_event_loop()
        self._loop = loop
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._serve())
        finally:
            try:
                loop.run_until_complete(self._shutdown())
            except Exception:
                pass
            loop.close()

    def stop(self) -> None:
        self._stop.set()
        if self._loop:
            self._loop.call_soon_threadsafe(lambda: None)
        self.discovery.stop()

    def broadcast(self, message: dict[str, Any], scope: str | None = None) -> None:
        if not self._loop:
            return
        asyncio.run_coroutine_threadsafe(self._broadcast(message, scope), self._loop)

    async def _serve(self) -> None:
        app = web.Application(client_max_size=10 * 1024 * 1024)
        app.router.add_get("/v1/health", self._health)
        app.router.add_post("/v1/pair", self._pair)
        app.router.add_get("/v1/devices", self._devices)
        app.router.add_post("/v1/ask", self._ask)
        app.router.add_post("/v1/snapshot", self._snapshot)
        app.router.add_get("/v1/ws", self._ws)

        self._runner = web.AppRunner(app, access_log=None)
        await self._runner.setup()

        ssl_ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        ssl_ctx.load_cert_chain(
            certfile=str(self.identity.cert_path),
            keyfile=str(self.identity.key_path),
        )
        site = web.TCPSite(self._runner, self.host, self.port, ssl_context=ssl_ctx)
        await site.start()
        self.discovery.start()
        print(
            f"Astra Mesh online: https://{local_ip()}:{self.port} "
            f"fingerprint={self.identity.fingerprint[:16]}..."
        )
        while not self._stop.is_set():
            await asyncio.sleep(0.25)

    async def _shutdown(self) -> None:
        self.discovery.stop()
        with self._sockets_lock:
            sockets = list(self._sockets.values())
            self._sockets.clear()
        for ws in sockets:
            try:
                await ws.close()
            except Exception:
                pass
        if self._runner:
            await self._runner.cleanup()

    async def _health(self, request: web.Request) -> web.Response:
        return web.json_response({
            "ok": True,
            "service": "astra-mesh",
            "version": "0.8",
            "protocol": 1,
            "node_id": self.identity.node_id,
            "name": self.identity.name,
            "fingerprint": self.identity.fingerprint,
        })

    async def _pair(self, request: web.Request) -> web.Response:
        payload = await request.json()
        code = str(payload.get("code", "")).strip()
        device_id = str(payload.get("device_id", "")).strip()
        name = str(payload.get("name", "Android")).strip()
        platform_name = str(payload.get("platform", "android")).strip()
        if not device_id or not self.pairing.verify(code):
            return web.json_response(
                {"ok": False, "error": "invalid_or_expired_pairing_code"},
                status=403,
            )
        token, device = self.registry.pair(device_id, name, platform_name)
        self._emit("mesh.paired", {"device": device})
        return web.json_response({
            "ok": True,
            "token": token,
            "device": device,
            "node": {
                "id": self.identity.node_id,
                "name": self.identity.name,
                "fingerprint": self.identity.fingerprint,
            },
        })

    async def _devices(self, request: web.Request) -> web.Response:
        device = self._auth(request)
        if not device:
            return web.json_response({"ok": False, "error": "unauthorized"}, status=401)
        return web.json_response({
            "ok": True,
            "self": self._public(device),
            "devices": self.registry.list_public(),
        })

    async def _ask(self, request: web.Request) -> web.Response:
        device = self._auth(request)
        if not device:
            return web.json_response({"ok": False, "error": "unauthorized"}, status=401)
        if not self.registry.has_scope(device, "assistant.ask"):
            return web.json_response({"ok": False, "error": "scope_denied"}, status=403)
        payload = await request.json()
        text = str(payload.get("text", "")).strip()
        if not text:
            return web.json_response({"ok": False, "error": "empty_request"}, status=400)
        result = await asyncio.to_thread(
            self.request_handler,
            {"type": "ask", "text": text, "mesh_device": self._public(device)},
        )
        return web.json_response(result)

    async def _snapshot(self, request: web.Request) -> web.Response:
        device = self._auth(request)
        if not device:
            return web.json_response({"ok": False, "error": "unauthorized"}, status=401)
        if not self.registry.has_scope(device, "camera.snapshot"):
            return web.json_response({"ok": False, "error": "scope_denied"}, status=403)
        raw = await request.read()
        if not raw or len(raw) > 8 * 1024 * 1024:
            return web.json_response({"ok": False, "error": "invalid_snapshot"}, status=400)
        suffix = ".jpg"
        content_type = request.headers.get("Content-Type", "")
        if "png" in content_type:
            suffix = ".png"
        inbox = self.root / "inbox" / str(device["device_id"])
        inbox.mkdir(parents=True, exist_ok=True)
        path = inbox / f"{int(time.time() * 1000)}{suffix}"
        path.write_bytes(raw)
        self._emit("mesh.camera_snapshot", {
            "device": self._public(device),
            "path": str(path),
            "bytes": len(raw),
        })
        return web.json_response({"ok": True, "path": str(path)})

    async def _ws(self, request: web.Request) -> web.StreamResponse:
        device = self._auth(request)
        if not device:
            return web.json_response({"ok": False, "error": "unauthorized"}, status=401)

        ws = web.WebSocketResponse(heartbeat=20, receive_timeout=90)
        await ws.prepare(request)
        device_id = str(device["device_id"])
        with self._sockets_lock:
            previous = self._sockets.get(device_id)
            self._sockets[device_id] = ws
        if previous and not previous.closed:
            try:
                await previous.close(code=4001, message=b"replaced")
            except Exception:
                pass

        await ws.send_json(envelope(
            "welcome",
            node_id=self.identity.node_id,
            node_name=self.identity.name,
            device=self._public(device),
        ))
        self._emit("mesh.connected", {"device": self._public(device)})

        try:
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    await self._handle_ws_message(ws, device, msg.data)
                elif msg.type in {WSMsgType.ERROR, WSMsgType.CLOSE, WSMsgType.CLOSED}:
                    break
        finally:
            with self._sockets_lock:
                if self._sockets.get(device_id) is ws:
                    self._sockets.pop(device_id, None)
            self._emit("mesh.disconnected", {"device": self._public(device)})
        return ws

    async def _handle_ws_message(
        self,
        ws: web.WebSocketResponse,
        device: dict,
        raw: str,
    ) -> None:
        try:
            payload = json.loads(raw)
        except Exception:
            await ws.send_json(envelope("error", error="invalid_json"))
            return

        kind = str(payload.get("type", ""))
        if kind == "ping":
            await ws.send_json(envelope("pong", ts=time.time()))
            return

        if kind == "ask":
            if not self.registry.has_scope(device, "assistant.ask"):
                await ws.send_json(envelope("error", error="scope_denied"))
                return
            text = str(payload.get("text", "")).strip()
            result = await asyncio.to_thread(
                self.request_handler,
                {"type": "ask", "text": text, "mesh_device": self._public(device)},
            )
            await ws.send_json(envelope(
                "reply",
                request_id=payload.get("request_id"),
                result=result,
            ))
            return

        if kind == "context":
            if not self.registry.has_scope(device, "context.read"):
                await ws.send_json(envelope("error", error="scope_denied"))
                return
            result = await asyncio.to_thread(
                self.request_handler,
                {"type": "awareness", "mesh_device": self._public(device)},
            )
            await ws.send_json(envelope(
                "context",
                request_id=payload.get("request_id"),
                result=result,
            ))
            return

        if kind == "sensor":
            if not self.registry.has_scope(device, "sensor.write"):
                await ws.send_json(envelope("error", error="scope_denied"))
                return
            data = payload.get("data")
            sensor = str(payload.get("sensor", "unknown"))[:50]
            self._emit("mesh.sensor", {
                "device": self._public(device),
                "sensor": sensor,
                "data": data,
                "ts": payload.get("ts", time.time()),
            })
            await ws.send_json(envelope("ack", request_id=payload.get("request_id")))
            return

        if kind == "clipboard.push":
            if not self.registry.has_scope(device, "clipboard.push"):
                await ws.send_json(envelope("error", error="scope_denied"))
                return
            text = str(payload.get("text", ""))[:100000]
            result = await asyncio.to_thread(
                self.request_handler,
                {
                    "type": "mesh.clipboard",
                    "text": text,
                    "mesh_device": self._public(device),
                },
            )
            await ws.send_json(envelope("ack", result=result))
            return

        await ws.send_json(envelope("error", error="unsupported_message_type"))

    async def _broadcast(self, message: dict[str, Any], scope: str | None) -> None:
        with self._sockets_lock:
            items = list(self._sockets.items())
        for device_id, ws in items:
            if ws.closed:
                continue
            device = next(
                (d for d in self.registry.list_public() if d["device_id"] == device_id),
                None,
            )
            if scope and (not device or scope not in set(device.get("scopes", []))):
                continue
            try:
                await ws.send_json(message)
            except Exception:
                pass

    def _auth(self, request: web.Request) -> dict | None:
        header = request.headers.get("Authorization", "")
        if not header.startswith("Bearer "):
            return None
        return self.registry.authenticate(header[7:].strip())

    def _emit(self, name: str, payload: dict[str, Any]) -> None:
        if self.event_handler:
            try:
                self.event_handler(name, payload)
            except Exception:
                pass

    @staticmethod
    def _public(device: dict) -> dict:
        return {k: v for k, v in device.items() if k != "token_hash"}
