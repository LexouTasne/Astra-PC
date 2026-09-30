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
from astra_pc.ai.swarm import SubAgentPool, SubAgentTask
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
from astra_pc.gestures.control import (
    FEATURE_LABELS,
    GestureControlState,
    apply_gesture_control,
    parse_gesture_control,
)
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
        keep = ai.get("keep_alive", "2m")
        text_keep = ai.get("text_keep_alive", keep)
        vision_keep = ai.get("vision_keep_alive", "45s")
        fast_keep = ai.get("fast_keep_alive", -1)

        self.text_client = OllamaClient(
            ai.get("text_model", "qwen3:1.7b"),
            host,
            timeout,
            text_keep,
        )
        self.fast_client = OllamaClient(
            ai.get("fast_model", "qwen3:0.6b"),
            host,
            timeout,
            fast_keep,
        )
        self.vision_client = OllamaClient(
            ai.get("vision_model", "qwen3-vl:2b-instruct"),
            host,
            timeout,
            vision_keep,
        )
        strong_name = str(ai.get("strong_model", "")).strip()
        self.strong_client = OllamaClient(strong_name, host, timeout, "5m") if strong_name else None
        self.brain = AstraBrain(
            self.text_client,
            self.vision_client,
            self.strong_client,
            fast_client=self.fast_client,
        )
        swarm_cfg = config.data.get("swarm", {})
        self.subagents = SubAgentPool(
            self.text_client,
            self.vision_client,
            planner_client=self.fast_client,
            max_agents=int(swarm_cfg.get("max_agents", 100)),
            max_workers=int(swarm_cfg.get("max_workers", 3)),
            max_balanced_agents=int(swarm_cfg.get("max_balanced_agents", 1)),
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
            keep_alive=embed_cfg.get("embedding_keep_alive", 0),
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
        self._agent_lock = threading.Lock()
        self._agent_cancel = threading.Event()
        self._mission_lock = threading.Lock()
        self._mission_cancel = threading.Event()
        self._voice_preview_lock = threading.RLock()
        self._voice_preview_state = {"text": "", "kind": "", "at": 0.0}
        self._voice_preview_warm_at = {"text": 0.0, "vision": 0.0}
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
                    stream_handler=self._voice_stream,
                    preview_handler=self._voice_preview,
                    cancel_handler=self._cancel_active_work,
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
                    partial_interval_ms=int(
                        voice_state.get(
                            "partial_interval_ms",
                            voice_cfg.get("partial_interval_ms", 850),
                        )
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

    def _cancel_active_work(self) -> None:
        self._agent_cancel.set()
        self._mission_cancel.set()
        self.subagents.cancel()
        self.bus.publish("agents.cancelled")
        self.bus.publish("mission.cancelled")

    def _swarm_parallel_limit(self) -> int:
        state = self.governor.state()
        if state.mode == "eco":
            return 1
        if state.mode == "balanced":
            return min(2, self.subagents.max_workers)
        return self.subagents.max_workers

    @staticmethod
    def _wants_mission(text: str) -> bool:
        q = " ".join(str(text).lower().strip().split())
        return any(
            phrase in q
            for phrase in (
                "modo missão", "modo missao", "missão completa", "missao completa",
                "faz isso inteiro", "faça isso inteiro", "faz tudo isso",
                "faça tudo isso", "faz tudo pra mim", "faça tudo pra mim",
                "resolve isso inteiro", "resolva isso inteiro",
                "cuida disso pra mim", "cuide disso pra mim",
                "do começo ao fim", "do comeco ao fim",
                "assume essa tarefa", "assuma essa tarefa",
            )
        )

    @staticmethod
    def _wants_swarm(text: str) -> bool:
        q = " ".join(str(text).lower().strip().split())
        if re.search(r"([0-9]{1,3})\s*(?:sub[- ]?)?agentes?", q):
            return True
        return any(
            phrase in q
            for phrase in (
                "subagente", "sub-agente", "sub agente",
                "vários agentes", "varios agentes",
                "múltiplos agentes", "multiplos agentes",
                "agentes em paralelo", "pensa em paralelo", "pense em paralelo",
                "divide entre agentes", "divida entre agentes",
                "equipe de agentes", "usa agentes", "use agentes",
                "usar agentes", "swarm",
            )
        )

    @staticmethod
    def _requested_agent_count(text: str, default: int = 4) -> int:
        q = " ".join(str(text).lower().strip().split())
        match = re.search(r"([0-9]{1,3})\s*(?:sub[- ]?)?agentes?", q)
        if not match:
            return max(1, min(100, int(default)))
        return max(1, min(100, int(match.group(1))))

    @staticmethod
    def _wants_visual_agent(text: str) -> bool:
        q = " ".join(str(text).lower().strip().split())
        action = any(
            token in q
            for token in (
                "clica", "clique", "clicar", "aperta", "aperte", "pressiona",
                "pressione", "segura", "segure", "solta", "solte", "mexe",
                "mova", "move", "arrasta", "arraste", "vai até", "va até",
                "vá até", "anda até", "ande até", "acha e", "encontra e",
                "procura e", "abre isso", "fecha isso",
            )
        )
        visual = any(
            token in q
            for token in (
                "na tela", "minha tela", "a tela", "esse botão", "essa opção",
                "essa janela", "aquele botão", "aquela opção", "aquela janela",
                "ali", "aí", "ai", "até chegar", "ate chegar", "até lá", "ate la",
                "aquela porta", "aquele lugar", "esse lugar", "onde está", "onde ta",
            )
        )
        explicit = any(
            token in q
            for token in (
                "modo agente", "agente visual", "usa a visão", "use a visão",
                "olha a tela e", "olhe a tela e",
            )
        )
        direct_visual_action = any(
            token in q
            for token in (
                "clica no ", "clica na ", "clique no ", "clique na ",
                "clica em ", "clique em ",
                "acha o ", "acha a ", "encontra o ", "encontra a ",
                "procura o ", "procura a ",
            )
        )
        visual_object = any(
            token in q
            for token in (
                "botão", "botao", "link", "ícone", "icone", "aba",
                "janela", "campo", "menu", "opção", "opcao",
            )
        )
        return explicit or (action and visual) or direct_visual_action or (
            visual_object and any(v in q for v in ("acha", "encontra", "procura"))
        )

    def _voice_preview(self, text: str) -> None:
        """Speculative, side-effect-free preparation for partial speech."""
        q = " ".join(str(text).lower().strip().split())
        if not q:
            return

        screenish = any(
            phrase in q
            for phrase in (
                "tela", "janela", "botão", "botao", "ícone", "icone",
                "aba", "campo", "menu", "ali", "aí", "ai",
            )
        )
        visual_agent = self._wants_visual_agent(text)
        kind = "agent" if visual_agent else ("screen" if screenish else "ask")
        warm_key = "vision" if kind in {"agent", "screen"} else "text"
        now = time.monotonic()

        with self._voice_preview_lock:
            self._voice_preview_state = {
                "text": text[-240:],
                "kind": kind,
                "at": now,
            }
            should_warm = now - float(self._voice_preview_warm_at.get(warm_key, 0.0)) >= 2.0
            if should_warm:
                self._voice_preview_warm_at[warm_key] = now

        if should_warm:
            self._background(
                self.brain.preload_vision if warm_key == "vision" else self.brain.preload_fast
            )
        print(f"[voice:preview] kind={kind} text={text}")

    def _voice_request(self, text: str) -> str:
        q = text.lower()
        screen_phrases = (
            "minha tela",
            "na tela",
            "tela agora",
            "o que estou vendo",
            "essa janela",
        )
        if self._wants_mission(text):
            kind = "mission"
        elif self._wants_swarm(text):
            kind = "agents.run"
        elif self._wants_visual_agent(text):
            kind = "agent"
        else:
            kind = "screen" if any(phrase in q for phrase in screen_phrases) else "ask"
        result = self.handle({"type": kind, "text": text, "voice": True})
        return str(result.get("message") or result.get("error") or "")

    def _voice_stream(self, text: str):
        """Stream ordinary voice chat while preserving action/tool routing."""
        q = text.lower()
        screen_phrases = (
            "minha tela",
            "na tela",
            "tela agora",
            "o que estou vendo",
            "essa janela",
        )

        must_use_full_path = (
            self._wants_mission(text)
            or self._wants_swarm(text)
            or self._wants_visual_agent(text)
            or any(phrase in q for phrase in screen_phrases)
            or CommandRouter._time(text) is not None
            or CommandRouter._math(text) is not None
            or CommandRouter._instant_reply(text) is not None
            or parse_gesture_control(text) is not None
            or self.planner.needs_planning(text)
        )

        if not must_use_full_path:
            last_listing = self.memory.get("last_files_listing", None)
            direct_plan = (
                self.planner.file_followup_plan(text, last_listing)
                or self.planner._fast_plan(text, self.context.current)
            )
            must_use_full_path = bool(direct_plan)

        if must_use_full_path:
            yield self._voice_request(text)
            return

        context = self._voice_context()
        stream = (
            self.brain.ask_fast_stream(text, extra_context=context)
            if self._use_fast_voice(text)
            else self.brain.ask_voice_stream(text, extra_context=context)
        )
        chunks: list[str] = []
        for piece in stream:
            piece = str(piece or "")
            if not piece:
                continue
            chunks.append(piece)
            yield piece

        answer = "".join(chunks).strip()
        if answer:
            self._record_chat(text, answer)

    def _warm_text(self) -> None:
        # Warm sequentially: make the fast planner ready first, then the
        # stronger text model. Parallel Ollama loads can stall on 4 GB GPUs.
        try:
            self.brain.preload_fast()
            self.bus.publish("model.ready", model="fast")
        except Exception as exc:
            self.bus.publish("model.error", model="fast", error=str(exc))
            print(f"[model:fast] warmup failed: {exc}")

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
        if not bool(self.config.data.get("notifications", {}).get("enabled", True)):
            return
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

    def _voice_context(self) -> str:
        current = self.context.current
        with self._chat_lock:
            recent = list(self._chat_history[-2:])
        parts = [
            f"Perfil: {current.profile}",
            f"Janela: {current.active_window or 'desconhecida'}",
        ]
        if recent:
            parts.append(
                "Conversa recente:\n"
                + "\n".join(
                    f"U: {user}\nA: {answer[:320]}"
                    for user, answer in recent
                )
            )
        last_path = self.memory.get("last_files_path", None)
        if last_path:
            parts.append(f"Último caminho: {last_path}")
        return "\n".join(parts)

    @staticmethod
    def _use_fast_voice(text: str) -> bool:
        q = " ".join(str(text).lower().split())
        if not q or len(q.split()) > 10:
            return False
        heavy = (
            "diferença", "diferenca", "compare", "comparar", "como funciona",
            "por que", "porque", "código", "codigo", "programação", "programacao",
            "java", "javascript", "python", "erro", "bug", "arquivo", "pasta",
            "diretório", "diretorio", "sistema", "computador", "tela", "processo",
            "atual", "hoje", "notícia", "noticia", "quem é", "quem e", "quem foi",
            "quando", "onde", "explique em detalhes", "passo a passo",
        )
        return not any(term in q for term in heavy)

    def _semantic_context(
        self,
        text: str,
        *,
        eager: bool = True,
    ) -> list[dict[str, Any]]:
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
        has_memory_cue = any(cue in q for cue in memory_cues)
        if not has_memory_cue and (not eager or len(q) < 48):
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

        # Mission steps are latency-sensitive. Recording every intermediate
        # tool result would duplicate the same user goal in recent chat and, more
        # importantly, semantic.remember would enqueue an embedding request on the
        # same single-lane Ollama runtime used by the planner. Keep mission steps
        # out of that path; the mission handler records the final result once.
        if not self._mission_lock.locked():
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
                "swarm": self.subagents.status(),
                "mission": {
                    "enabled": bool(self.config.data.get("mission", {}).get("enabled", True)),
                    "busy": self._mission_lock.locked(),
                    "max_steps": int(self.config.data.get("mission", {}).get("max_steps", 16)),
                },
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

        if kind == "mission":
            goal = str(request.get("text", "")).strip()
            if not goal:
                return {"ok": False, "error": "empty_mission_goal"}

            mission_cfg = self.config.data.get("mission", {})
            if not bool(mission_cfg.get("enabled", True)):
                return {"ok": False, "error": "mission_mode_disabled"}
            if not self._mission_lock.acquire(blocking=False):
                return {"ok": False, "error": "mission_busy"}

            self._mission_cancel.clear()
            self._agent_cancel.clear()
            self.subagents.reset_cancel()
            self.bus.publish("mission.started", goal=goal)

            def execute_skill(step):
                plan = {
                    "type": "skill",
                    "skill": str(step.get("skill", "")),
                    "action": str(step.get("action", "")),
                    "args": dict(step.get("args") or {}),
                }
                return self._execute_skill_plan(
                    goal,
                    plan,
                    {
                        "confirmed": bool(request.get("confirmed", False)),
                        "voice": bool(request.get("voice", False)),
                    },
                )

            def execute_visual(subgoal):
                return self.handle({
                    "type": "agent",
                    "text": subgoal,
                    "voice": bool(request.get("voice", False)),
                })

            def execute_swarm(subgoal, count, vision):
                return self.handle({
                    "type": "agents.run",
                    "text": subgoal,
                    "count": count,
                    "vision": vision,
                    "voice": bool(request.get("voice", False)),
                })

            try:
                from astra_pc.ai.mission import MissionAgent
                mission = MissionAgent(
                    self.fast_client,
                    fallback_client=self.text_client,
                    skill_provider=self.skills.describe,
                    context_provider=lambda: self._assistant_context(
                        self._semantic_context(goal, eager=False)
                    ),
                    execute_skill=execute_skill,
                    execute_visual=execute_visual,
                    execute_swarm=execute_swarm,
                    cancel_event=self._mission_cancel,
                    max_steps=int(mission_cfg.get("max_steps", 16)),
                )
                try:
                    result = mission.run(goal)
                except Exception as exc:
                    return {"ok": False, "error": f"mission_failed: {exc}"}

                payload = result.as_dict()
                payload["plan"] = {"type": "mission"}
                self._record_chat(goal, result.message)
                self.bus.publish(
                    "mission.finished",
                    goal=goal,
                    ok=result.ok,
                    steps=len(result.steps),
                )
                return payload
            finally:
                self._mission_cancel.clear()
                self._mission_lock.release()

        if kind == "agents.status":
            return {"ok": True, **self.subagents.status()}

        if kind == "agents.cancel":
            self._cancel_active_work()
            return {"ok": True, "message": "active_work_cancelled"}

        if kind == "agents.run":
            goal = str(request.get("text", "")).strip()
            raw_tasks = request.get("agents") or []
            if not isinstance(raw_tasks, list):
                return {"ok": False, "error": "agents_must_be_a_list"}

            shared_context = self._assistant_context(
                self._semantic_context(goal or "subagents", eager=False)
            )
            tasks = []
            for item in raw_tasks[: self.subagents.max_agents]:
                if not isinstance(item, dict):
                    continue
                instruction = str(item.get("instruction", "")).strip()
                if not instruction:
                    continue
                tasks.append(
                    SubAgentTask(
                        role=str(item.get("role", "worker")),
                        instruction=instruction,
                        use_vision=bool(item.get("use_vision", False)),
                    )
                )

            screenish = any(
                phrase in goal.lower()
                for phrase in (
                    "tela", "janela", "botão", "botao", "ícone", "icone",
                    "visual", "imagem", "monitor",
                )
            )
            if not tasks and goal:
                requested = int(
                    request.get(
                        "count",
                        self._requested_agent_count(
                            goal,
                            int(self.config.data.get("swarm", {}).get("default_agents", 4)),
                        ),
                    )
                )
                tasks = self.subagents.plan_tasks(
                    goal,
                    count=requested,
                    shared_context=shared_context,
                    include_vision=bool(request.get("vision", screenish)),
                )

            if not tasks:
                return {"ok": False, "error": "no_subagent_tasks"}

            image_path = None
            if any(task.use_vision for task in tasks):
                image_path = capture_screen()
            self.bus.publish(
                "agents.started",
                goal=goal,
                count=len(tasks),
            )
            try:
                results = self.subagents.run(
                    tasks,
                    shared_context=shared_context,
                    image=image_path,
                    on_result=lambda result: self.bus.publish(
                        "agents.result",
                        result=result.as_dict(),
                    ),
                    max_parallel=self._swarm_parallel_limit(),
                )
            finally:
                if image_path is not None:
                    image_path.unlink(missing_ok=True)
            self.bus.publish(
                "agents.finished",
                goal=goal,
                count=len(results),
            )

            payload = [result.as_dict() for result in results]
            usable = [
                {
                    "role": result.role,
                    "output": result.output,
                    "elapsed_ms": round(result.elapsed_ms, 1),
                }
                for result in results
                if result.ok and result.output
            ]
            summary_prompt = (
                f"Objetivo do usuário: {goal}\n"
                f"Resultados de subagentes: {json.dumps(usable, ensure_ascii=False)[:12000]}\n"
                "Sintetize uma resposta final direta em português do Brasil. "
                "Não invente ações que os subagentes não executaram."
            )
            message = (
                self.brain.ask(summary_prompt)
                if usable
                else "Os subagentes não retornaram resultados utilizáveis."
            )
            self._record_chat(goal or "subagentes", message)
            return {
                "ok": bool(results) and all(result.ok for result in results),
                "message": message,
                "results": payload,
                "count": len(results),
                "requested": len(tasks),
                "swarm": self.subagents.status(),
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

        if kind == "agent":
            goal = str(request.get("text", "")).strip()
            if not goal:
                return {"ok": False, "error": "empty_agent_goal"}
            agent_cfg = self.config.data.get("agent", {})
            if not bool(agent_cfg.get("enabled", True)):
                return {"ok": False, "error": "visual_agent_disabled"}
            if not self._agent_lock.acquire(blocking=False):
                return {"ok": False, "error": "visual_agent_busy"}

            self._agent_cancel.clear()
            self.subagents.reset_cancel()
            try:
                from astra_pc.ai.desktop_agent import VisualDesktopAgent
                swarm_cfg = self.config.data.get("swarm", {})
                agent = VisualDesktopAgent(
                    self.vision_client,
                    max_steps=int(agent_cfg.get("max_steps", 24)),
                    subagents=(
                        self.subagents
                        if bool(swarm_cfg.get("enabled", True))
                        else None
                    ),
                    swarm_interval=int(swarm_cfg.get("visual_interval", 3)),
                    swarm_parallel=self._swarm_parallel_limit(),
                    on_subagent_result=lambda result: self.bus.publish(
                        "agents.result",
                        result=result.as_dict(),
                        source="visual_agent",
                    ),
                    cancel_event=self._agent_cancel,
                )
                try:
                    message = agent.run(goal, auto_confirm=True)
                except Exception as exc:
                    return {"ok": False, "error": f"agent_failed: {exc}"}
                self._record_chat(goal, message)
                return {
                    "ok": True,
                    "message": message,
                    "plan": {"type": "visual_agent"},
                }
            finally:
                self._agent_cancel.clear()
                self._agent_lock.release()

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
                if not voice_mode:
                    self._background(self._remember_conversation, user_turn, answer)
                return {
                    "ok": True,
                    "message": answer,
                    "plan": {"type": "vision", "image": str(image_path)},
                }
            except Exception as exc:
                return {"ok": False, "error": f"Não consegui analisar a imagem: {exc}"}

        lowered = text.lower().strip()

        if kind == "ask" and self._wants_mission(text):
            return self.handle({"type": "mission", "text": text, "voice": voice_mode})

        if kind == "ask" and self._wants_swarm(text):
            return self.handle({"type": "agents.run", "text": text, "voice": voice_mode})

        if kind == "ask" and self._wants_visual_agent(text):
            return self.handle({"type": "agent", "text": text, "voice": voice_mode})

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
            memories = self._semantic_context(text, eager=not voice_mode)
            if voice_mode:
                context = self._voice_context()
                answer = (
                    self.brain.ask_fast(text, extra_context=context)
                    if self._use_fast_voice(text)
                    else self.brain.ask_voice(text, extra_context=context)
                )
            else:
                context = self._assistant_context(memories)
                answer = self.brain.ask(text, extra_context=context)
            if cacheable and answer:
                self.cache.put(cache_key, answer)
            self._record_chat(text, answer)
            if not voice_mode:
                self._background(self._remember_conversation, text, answer)
            return {
                "ok": True,
                "message": answer,
                "plan": {
                    "type": "answer",
                    "path": (
                        "voice-fast"
                        if voice_mode and self._use_fast_voice(text)
                        else ("voice-2b" if voice_mode else "2b-contextual")
                    ),
                },
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
        if not voice_mode:
            self._background(self._remember_conversation, text, answer)
        if cacheable and answer:
            self.cache.put(cache_key, answer)
        return {"ok": True, "message": answer, "plan": plan}
