from __future__ import annotations

import compileall
import importlib
import platform
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from astra_pc.ai.ollama_client import OllamaClient
from astra_pc.input.factory import create_input_backend
from astra_pc.perception.monitors import get_monitors, virtual_bounds


def _check(name: str, ok: bool, detail: str, elapsed_ms: float = 0.0) -> dict[str, Any]:
    return {
        "name": name,
        "ok": bool(ok),
        "detail": str(detail),
        "elapsed_ms": round(float(elapsed_ms), 1),
    }


def _timed(name: str, fn) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        detail = fn()
        return _check(name, True, str(detail), (time.perf_counter() - started) * 1000.0)
    except Exception as exc:
        return _check(name, False, f"{type(exc).__name__}: {exc}", (time.perf_counter() - started) * 1000.0)


def run_diagnostics(config, *, deep: bool = False) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    root = Path(__file__).resolve().parent

    checks.append(
        _check(
            "python",
            sys.version_info >= (3, 12),
            f"{platform.python_version()} ({sys.executable})",
        )
    )

    required_sections = ("ai", "voice", "daemon", "agent", "swarm", "mission")
    missing = [name for name in required_sections if not isinstance(config.data.get(name), dict)]
    checks.append(
        _check(
            "config",
            not missing,
            "ok" if not missing else "missing sections: " + ", ".join(missing),
        )
    )

    def compile_package():
        ok = compileall.compile_dir(str(root), quiet=2, force=False)
        if not ok:
            raise RuntimeError("compileall reported syntax errors")
        return "all astra_pc modules compile"

    checks.append(_timed("syntax", compile_package))

    modules = (
        "astra_pc.core.daemon",
        "astra_pc.ai.desktop_agent",
        "astra_pc.ai.swarm",
        "astra_pc.ai.tools",
        "astra_pc.voice.assistant",
        "astra_pc.voice.fast_whisper",
        "astra_pc.perception.monitors",
    )

    def imports():
        for module in modules:
            importlib.import_module(module)
        return f"{len(modules)} core modules imported"

    checks.append(_timed("imports", imports))

    ai = config.data.get("ai", {})
    host = ai.get("host", "http://127.0.0.1:11434")
    timeout = min(10, int(ai.get("timeout", 180)))
    probe = OllamaClient(ai.get("fast_model", "qwen3:0.6b"), host, timeout, 0)

    def ollama():
        if not probe.available():
            raise RuntimeError(f"Ollama not reachable at {host}")
        models = probe.models()
        required = [
            str(ai.get("fast_model", "")).strip(),
            str(ai.get("text_model", "")).strip(),
            str(ai.get("vision_model", "")).strip(),
        ]
        missing_models = [
            model for model in required
            if model and not any(item == model or item.startswith(model + ":") for item in models)
        ]
        if missing_models:
            raise RuntimeError("missing models: " + ", ".join(missing_models))
        return f"reachable; {len(models)} local models; required models present"

    checks.append(_timed("ollama", ollama))

    def monitors():
        items = get_monitors()
        if not items:
            raise RuntimeError("no monitors detected")
        bounds = virtual_bounds(items)
        return f"{len(items)} monitor(s); virtual desktop={bounds[2]}x{bounds[3]} origin={bounds[0]},{bounds[1]}"

    checks.append(_timed("monitors", monitors))

    def input_backend():
        backend = create_input_backend()
        try:
            health = getattr(backend, "health", None)
            value = health() if health else "backend created"
            return str(value)
        finally:
            close = getattr(backend, "close", None)
            if close:
                close()

    checks.append(_timed("input_backend", input_backend))

    swarm = config.data.get("swarm", {})
    max_agents = int(swarm.get("max_agents", 100))
    max_workers = int(swarm.get("max_workers", 3))
    swarm_ok = 1 <= max_agents <= 100 and 1 <= max_workers <= 8 and max_workers <= max_agents
    checks.append(
        _check(
            "swarm_config",
            swarm_ok,
            f"max_agents={max_agents}, max_workers={max_workers}, enabled={bool(swarm.get('enabled', True))}",
        )
    )

    if platform.system() == "Linux":
        def service_state():
            enabled = subprocess.run(
                ["systemctl", "--user", "is-enabled", "astra-pc.service"],
                capture_output=True, text=True, check=False, timeout=3,
            ).stdout.strip() or "unknown"
            active = subprocess.run(
                ["systemctl", "--user", "is-active", "astra-pc.service"],
                capture_output=True, text=True, check=False, timeout=3,
            ).stdout.strip() or "unknown"
            return f"enabled={enabled}; active={active}"

        checks.append(_timed("service", service_state))

    if deep:
        from PIL import Image
        from astra_pc.screen.capture import capture_screen

        def capture():
            path = capture_screen()
            try:
                with Image.open(path) as image:
                    return f"capture={image.width}x{image.height}"
            finally:
                path.unlink(missing_ok=True)

        checks.append(_timed("screen_capture", capture))

    failures = [item for item in checks if not item["ok"]]
    return {
        "ok": not failures,
        "summary": {
            "passed": len(checks) - len(failures),
            "failed": len(failures),
            "total": len(checks),
        },
        "checks": checks,
    }
