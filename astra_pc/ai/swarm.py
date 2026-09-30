from __future__ import annotations

import json
import re
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Iterable

from .ollama_client import OllamaClient


@dataclass(slots=True)
class SubAgentTask:
    role: str
    instruction: str
    task_id: str = ""
    use_vision: bool = False
    model_tier: str = "auto"

    def __post_init__(self) -> None:
        self.role = str(self.role or "worker").strip()[:80]
        self.instruction = str(self.instruction or "").strip()
        tier = str(self.model_tier or "auto").strip().lower()
        self.model_tier = tier if tier in {"auto", "fast", "balanced", "vision"} else "auto"
        if not self.task_id:
            self.task_id = uuid.uuid4().hex[:10]


@dataclass(slots=True)
class SubAgentResult:
    task_id: str
    role: str
    ok: bool
    output: str = ""
    error: str = ""
    elapsed_ms: float = 0.0
    model_tier: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


class SubAgentPool:
    """Logical swarm with bounded local model concurrency."""

    def __init__(
        self,
        text_client: OllamaClient,
        vision_client: OllamaClient,
        *,
        planner_client: OllamaClient | None = None,
        max_agents: int = 100,
        max_workers: int = 3,
        max_balanced_agents: int = 1,
    ) -> None:
        self.text_client = text_client
        self.vision_client = vision_client
        self.planner_client = planner_client or text_client
        self.max_agents = max(1, min(100, int(max_agents)))
        self.max_workers = max(1, min(8, int(max_workers)))
        self.max_balanced_agents = max(
            0,
            min(self.max_agents, int(max_balanced_agents)),
        )
        self._cancel = threading.Event()
        self._state_lock = threading.RLock()
        self._slots = threading.BoundedSemaphore(self.max_workers)
        self._running = 0

    @property
    def running(self) -> int:
        with self._state_lock:
            return self._running

    def status(self) -> dict:
        return {
            "running": self.running,
            "cancelled": self._cancel.is_set(),
            "max_agents": self.max_agents,
            "max_workers": self.max_workers,
            "max_balanced_agents": self.max_balanced_agents,
        }

    def cancel(self) -> None:
        self._cancel.set()

    def reset_cancel(self) -> None:
        self._cancel.clear()

    def run(
        self,
        tasks: Iterable[SubAgentTask],
        *,
        shared_context: str = "",
        image: str | Path | None = None,
        on_result: Callable[[SubAgentResult], None] | None = None,
        max_parallel: int | None = None,
    ) -> list[SubAgentResult]:
        items = list(tasks)[: self.max_agents]
        if not items:
            return []

        self.reset_cancel()
        results: list[SubAgentResult] = []
        parallel = self.max_workers if max_parallel is None else max(1, int(max_parallel))
        parallel = min(self.max_workers, parallel, len(items))
        pool = ThreadPoolExecutor(
            max_workers=parallel,
            thread_name_prefix="astra-subagent",
        )
        pending = {
            pool.submit(self._run_one, task, shared_context=shared_context, image=image): task
            for task in items
        }
        try:
            for future in as_completed(pending):
                task = pending[future]
                if self._cancel.is_set():
                    for queued in pending:
                        if not queued.done():
                            queued.cancel()
                    break
                try:
                    result = future.result()
                except Exception as exc:
                    result = SubAgentResult(task.task_id, task.role, False, error=str(exc))
                results.append(result)
                if on_result is not None:
                    try:
                        on_result(result)
                    except Exception:
                        pass
        finally:
            pool.shutdown(wait=not self._cancel.is_set(), cancel_futures=True)

        order = {task.task_id: index for index, task in enumerate(items)}
        results.sort(key=lambda result: order.get(result.task_id, 10**9))
        return results

    def plan_tasks(
        self,
        goal: str,
        *,
        count: int = 4,
        shared_context: str = "",
        include_vision: bool = False,
    ) -> list[SubAgentTask]:
        count = max(1, min(self.max_agents, int(count)))
        base_count = min(count, 10)
        prompt = (
            "Divida o objetivo abaixo em tarefas independentes para subagentes. "
            f"Crie no máximo {base_count} tarefas-base. Retorne APENAS JSON no formato "
            '[{"role":"nome curto","instruction":"tarefa concreta","use_vision":false,'
            '"model_tier":"fast|balanced"}]. '
            "Use balanced só para raciocínio crítico/planejamento; use fast para coleta e perspectivas. "
            "Nenhum subagente executa ações no PC; eles só analisam.\n"
            f"Objetivo: {goal}\n"
            f"Contexto: {shared_context[-3500:] or 'nenhum'}"
        )
        raw = self.planner_client.chat(
            prompt,
            system="Você é o orquestrador local do Astra. Responda em JSON válido.",
            temperature=0.05,
            num_ctx=4096,
            num_predict=700,
            think=False,
            format="json",
        )
        cleaned = raw.strip()
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError:
            start_i, end_i = cleaned.find("["), cleaned.rfind("]")
            data = []
            if start_i >= 0 and end_i > start_i:
                try:
                    data = json.loads(cleaned[start_i:end_i + 1])
                except Exception:
                    data = []
        if not isinstance(data, list):
            data = []

        tasks: list[SubAgentTask] = []
        for item in data[:base_count]:
            if not isinstance(item, dict):
                continue
            instruction = str(item.get("instruction", "")).strip()
            if not instruction:
                continue
            instruction = "Analise e reporte, sem executar ações: " + instruction
            tasks.append(
                SubAgentTask(
                    role=str(item.get("role", "worker")),
                    instruction=instruction,
                    use_vision=bool(item.get("use_vision", False)) and include_vision,
                    model_tier=str(item.get("model_tier", "auto")),
                )
            )

        if not tasks:
            tasks = default_tasks(goal, include_vision=include_vision)

        balanced_used = 0
        vision_used = 0
        role_counts: dict[str, int] = {}
        for task in tasks:
            base_role = task.role or "worker"
            role_counts[base_role] = role_counts.get(base_role, 0) + 1
            if role_counts[base_role] > 1:
                task.role = f"{base_role}-{role_counts[base_role]}"

            if task.use_vision:
                if vision_used >= 1:
                    task.use_vision = False
                    task.model_tier = "fast"
                else:
                    task.model_tier = "vision"
                    vision_used += 1
                continue

            if task.model_tier == "balanced":
                if balanced_used >= self.max_balanced_agents:
                    task.model_tier = "fast"
                else:
                    balanced_used += 1
            elif task.model_tier not in {"fast", "vision"}:
                hint = (task.role + " " + task.instruction).lower()
                critical = any(
                    token in hint
                    for token in (
                        "planej", "crít", "critic", "arquitet",
                        "verific", "risco", "decisão", "decisao",
                    )
                )
                if critical and balanced_used < self.max_balanced_agents:
                    task.model_tier = "balanced"
                    balanced_used += 1
                else:
                    task.model_tier = "fast"

        foci = (
            "latência e desempenho", "falhas e edge cases", "segurança e permissões",
            "experiência do usuário", "arquitetura", "testes", "memória e contexto",
            "voz e streaming", "visão", "entrada de mouse e teclado", "concorrência",
            "uso de CPU/GPU/RAM", "recuperação de erros", "observabilidade",
            "compatibilidade Linux/Windows", "rede e IPC", "cache", "estado e sessões",
            "simplicidade de implementação", "alternativas técnicas",
        )
        index = 0
        while len(tasks) < count:
            focus = foci[index % len(foci)]
            number = len(tasks) + 1
            tasks.append(
                SubAgentTask(
                    role=f"especialista-{number}",
                    instruction=(
                        f"Analise e reporte, sem executar ações: objetivo={goal}. "
                        f"Foque em {focus}. Procure uma perspectiva independente das demais."
                    ),
                    use_vision=include_vision and focus == "visão",
                    model_tier="fast",
                )
            )
            index += 1

        return tasks[:count]

    def _client_for_task(
        self,
        task: SubAgentTask,
        image: str | Path | None,
    ) -> tuple[OllamaClient, str]:
        if task.use_vision and image:
            return self.vision_client, "vision"
        if task.model_tier == "fast":
            return self.planner_client, "fast"
        if task.model_tier == "balanced":
            return self.text_client, "balanced"

        hint = (task.role + " " + task.instruction).lower()
        strong_hints = (
            "planej", "crít", "critic", "arquitet", "verific", "risco",
            "síntese", "sintese", "decisão", "decisao",
        )
        if any(token in hint for token in strong_hints):
            return self.text_client, "balanced"
        return self.planner_client, "fast"

    def _run_one(
        self,
        task: SubAgentTask,
        *,
        shared_context: str,
        image: str | Path | None,
    ) -> SubAgentResult:
        started = time.perf_counter()
        if self._cancel.is_set():
            return SubAgentResult(task.task_id, task.role, False, error="cancelled")

        self._slots.acquire()
        if self._cancel.is_set():
            self._slots.release()
            return SubAgentResult(task.task_id, task.role, False, error="cancelled")
        with self._state_lock:
            self._running += 1
        try:
            system = (
                "You are an Astra sub-agent. Work only on your assigned role. "
                "Return a concise finding for the parent agent. Do not claim that "
                "you clicked, typed, moved the mouse, changed files or executed an action. "
                "You are analysis-only. Answer in Brazilian Portuguese."
            )
            prompt = (
                f"Papel: {task.role}\\n"
                f"Tarefa: {task.instruction}\\n"
                f"Contexto compartilhado: {shared_context[-5000:] or 'nenhum'}\\n"
                "Retorne apenas o resultado útil para o agente principal."
            )
            client, tier = self._client_for_task(task, image)
            balanced_acquired = False
            if tier == "balanced":
                self._balanced_slots.acquire()
                balanced_acquired = True
                if self._cancel.is_set():
                    self._balanced_slots.release()
                    return SubAgentResult(
                        task.task_id, task.role, False,
                        error="cancelled", model_tier=tier,
                    )
            kwargs = {
                "system": system,
                "temperature": 0.05,
                "num_ctx": 4096,
                "num_predict": 180,
                "think": False,
            }
            if task.use_vision and image:
                kwargs["images"] = [Path(image)]

            output = client.chat(prompt, **kwargs).strip()
            return SubAgentResult(
                task.task_id, task.role, True, output=output,
                elapsed_ms=(time.perf_counter() - started) * 1000.0,
                model_tier=tier,
            )
        except Exception as exc:
            return SubAgentResult(
                task.task_id, task.role, False, error=str(exc),
                elapsed_ms=(time.perf_counter() - started) * 1000.0,
                model_tier=(locals().get("tier") or task.model_tier),
            )
        finally:
            if locals().get("balanced_acquired", False):
                self._balanced_slots.release()
            with self._state_lock:
                self._running = max(0, self._running - 1)
            self._slots.release()


DEFAULT_ROLES = (
    ("observador", "Descreva somente os fatos relevantes do estado atual.", "fast"),
    ("planejador", "Proponha o próximo passo mínimo e reversível.", "balanced"),
    ("crítico", "Procure riscos, ambiguidades e possíveis erros no plano.", "balanced"),
)


def default_tasks(goal: str, *, include_vision: bool = False) -> list[SubAgentTask]:
    tasks = []
    for role, instruction, tier in DEFAULT_ROLES:
        use_vision = include_vision and role == "observador"
        effective_tier = "vision" if use_vision else tier
        if include_vision and role in {"planejador", "crítico"}:
            effective_tier = "fast"
        tasks.append(
            SubAgentTask(
                role=role,
                instruction=f"Objetivo do usuário: {goal}. {instruction}",
                use_vision=use_vision,
                model_tier=effective_tier,
            )
        )
    return tasks
