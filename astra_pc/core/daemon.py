from __future__ import annotations

import json
import socket
import threading
import time
from pathlib import Path
from typing import Any

from astra_pc.accessibility import create_accessibility_provider
from astra_pc.ai.agent import AstraBrain
from astra_pc.ai.ollama_client import OllamaClient
from astra_pc.core.context import ContextEngine
from astra_pc.core.events import EventBus
from astra_pc.core.memory import SessionMemory
from astra_pc.core.permissions import PermissionLayer
from astra_pc.core.planner import AstraPlanner
from astra_pc.core.proactive import ProactiveMonitor
from astra_pc.core.routines import RoutineManager
from astra_pc.skills.manager import SkillManager


class AstraDaemon:
    def __init__(self, config):
        self.config = config
        ai = config.data.get("ai", {})
        host = ai.get("host", "http://127.0.0.1:11434")
        timeout = int(ai.get("timeout", 180))
        keep = ai.get("keep_alive", "-1")

        self.text_client = OllamaClient(
            ai.get("text_model", "qwen3:0.6b"),
            host,
            timeout,
            keep,
        )
        self.vision_client = OllamaClient(
            ai.get("vision_model", "qwen3-vl:2b-instruct"),
            host,
            timeout,
            keep,
        )
        self.brain = AstraBrain(self.text_client, self.vision_client)

        daemon_cfg = config.data.get("daemon", {})
        self.host = daemon_cfg.get("host", "127.0.0.1")
        self.port = int(daemon_cfg.get("port", 8765))
        self.context_interval = float(daemon_cfg.get("context_interval", 0.75))
        memory_path = daemon_cfg.get(
            "memory_path",
            str(Path.home() / ".local" / "share" / "astra-pc" / "astra.db"),
        )

        self.bus = EventBus()
        self.memory = SessionMemory(memory_path)
        self.context = ContextEngine(
            profile=config.data.get("profiles", {}).get("active", "default")
        )
        self.accessibility = create_accessibility_provider()
        self.permissions = PermissionLayer()
        self.skills = SkillManager(self.permissions)
        self.routines = RoutineManager(self.memory, self.skills)
        self.planner = AstraPlanner(self.brain, self.skills)
        proactive_cfg = config.data.get("proactive", {})
        self.proactive = ProactiveMonitor(
            self.bus,
            cpu_threshold=float(proactive_cfg.get("cpu_threshold", 92)),
            ram_threshold=float(proactive_cfg.get("ram_threshold", 92)),
            interval=float(proactive_cfg.get("interval", 5)),
        )
        self.bus.subscribe("*", self._remember_event)
        self._stop = threading.Event()
        self._accessibility_cache: list[dict[str, Any]] = []
        self.voice_assistant = None

    def run(self, voice: bool = False, no_speak: bool = False) -> None:
        print(f"Astra daemon starting on {self.host}:{self.port}")
        self.brain.preload()
        threading.Thread(target=self._warm_vision, daemon=True).start()
        threading.Thread(target=self._context_loop, daemon=True).start()

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
        if self.voice_assistant:
            try:
                self.voice_assistant.stop()
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
        if event.name.startswith("context."):
            return
        self.memory.add(
            "event",
            {
                "name": event.name,
                "payload": event.payload,
                "created_at": event.created_at,
            },
        )

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
            return {"ok": True, "version": "0.6", "status": "ready"}

        if kind == "stop":
            self.stop()
            return {"ok": True, "message": "stopping"}

        if kind == "context":
            return {
                "ok": True,
                "context": self.context.current.as_dict(),
                "accessibility": self._accessibility_cache[:80],
                "routines": self.routines.list(),
            }

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

        plan = self.planner.plan(
            text,
            self.context.current,
            self._accessibility_cache,
        )
        self.memory.add("request", {"text": text, "plan": plan})

        if plan.get("type") == "skill":
            result = self.skills.execute(
                str(plan.get("skill", "")),
                str(plan.get("action", "")),
                dict(plan.get("args", {})),
                confirmed=bool(request.get("confirmed", False)),
            )
            return {
                "ok": result.ok,
                "message": result.message,
                "data": result.data,
                "plan": plan,
            }

        answer = str(plan.get("answer") or self.brain.ask(text))
        return {"ok": True, "message": answer, "plan": plan}
