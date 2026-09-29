from __future__ import annotations

import json
import re
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
from astra_pc.gestures.control import FEATURE_LABELS, GestureControlState, apply_gesture_control
from astra_pc.perception.fusion import PerceptionFusion
from astra_pc.perception.monitors import get_monitors
from astra_pc.perception.reference import ReferenceResolver
from astra_pc.screen.capture import capture_screen
from astra_pc.skills.manager import SkillManager
from astra_pc.voice.commands import CommandRouter


class AstraDaemon:
    def __init__(self, config):
        self.config = config
        ai = config.data.get("ai", {})
        host = ai.get("host", "http://127.0.0.1:11434")
        timeout = int(ai.get("timeout", 180))
        keep = ai.get("keep_alive", -1)

        self.text_client = OllamaClient(
            ai.get("text_model", "qwen3-vl:2b-instruct"),
            host,
            timeout,
            keep,
        )
        self.fast_client = OllamaClient(
            ai.get("fast_model", "qwen3:0.6b"),
            host,
            timeout,
            "10m",
        )
        self.vision_client = OllamaClient(
            ai.get("vision_model", "qwen3-vl:2b-instruct"),
            host,
            timeout,
            keep,
        )
        strong_name = str(ai.get("strong_model", "")).strip()
        self.strong_client = OllamaClient(strong_name, host, timeout, "5m") if strong_name else None
        self.brain = AstraBrain(
            self.text_client,
            self.vision_client,
            self.strong_client,
            fast_client=self.fast_client,
        )

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
        self.gesture_control = GestureControlState()
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
        self._voice_lock = threading.RLock()
        self.mesh_server = None
        self.mesh_sensor_state: dict[str, dict[str, Any]] = {}
        self._chat_lock = threading.RLock()
        self._chat_history: list[tuple[str, str]] = []
        stored_chat = self.memory.get("recent_chat", [])
        if isinstance(stored_chat, list):
            for item in stored_chat[-12:]:
                if not isinstance(item, dict):
                    continue
                user = str(item.get("user", "")).strip()
                answer = str(item.get("assistant", "")).strip()
                if user and answer:
                    self._chat_history.append((user, answer))

    def run(self, voice: bool = False, no_speak: bool = False) -> None:
        print(f"Astra 0.8 daemon starting on {self.host}:{self.port}")
        threading.Thread(target=self._warm_text, daemon=True).start()
        # Vision is loaded lazily only when a screen/image request arrives.
        # Keeping Qwen-VL cold avoids competing with the 0.6B voice model.
        threading.Thread(target=self._context_loop, daemon=True).start()
        self._start_mesh()

        if voice:
            self._start_voice_assistant(no_speak=no_speak)

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
        self._stop_voice_assistant()

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
                sensor_rate_limit_hz=float(
                    mesh_cfg.get("sensor_rate_limit_hz", 30)
                ),
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

    def _start_voice_assistant(self, no_speak: bool = False) -> bool:
        with self._voice_lock:
            if self.voice_assistant is not None:
                return True
            try:
                from astra_pc.voice.assistant import AstraVoiceAssistant
                from astra_pc.voice.piper_tts import load_voice_state, resolve_piper_model

                voice_cfg = self.config.data.get("voice", {})
                voice_state = load_voice_state()
                piper_model = resolve_piper_model(
                    voice_cfg.get("piper_model") or None
                )
                whisper_model = (
                    voice_state.get("whisper_model")
                    or voice_cfg.get("whisper_model", "small")
                )
                language = (
                    voice_state.get("language")
                    or voice_cfg.get("language", "pt")
                )
                input_device = voice_state.get("input_device_name") or None
                if not input_device and voice_state.get("input_device_index") is not None:
                    input_device = int(voice_state["input_device_index"])
                assistant = AstraVoiceAssistant(
                    self.brain,
                    None,
                    wake_word=voice_cfg.get("wake_word", "astra"),
                    speak=not no_speak,
                    engine=voice_cfg.get("engine", "fast"),
                    whisper_model=whisper_model,
                    language=language,
                    request_handler=self._voice_request,
                    conversation_window=float(
                        voice_cfg.get("conversation_window", 9.0)
                    ),
                    wakeword_model=(
                        voice_cfg.get("dedicated_wakeword", {}).get("model_path")
                        if voice_cfg.get("dedicated_wakeword", {}).get("enabled")
                        else None
                    ),
                    wakeword_threshold=float(
                        voice_cfg.get("dedicated_wakeword", {}).get(
                            "threshold", 0.55
                        )
                    ),
                    piper_model=piper_model,
                    input_device=input_device,
                    silence_ms=int(
                        voice_state.get(
                            "silence_ms",
                            voice_cfg.get("silence_ms", 480),
                        )
                    ),
                    pre_roll_ms=int(
                        voice_state.get(
                            "pre_roll_ms",
                            voice_cfg.get("pre_roll_ms", 300),
                        )
                    ),
                    start_speech_ms=int(
                        voice_state.get(
                            "start_speech_ms",
                            voice_cfg.get("start_speech_ms", 60),
                        )
                    ),
                    min_utterance_ms=int(
                        voice_state.get(
                            "min_utterance_ms",
                            voice_cfg.get("min_utterance_ms", 180),
                        )
                    ),
                    max_utterance_s=float(
                        voice_state.get(
                            "max_utterance_s",
                            voice_cfg.get("max_utterance_s", 18.0),
                        )
                    ),
                    vad_mode=int(
                        voice_state.get(
                            "vad_mode",
                            voice_cfg.get("vad_mode", 2),
                        )
                    ),
                    adaptive_retry=bool(
                        voice_state.get("adaptive_retry", True)
                    ),
                )
                self.voice_assistant = assistant
                threading.Thread(
                    target=assistant.run,
                    name="astra-resident-voice",
                    daemon=True,
                ).start()
                return True
            except Exception as exc:
                self.voice_assistant = None
                print(f"[voice] resident start failed: {exc}")
                return False

    def _stop_voice_assistant(self) -> bool:
        with self._voice_lock:
            assistant = self.voice_assistant
            self.voice_assistant = None
        if assistant is None:
            return True
        try:
            assistant.stop()
            return True
        except Exception as exc:
            print(f"[voice] resident stop failed: {exc}")
            return False

    def _voice_request(self, text: str) -> str:
        q = text.lower()
        screen_phrases = (
            "minha tela",
            "na tela",
            "tela agora",
            "o que estou vendo",
            "essa janela",
        )
        kind = "screen" if any(phrase in q for phrase in screen_phrases) else "ask"
        result = self.handle({"type": kind, "text": text, "voice": True})
        return str(result.get("message") or result.get("error") or "")

    def _warm_text(self) -> None:
        try:
            self.brain.preload()
            self.bus.publish("model.ready", model="text")
        except Exception as exc:
            self.bus.publish("model.error", model="text", error=str(exc))
            print(f"[model:text] warmup failed: {exc}")

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

    def _background(self, fn, *args, **kwargs) -> None:
        def runner():
            try:
                fn(*args, **kwargs)
            except Exception:
                pass
        threading.Thread(target=runner, daemon=True).start()

    def _remember_conversation(self, text: str, answer: str) -> None:
        self.semantic.remember(
            f"Usuário: {text}\nAstra: {answer}",
            kind="conversation",
            metadata={
                "profile": self.context.current.profile,
                "window": self.context.current.active_window,
            },
        )

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

    def _record_chat(self, user_text: str, answer: str) -> None:
        if not user_text or not answer:
            return
        with self._chat_lock:
            self._chat_history.append((user_text, answer))
            if len(self._chat_history) > 12:
                self._chat_history = self._chat_history[-12:]
            payload = [
                {"user": user, "assistant": assistant}
                for user, assistant in self._chat_history
            ]
        try:
            self.memory.set("recent_chat", payload)
        except Exception:
            pass

    def _assistant_context(
        self,
        memories: list[dict[str, Any]] | None = None,
    ) -> str:
        current = self.context.current
        skills = self.skills.describe()
        with self._chat_lock:
            recent = list(self._chat_history[-10:])

        parts = [
            f"Perfil atual: {current.profile}",
            f"Janela ativa: {current.active_window or 'desconhecida'}",
            f"Diretório atual do desktop: {current.cwd or 'desconhecido'}",
            "Skills disponíveis: "
            + "; ".join(
                f"{item.get('name')}: {item.get('description')}"
                for item in skills
            ),
        ]
        if recent:
            parts.append(
                "Conversa recente:\n"
                + "\n".join(
                    f"Usuário: {user}\nAstra: {answer}"
                    for user, answer in recent
                )
            )
        if memories:
            parts.append(
                "Memórias relevantes:\n"
                + json.dumps(memories[:4], ensure_ascii=False)[:3500]
            )
        last_path = self.memory.get("last_files_path", None)
        if last_path:
            parts.append(f"Último caminho de arquivos usado: {last_path}")

        listing = self.memory.get("last_files_listing", None)
        if isinstance(listing, dict):
            entries = listing.get("entries")
            if isinstance(entries, list) and entries:
                compact = [
                    {
                        "name": str(item.get("name", "")),
                        "path": str(item.get("path", "")),
                        "type": str(item.get("type", "")),
                    }
                    for item in entries[:40]
                    if isinstance(item, dict)
                ]
                parts.append(
                    "Última listagem real de arquivos (use para resolver referências):\n"
                    + json.dumps(
                        {"path": listing.get("path"), "entries": compact},
                        ensure_ascii=False,
                    )[:7000]
                )
        return "\n\n".join(parts)

    def _semantic_context(self, text: str) -> list[dict[str, Any]]:
        q = " ".join(text.lower().split())
        memory_cues = (
            "lembra",
            "lembrar",
            "antes",
            "anterior",
            "última",
            "ultima",
            "de novo",
            "como eu gosto",
            "preferência",
            "preferencia",
            "meu projeto",
            "nosso projeto",
            "a gente falou",
            "já falamos",
            "ja falamos",
        )
        if len(q) < 48 and not any(cue in q for cue in memory_cues):
            return []
        try:
            return self.semantic.search(text, limit=4)
        except Exception:
            return []

    def _execute_skill_plan(
        self,
        text: str,
        plan: dict[str, Any],
        request: dict[str, Any],
    ) -> dict[str, Any]:
        skill_name = str(plan.get("skill", ""))
        action_name = str(plan.get("action", ""))
        skill_args = dict(plan.get("args", {}))

        if skill_name == "apps" and action_name in {"open_app", "close_app"}:
            app_name = str(skill_args.get("name", "")).strip(" .,;:!?")
            if app_name:
                self.memory.set("last_app_name", app_name)

        result = self.skills.execute(
            skill_name,
            action_name,
            skill_args,
            confirmed=bool(request.get("confirmed", False)),
        )
        reply = {
            "ok": result.ok,
            "message": result.message,
            "data": result.data,
            "plan": plan,
        }
        if result.ok and skill_name == "files":
            data = result.data or {}
            used_path = (
                data.get("path")
                or skill_args.get("path")
                or skill_args.get("root")
            )
            if used_path:
                self.memory.set("last_files_path", str(used_path))
            if action_name == "list_dir":
                entries = data.get("entries") if isinstance(data, dict) else None
                if isinstance(entries, list):
                    self.memory.set(
                        "last_files_listing",
                        {
                            "path": str(data.get("path") or used_path or ""),
                            "display_path": str(data.get("display_path") or ""),
                            "entries": entries[:250],
                            "total": int(data.get("total", len(entries))),
                        },
                    )

        self._record_chat(text, result.message)
        self._background(
            self.semantic.remember,
            f"Pedido: {text}\nAção: {plan}\nResultado: {result.message}",
            kind="action",
            metadata={"ok": result.ok, "profile": self.context.current.profile},
        )
        return reply

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
        voice_mode = bool(request.get("voice", False))

        if kind == "ping":
            return {"ok": True, "version": "0.8", "status": "ready"}

        if kind == "voice.status":
            return {
                "ok": True,
                "active": self.voice_assistant is not None,
            }

        if kind == "voice.start":
            started = self._start_voice_assistant(
                no_speak=bool(request.get("no_speak", False))
            )
            return {"ok": started, "active": self.voice_assistant is not None}

        if kind == "voice.stop":
            stopped = self._stop_voice_assistant()
            return {"ok": stopped, "active": self.voice_assistant is not None}

        if kind == "voice.dictate_once":
            assistant = self.voice_assistant
            if assistant is None:
                return {"ok": False, "error": "resident_voice_not_active"}
            try:
                text = assistant.dictate_once(
                    timeout=float(request.get("timeout", 15.0))
                )
                return {"ok": True, "text": text}
            except Exception as exc:
                return {"ok": False, "error": str(exc)}

        if kind == "gestures.state":
            snap = self.gesture_control.snapshot(force=True)
            overrides = dict(snap.get("overrides", {}))
            gesture_cfg = dict(self.config.data.get("gestures", {}))
            pointer_cfg = dict(self.config.data.get("pointer", {}))
            defaults = {
                "pointer": False,
                "click": False,
                "right_click": True,
                "scroll": True,
                "swipe": True,
                "zoom": True,
                "rotate": True,
                "drag": False,
            }
            features = {
                name: bool(overrides.get(name, default))
                for name, default in defaults.items()
            }
            return {
                "ok": True,
                "enabled": bool(snap.get("enabled", True)),
                "features": features,
                "overrides": overrides,
            }

        if kind == "gestures.set":
            feature = str(request.get("feature", "")).strip()
            value = bool(request.get("value", False))
            if feature == "system":
                self.gesture_control.set_enabled(value)
            elif feature in FEATURE_LABELS:
                self.gesture_control.set_feature(feature, value)
            else:
                return {"ok": False, "error": "unknown_gesture_feature"}

            snap = self.gesture_control.snapshot(force=True)
            self.bus.publish(
                "gestures.control",
                state=snap,
                source="desktop",
            )
            return self.handle({"type": "gestures.state"})

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

        if kind == "mesh.device_command":
            if not self.mesh_server:
                return {"ok": False, "error": "mesh_not_running"}
            from astra_pc.mesh.protocol import envelope
            device_id = str(request.get("device_id", ""))
            action = str(request.get("action", ""))
            payload = request.get("payload") or {}
            scope = {
                "notify": "notifications.receive",
                "clipboard.set": "clipboard.receive",
            }.get(action)
            if scope is None:
                return {"ok": False, "error": "unsupported_device_command"}
            sent = self.mesh_server.send_to_device(
                device_id,
                envelope("device.command", action=action, payload=payload),
                required_scope=scope,
            )
            return {"ok": sent, "message": "sent" if sent else "device_offline_or_scope_denied"}

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
                "gestures": self.gesture_control.snapshot(force=True),
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
        image_raw = request.get("image")
        if not text and not image_raw:
            return {"ok": False, "error": "empty request"}
        if not text:
            text = "Analise esta imagem e descreva o que é importante."

        if image_raw:
            try:
                image_path = Path(str(image_raw)).expanduser().resolve()
                allowed = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
                if (
                    not image_path.is_file()
                    or image_path.suffix.casefold() not in allowed
                    or image_path.stat().st_size > 25 * 1024 * 1024
                ):
                    return {
                        "ok": False,
                        "error": "Imagem inválida. Use PNG/JPG/WEBP/BMP com até 25 MB.",
                    }
                memories = self._semantic_context(text)
                answer = self.brain.see(
                    image_path,
                    text,
                    extra_context=self._assistant_context(memories),
                )
                user_turn = f"{text} [imagem: {image_path.name}]"
                self._record_chat(user_turn, answer)
                self._background(self._remember_conversation, user_turn, answer)
                return {
                    "ok": True,
                    "message": answer,
                    "plan": {"type": "vision", "image": str(image_path)},
                }
            except Exception as exc:
                return {"ok": False, "error": f"Não consegui analisar a imagem: {exc}"}

        lowered = text.lower().strip()

        time_answer = CommandRouter._time(text)
        if time_answer is not None:
            self._record_chat(text, time_answer)
            return {
                "ok": True,
                "message": time_answer,
                "plan": {"type": "answer", "path": "system-local-time"},
            }

        math_answer = CommandRouter._math(text)
        if math_answer is not None:
            self._record_chat(text, math_answer)
            return {
                "ok": True,
                "message": math_answer,
                "plan": {"type": "answer", "path": "system-local-math"},
            }

        instant_answer = CommandRouter._instant_reply(text)
        if instant_answer is not None:
            self._record_chat(text, instant_answer)
            return {
                "ok": True,
                "message": instant_answer,
                "plan": {"type": "answer", "path": "instant-local"},
            }

        gesture_answer = apply_gesture_control(self.gesture_control, text)
        if gesture_answer is not None:
            self._record_chat(text, gesture_answer)
            self.bus.publish(
                "gestures.control",
                state=self.gesture_control.snapshot(force=True),
                source="voice" if voice_mode else "chat",
            )
            return {
                "ok": True,
                "message": gesture_answer,
                "plan": {"type": "answer", "path": "gesture-control"},
            }

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

        last_listing = self.memory.get("last_files_listing", None)
        followup_plan = self.planner.file_followup_plan(text, last_listing)

        fast_text = text
        last_app = self.memory.get("last_app_name", None)
        if last_app and re.search(
            r"\b(?:abre|abra|abrir|feche|fecha|fechar|encerre|encerra|encerrar)\b",
            lowered,
        ):
            app_ref = re.compile(
                r"\b(?:esse|este|o)\s+(?:aplicativo|app|programa)\b|"
                r"\b(?:ele|dele)\b",
                re.I,
            )
            if app_ref.search(fast_text):
                fast_text = app_ref.sub(str(last_app), fast_text)
                print(f"[context] app reference -> {last_app}")

        direct_plan = followup_plan or self.planner._fast_plan(
            fast_text,
            self.context.current,
        )
        if direct_plan and direct_plan.get("type") == "skill":
            return self._execute_skill_plan(text, direct_plan, request)

        planning_needed = self.planner.needs_planning(text)
        context_sensitive = (
            len(text.split()) <= 7
            or any(
                word in lowered
                for word in (
                    " ele", " ela", " isso", " isto", " esse", " essa",
                    " desse", " dessa", " dele", " dela", " ali", " aí", " ai",
                    "primeiro", "segundo", "terceiro", "anterior", "último", "ultimo",
                )
            )
        )
        cacheable = (
            not voice_mode
            and not planning_needed
            and not context_sensitive
            and not any(
                word in lowered
                for word in (
                    "agora",
                    "hoje",
                    "tela",
                    "aqui",
                    "status",
                    "processo",
                    "arquivo",
                    "pasta",
                    "diretório",
                    "diretorio",
                )
            )
        )
        cache_namespace = (
            f"{self.context.current.profile}|brain-2b-v2|{self.text_client.model}"
        )
        cache_key = self.cache.key(text, cache_namespace)
        if cacheable:
            cached = self.cache.get(cache_key)
            if cached is not None:
                return {"ok": True, "message": cached, "cached": True}

        # Voice and GUI/chat now share the same daemon conversation state.
        # Voice keeps the shorter spoken-generation budget, but receives the
        # exact same recent chat, memory, files and desktop context.
        if not planning_needed:
            memories = self._semantic_context(text)
            context = self._assistant_context(memories)
            answer = (
                self.brain.ask_voice(text, extra_context=context)
                if voice_mode
                else self.brain.ask(text, extra_context=context)
            )
            if cacheable and answer:
                self.cache.put(cache_key, answer)
            self._record_chat(text, answer)
            self._background(self._remember_conversation, text, answer)
            return {
                "ok": True,
                "message": answer,
                "plan": {"type": "answer", "path": "2b-contextual"},
            }

        planner_text = text

        if not followup_plan and not AstraPlanner.extract_path(text):
            q = lowered
            if any(
                phrase in q
                for phrase in (
                    "nessa pasta",
                    "dessa pasta",
                    "nesse diretório",
                    "nesse diretorio",
                    "lá dentro",
                    "la dentro",
                    "dentro dele",
                    "dentro dela",
                )
            ):
                last_path = self.memory.get("last_files_path", None)
                if last_path:
                    planner_text = f'{text} "{last_path}"'

        memories = self._semantic_context(text)
        reference = self.reference.resolve(
            text,
            active_window=self.context.current.active_window,
            accessibility=self._accessibility_cache,
        )
        browser_dom = []
        title = self.context.current.active_window.lower()
        if any(x in title for x in ("chrome", "chromium", "firefox", "brave", "edge")):
            browser_dom = self.browser.snapshot(limit=45)

        plan = followup_plan or self.planner.plan(
            planner_text,
            self.context.current,
            self._accessibility_cache,
            memories=memories,
            reference=reference,
            browser_dom=browser_dom,
        )
        self.memory.add("request", {"text": text, "plan": plan})

        if plan.get("type") == "skill":
            return self._execute_skill_plan(text, plan, request)

        context = self._assistant_context(memories)
        answer = str(
            plan.get("answer")
            or (
                self.brain.ask_voice(text, extra_context=context)
                if voice_mode
                else self.brain.ask(text, extra_context=context)
            )
        )
        self._record_chat(text, answer)
        self._background(self._remember_conversation, text, answer)
        if cacheable and answer:
            self.cache.put(cache_key, answer)
        return {"ok": True, "message": answer, "plan": plan}
