from __future__ import annotations

import json
import socket
import threading
import time
from pathlib import Path
from typing import Any

from astra_pc.accessibility import create_accessibility_provider
from astra_pc.ai.agent import AstraBrain
from astra_pc.ai.embeddings import EmbeddingClient
from astra_pc.ai.ollama_client import OllamaClient
from astra_pc.browser.dom import BrowserDOM
from astra_pc.core.cache import ResponseCache
from astra_pc.core.context import ContextEngine
from astra_pc.core.events import EventBus
from astra_pc.core.governor import PerformanceGovernor
from astra_pc.core.memory import SessionMemory
from astra_pc.core.permissions import PermissionLayer
from astra_pc.core.planner import AstraPlanner
from astra_pc.core.prediction import PredictionEngine
from astra_pc.core.proactive import ProactiveMonitor
from astra_pc.core.routines import RoutineManager
from astra_pc.core.routine_suggestions import RoutineSuggestionEngine
from astra_pc.core.semantic_memory import SemanticMemory
from astra_pc.perception.fusion import PerceptionFusion
from astra_pc.perception.monitors import get_monitors
from astra_pc.perception.reference import ReferenceResolver
from astra_pc.screen.capture import capture_screen
from astra_pc.skills.manager import SkillManager


class AstraDaemon:
    def __init__(self, config):
        self.config = config
        ai = config.data.get("ai", {})
        host = ai.get("host", "http://127.0.0.1:11434")
        timeout = int(ai.get("timeout", 180))
        keep = ai.get("keep_alive", "-1")

        self.text_client = OllamaClient(ai.get("text_model", "qwen3:0.6b"), host, timeout, keep)
        self.vision_client = OllamaClient(ai.get("vision_model", "qwen3-vl:2b-instruct"), host, timeout, keep)
        strong_name = str(ai.get("strong_model", "")).strip()
        self.strong_client = OllamaClient(strong_name, host, timeout, "5m") if strong_name else None
        self.brain = AstraBrain(self.text_client, self.vision_client, self.strong_client)

        daemon_cfg = config.data.get("daemon", {})
        self.host = daemon_cfg.get("host", "127.0.0.1")
        self.port = int(daemon_cfg.get("port", 8765))
        self.context_interval = float(daemon_cfg.get("context_interval", 0.75))
        memory_path = daemon_cfg.get(
            "memory_path",
            str(Path.home() / ".local" / "share" / "astra-pc" / "astra.db"),
        )
        cache_path = daemon_cfg.get(
            "cache_path",
            str(Path.home() / ".cache" / "astra-pc" / "responses.db"),
        )

        self.bus = EventBus()
        self.memory = SessionMemory(memory_path)
        embed_cfg = config.data.get("memory", {})
        self.embedding_client = EmbeddingClient(
            model=embed_cfg.get("embedding_model", "qwen3-embedding:0.6b"),
            host=host,
            timeout=int(embed_cfg.get("embedding_timeout", 25)),
        )
        self.semantic = SemanticMemory(memory_path, self.embedding_client)
        self.cache = ResponseCache(cache_path, ttl=int(daemon_cfg.get("cache_ttl", 86400)))

        stored_profile = self.memory.get("active_profile", None)
        active_profile = stored_profile or config.data.get("profiles", {}).get("active", "default")
        self.context = ContextEngine(profile=active_profile)
        self.accessibility = create_accessibility_provider()
        self.permissions = PermissionLayer()
        plugin_dir = config.data.get("skills", {}).get(
            "plugin_dir",
            str(Path.home() / ".local" / "share" / "astra-pc" / "skills"),
        )
        self.skills = SkillManager(self.permissions, plugin_dir=plugin_dir)
        self.routines = RoutineManager(self.memory, self.skills)
        self.routine_suggestions = RoutineSuggestionEngine(self.memory)
        self.planner = AstraPlanner(self.brain, self.skills)
        self.prediction = PredictionEngine(self.memory)
        self.reference = ReferenceResolver()
        self.fusion = PerceptionFusion(self.brain)
        self.browser = BrowserDOM(config.data.get("browser", {}).get("cdp", "http://127.0.0.1:9222"))
        self.governor = PerformanceGovernor(
            cpu_high=float(config.data.get("performance", {}).get("cpu_high", 85)),
            ram_high=float(config.data.get("performance", {}).get("ram_high", 88)),
        )

        proactive_cfg = config.data.get("proactive", {})
        self.proactive = ProactiveMonitor(
            self.bus,
            cpu_threshold=float(proactive_cfg.get("cpu_threshold", 92)),
            ram_threshold=float(proactive_cfg.get("ram_threshold", 92)),
            interval=float(proactive_cfg.get("interval", 5)),
        )
        self.bus.subscribe("*", self._remember_event)
        self.bus.subscribe("system.cpu_high", self._notify_system_event)
        self.bus.subscribe("system.ram_high", self._notify_system_event)

        self._stop = threading.Event()
        self._accessibility_cache: list[dict[str, Any]] = []
        self.voice_assistant = None
        self.mesh_server = None
        self.mesh_sensor_state: dict[str, dict[str, Any]] = {}

    def run(self, voice: bool = False, no_speak: bool = False) -> None:
        print(f"Astra 0.8 daemon starting on {self.host}:{self.port}")
        self.brain.preload()
        threading.Thread(target=self._warm_vision, daemon=True).start()
        threading.Thread(target=self._context_loop, daemon=True).start()
        self._start_mesh()

        if voice:
            from astra_pc.voice.assistant import AstraVoiceAssistant
            voice_cfg = self.config.data.get("voice", {})
            self.voice_assistant = AstraVoiceAssistant(
                self.brain,
                None,
                wake_word=voice_cfg.get("wake_word", "astra"),
                speak=not no_speak,
                engine=voice_cfg.get("engine", "fast"),
                whisper_model=voice_cfg.get("whisper_model", "base"),
                language=voice_cfg.get("language", "pt"),
                request_handler=self._voice_request,
                conversation_window=float(voice_cfg.get("conversation_window", 9.0)),
                wakeword_model=(
                    voice_cfg.get("dedicated_wakeword", {}).get("model_path")
                    if voice_cfg.get("dedicated_wakeword", {}).get("enabled")
                    else None
                ),
                wakeword_threshold=float(
                    voice_cfg.get("dedicated_wakeword", {}).get("threshold", 0.55)
                ),
                piper_model=voice_cfg.get("piper_model") or None,
            )
            threading.Thread(
                target=self.voice_assistant.run,
                name="astra-resident-voice",
                daemon=True,
            ).start()

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server.bind((self.host, self.port))
            server.listen(8)
            server.settimeout(0.5)
            print("Astra daemon ready.")
            while not self._stop.is_set():
                self.bus.drain()
                try:
                    conn, _ = server.accept()
                except socket.timeout:
                    continue
                threading.Thread(
                    target=self._handle_connection,
                    args=(conn,),
                    daemon=True,
                ).start()

        print("Astra daemon stopped.")

    def stop(self) -> None:
        self._stop.set()
        if self.mesh_server:
            try:
                self.mesh_server.stop()
            except Exception:
                pass
        if self.voice_assistant:
            try:
                self.voice_assistant.stop()
            except Exception:
                pass

    def _start_mesh(self) -> None:
        mesh_cfg = self.config.data.get("mesh", {})
        if not mesh_cfg.get("enabled", True):
            return
        try:
            from astra_pc.mesh.server import AstraMeshServer
            root = mesh_cfg.get(
                "state_path",
                str(Path.home() / ".local" / "share" / "astra-pc" / "mesh"),
            )
            self.mesh_server = AstraMeshServer(
                root=root,
                host=mesh_cfg.get("host", "0.0.0.0"),
                port=int(mesh_cfg.get("port", 8767)),
                name=mesh_cfg.get("name") or "Astra",
                request_handler=self.handle,
                event_handler=self._mesh_event,
            )
            self.mesh_server.start()
        except Exception as exc:
            self.mesh_server = None
            print(f"[mesh] unavailable: {exc}")

    def _mesh_event(self, name: str, payload: dict[str, Any]) -> None:
        if name == "mesh.sensor":
            device = payload.get("device", {})
            device_id = str(device.get("device_id", "unknown"))
            sensor = str(payload.get("sensor", "unknown"))
            state = self.mesh_sensor_state.setdefault(device_id, {
                "device": device,
                "sensors": {},
                "updated": 0.0,
            })
            state["device"] = device
            state["sensors"][sensor] = {
                "data": payload.get("data"),
                "ts": payload.get("ts"),
            }
            state["updated"] = time.time()
        self.bus.publish(name, **payload)
        if name == "mesh.camera_snapshot":
            try:
                device = payload.get("device", {})
                self.semantic.remember(
                    f"Snapshot recebido de {device.get('name', 'device')}: {payload.get('path', '')}",
                    kind="mesh",
                    metadata=payload,
                )
            except Exception:
                pass

    def _voice_request(self, text: str) -> str:
        result = self.handle({"type": "ask", "text": text})
        return str(result.get("message") or result.get("error") or "")

    def _warm_vision(self) -> None:
        try:
            self.brain.preload_vision()
            self.bus.publish("model.ready", model="vision")
        except Exception as exc:
            self.bus.publish("model.error", model="vision", error=str(exc))

    def _context_loop(self) -> None:
        previous = None
        tick = 0
        while not self._stop.is_set():
            ctx = self.context.refresh()
            current = (ctx.active_window, ctx.active_process, ctx.profile)
            if current != previous:
                self.bus.publish("context.changed", context=ctx.as_dict())
                self.memory.add("context", ctx.as_dict())
                previous = current

            tick += 1
            proactive_every = max(1, int(self.proactive.interval / max(self.context_interval, 0.1)))
            if tick % proactive_every == 0:
                try:
                    self.proactive.tick()
                except Exception:
                    pass

            if tick % 3 == 0 and self.accessibility.available():
                try:
                    self._accessibility_cache = [
                        e.as_dict() for e in self.accessibility.snapshot(limit=100)
                    ]
                except Exception:
                    self._accessibility_cache = []

            time.sleep(self.context_interval)

    def _remember_event(self, event) -> None:
        if event.name.startswith("context.") or event.name == "mesh.sensor":
            return
        self.memory.add(
            "event",
            {
                "name": event.name,
                "payload": event.payload,
                "created_at": event.created_at,
            },
        )

    def _notify_system_event(self, event) -> None:
        try:
            value = round(float(event.payload.get("value", 0)), 1)
            label = "CPU" if "cpu" in event.name else "RAM"
            message = f"{label} está em {value}%."
            self.skills.execute(
                "notifications",
                "notify",
                {"title": "Astra", "message": message},
            )
            if self.mesh_server:
                from astra_pc.mesh.protocol import envelope
                self.mesh_server.broadcast(
                    envelope("notification", title="Astra", message=message),
                    scope="notifications.receive",
                )
        except Exception:
            pass

    def _handle_connection(self, conn: socket.socket) -> None:
        with conn:
            file = conn.makefile("rwb")
            line = file.readline()
            if not line:
                return
            try:
                request = json.loads(line.decode("utf-8"))
                response = self.handle(request)
            except Exception as exc:
                response = {"ok": False, "error": str(exc)}
            file.write((json.dumps(response, ensure_ascii=False) + "\n").encode("utf-8"))
            file.flush()

    def handle(self, request: dict[str, Any]) -> dict[str, Any]:
        kind = str(request.get("type", "ask"))

        if kind == "ping":
            return {"ok": True, "version": "0.8", "status": "ready"}

        if kind == "stop":
            self.stop()
            return {"ok": True, "message": "stopping"}

        if kind == "mesh.pair_code":
            if not self.mesh_server:
                return {"ok": False, "error": "mesh_not_running"}
            ttl = int(request.get("ttl", 300))
            data = self.mesh_server.pair_code(ttl)
            output = request.get("qr")
            if output:
                try:
                    from astra_pc.mesh.qr import save_qr
                    save_qr(data["uri"], output)
                    data["qr_path"] = str(Path(output).expanduser())
                except Exception as exc:
                    data["qr_error"] = str(exc)
            return {"ok": True, **data}

        if kind == "mesh.devices":
            if not self.mesh_server:
                return {"ok": False, "error": "mesh_not_running"}
            return {
                "ok": True,
                "devices": self.mesh_server.registry.list_public(),
                "fingerprint": self.mesh_server.fingerprint,
            }

        if kind == "mesh.revoke":
            if not self.mesh_server:
                return {"ok": False, "error": "mesh_not_running"}
            device_id = str(request.get("device_id", ""))
            return {"ok": self.mesh_server.registry.revoke(device_id)}

        if kind == "mesh.clipboard":
            text = str(request.get("text", ""))[:100000]
            result = self.skills.execute(
                "clipboard",
                "clipboard_write",
                {"text": text},
            )
            device = request.get("mesh_device") or {}
            self.bus.publish(
                "mesh.clipboard",
                device=device,
                length=len(text),
            )
            return {"ok": result.ok, "message": result.message}

        if kind in {"context", "awareness"}:
            perf = self.governor.state()
            return {
                "ok": True,
                "context": self.context.current.as_dict(),
                "accessibility": self._accessibility_cache[:80],
                "monitors": [m.as_dict() for m in get_monitors()],
                "routines": self.routines.list(),
                "routine_suggestions": self.routine_suggestions.suggest(),
                "predicted_next_windows": self.prediction.next_windows(
                    self.context.current.active_window
                ),
                "performance": {
                    "mode": perf.mode,
                    "cpu": perf.cpu,
                    "ram": perf.ram,
                    "video_frames": perf.video_frames,
                    "vision_max_width": perf.vision_max_width,
                },
                "skills": self.skills.describe(),
                "mesh": {
                    "enabled": self.mesh_server is not None,
                    "port": (
                        self.mesh_server.port if self.mesh_server else None
                    ),
                    "fingerprint": (
                        self.mesh_server.fingerprint if self.mesh_server else None
                    ),
                    "devices": (
                        self.mesh_server.registry.list_public()
                        if self.mesh_server else []
                    ),
                    "live_sensors": list(self.mesh_sensor_state.values()),
                },
            }

        if kind == "memory.search":
            query = str(request.get("text", "")).strip()
            return {"ok": True, "results": self.semantic.search(query, limit=8)}

        if kind == "screen":
            question = str(request.get("text", "")).strip() or "O que há na minha tela?"
            shot = capture_screen()
            try:
                answer = self.fusion.describe(shot, self._accessibility_cache, question)
            finally:
                shot.unlink(missing_ok=True)
            self.semantic.remember(
                f"Pergunta de tela: {question}\nResposta: {answer}",
                kind="vision",
                metadata={"window": self.context.current.active_window},
            )
            return {"ok": True, "message": answer}

        if kind == "profile":
            profile = str(request.get("profile", "")).strip() or "default"
            self.context.profile = profile
            self.memory.set("active_profile", profile)
            self.bus.publish("profile.changed", profile=profile)
            self.context.refresh()
            return {"ok": True, "profile": profile}

        if kind == "routine.save":
            name = str(request.get("name", "")).strip()
            steps = request.get("steps", [])
            if not name or not isinstance(steps, list):
                return {"ok": False, "error": "routine name and steps are required"}
            self.routines.save(name, steps)
            return {"ok": True, "message": f"routine saved: {name}"}

        if kind == "routine.run":
            name = str(request.get("name", "")).strip()
            results = self.routines.run(
                name,
                confirmed=bool(request.get("confirmed", False)),
            )
            return {"ok": all(x.get("ok") for x in results), "results": results}

        text = str(request.get("text", "")).strip()
        if not text:
            return {"ok": False, "error": "empty request"}

        lowered = text.lower().strip()
        profile_aliases = {
            "modo dev": "dev",
            "modo programação": "dev",
            "modo programacao": "dev",
            "modo gaming": "gaming",
            "modo jogo": "gaming",
            "modo estudo": "study",
            "modo normal": "default",
        }
        if lowered in profile_aliases:
            profile = profile_aliases[lowered]
            self.context.profile = profile
            self.memory.set("active_profile", profile)
            self.context.refresh()
            self.bus.publish("profile.changed", profile=profile)
            return {"ok": True, "message": f"Modo {profile} ativado.", "profile": profile}

        if lowered.startswith("rodar rotina ") or lowered.startswith("executar rotina "):
            name = text.split(" ", 2)[-1].strip()
            results = self.routines.run(name, confirmed=bool(request.get("confirmed", False)))
            ok = all(x.get("ok") for x in results)
            message = results[-1].get("message", "") if results else "Rotina vazia."
            return {"ok": ok, "message": message, "results": results}

        cacheable = not any(
            word in lowered
            for word in ("agora", "hoje", "tela", "isso", "isto", "aqui", "status", "processo")
        )
        cache_key = self.cache.key(text, self.context.current.profile)
        if cacheable:
            cached = self.cache.get(cache_key)
            if cached is not None:
                return {"ok": True, "message": cached, "cached": True}

        memories = self.semantic.search(text, limit=5)
        reference = self.reference.resolve(
            text,
            active_window=self.context.current.active_window,
            accessibility=self._accessibility_cache,
        )
        browser_dom = []
        title = self.context.current.active_window.lower()
        if any(x in title for x in ("chrome", "chromium", "firefox", "brave", "edge")):
            browser_dom = self.browser.snapshot(limit=45)

        plan = self.planner.plan(
            text,
            self.context.current,
            self._accessibility_cache,
            memories=memories,
            reference=reference,
            browser_dom=browser_dom,
        )
        self.memory.add("request", {"text": text, "plan": plan})

        if plan.get("type") == "skill":
            result = self.skills.execute(
                str(plan.get("skill", "")),
                str(plan.get("action", "")),
                dict(plan.get("args", {})),
                confirmed=bool(request.get("confirmed", False)),
            )
            reply = {
                "ok": result.ok,
                "message": result.message,
                "data": result.data,
                "plan": plan,
            }
            self.semantic.remember(
                f"Pedido: {text}\nAção: {plan}\nResultado: {result.message}",
                kind="action",
                metadata={"ok": result.ok, "profile": self.context.current.profile},
            )
            return reply

        answer = str(plan.get("answer") or self.brain.ask(text))
        self.semantic.remember(
            f"Usuário: {text}\nAstra: {answer}",
            kind="conversation",
            metadata={
                "profile": self.context.current.profile,
                "window": self.context.current.active_window,
            },
        )
        if cacheable and answer:
            self.cache.put(cache_key, answer)
        return {"ok": True, "message": answer, "plan": plan}
