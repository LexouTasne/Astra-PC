from __future__ import annotations

import argparse
import random
from pathlib import Path

from .config import load_config


def _brain(config):
    from .ai.agent import AstraBrain
    from .ai.ollama_client import OllamaClient

    ai = config.data.get("ai", {})
    host = ai.get("host", "http://127.0.0.1:11434")
    timeout = int(ai.get("timeout", 180))
    keep_alive = ai.get("keep_alive", "-1")

    text_client = OllamaClient(
        model=ai.get("text_model", "qwen3:0.6b"),
        host=host,
        timeout=timeout,
        keep_alive=keep_alive,
    )
    vision_client = OllamaClient(
        model=ai.get("vision_model", "qwen3-vl:2b-instruct"),
        host=host,
        timeout=timeout,
        keep_alive=keep_alive,
    )
    return AstraBrain(text_client, vision_client), text_client


def _run_gestures(args, config) -> None:
    from .core.runtime import AstraRuntime

    AstraRuntime(
        config=config,
        show_camera=args.show_camera,
        dry_run=args.dry_run,
        voice_model=args.voice_model,
    ).run()


def _run_ask(args, config) -> None:
    from .core.ipc import daemon_request

    daemon_cfg = config.data.get("daemon", {})
    try:
        result = daemon_request(
            {"type": "ask", "text": args.prompt},
            host=daemon_cfg.get("host", "127.0.0.1"),
            port=int(daemon_cfg.get("port", 8765)),
            timeout=8.0,
        )
        if result.get("ok"):
            print(result.get("message", ""))
            return
    except Exception:
        pass

    brain, _ = _brain(config)
    print(brain.ask(args.prompt))


def _run_see(args, config) -> None:
    brain, _ = _brain(config)
    print(brain.see(args.image, args.prompt))


def _run_screen(args, config) -> None:
    from .screen.capture import capture_screen

    brain, _ = _brain(config)
    shot = capture_screen()
    try:
        print(brain.see(shot, args.prompt))
    finally:
        if not args.keep:
            shot.unlink(missing_ok=True)
        else:
            print(f"[Astra] screenshot: {shot}")


def _run_video(args, config) -> None:
    from .media.video_understanding import understand_video

    brain, _ = _brain(config)
    print(
        understand_video(
            brain,
            args.video,
            args.prompt,
            frame_count=args.frames,
        )
    )


def _run_chat(args, config) -> None:
    from .core.ipc import daemon_request

    daemon_cfg = config.data.get("daemon", {})
    host = daemon_cfg.get("host", "127.0.0.1")
    port = int(daemon_cfg.get("port", 8765))

    brain = client = None
    print("Astra chat. Uses resident daemon when available. Type /exit to leave.")
    while True:
        try:
            text = input("You> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if not text:
            continue
        if text in {"/exit", "/quit"}:
            return

        try:
            result = daemon_request(
                {"type": "ask", "text": text},
                host=host,
                port=port,
                timeout=30.0,
            )
            if result.get("ok"):
                print("Astra>", result.get("message", ""))
                continue
        except Exception:
            pass

        if brain is None:
            brain, client = _brain(config)
            if not client.available():
                raise SystemExit(
                    "Ollama is not reachable. Run installer.py or start 'ollama serve'."
                )
        print("Astra>", brain.ask(text))


def _run_voice(args, config) -> None:
    from .voice.assistant import AstraVoiceAssistant

    brain, client = _brain(config)
    if not client.available():
        raise SystemExit(
            "Ollama is not reachable. Run installer.py or start 'ollama serve'."
        )
    assistant = AstraVoiceAssistant(
        brain,
        args.voice_model,
        wake_word=args.wake_word,
        speak=not args.no_speak,
        engine=args.engine,
        whisper_model=args.whisper_model,
        language=args.language,
    )
    assistant.run()


def _run_daemon(args, config) -> None:
    from .core.daemon import AstraDaemon
    AstraDaemon(config).run(
        voice=args.voice,
        no_speak=args.no_speak,
    )


def _run_ctl(args, config) -> None:
    import json
    from .core.ipc import daemon_request

    daemon_cfg = config.data.get("daemon", {})
    host = daemon_cfg.get("host", "127.0.0.1")
    port = int(daemon_cfg.get("port", 8765))

    payload = {"type": args.type}
    if args.text is not None:
        payload["text"] = args.text
    if args.confirmed:
        payload["confirmed"] = True

    result = daemon_request(payload, host=host, port=port, timeout=args.timeout)
    print(json.dumps(result, ensure_ascii=False, indent=2))


def _run_profile(args, config) -> None:
    from .core.ipc import daemon_request

    daemon_cfg = config.data.get("daemon", {})
    result = daemon_request(
        {"type": "profile", "profile": args.name},
        host=daemon_cfg.get("host", "127.0.0.1"),
        port=int(daemon_cfg.get("port", 8765)),
    )
    print(result.get("profile") or result)


def _run_routine(args, config) -> None:
    import json
    from .core.ipc import daemon_request

    daemon_cfg = config.data.get("daemon", {})
    host = daemon_cfg.get("host", "127.0.0.1")
    port = int(daemon_cfg.get("port", 8765))

    if args.routine_command == "run":
        payload = {
            "type": "routine.run",
            "name": args.name,
            "confirmed": args.yes,
        }
    else:
        steps = json.loads(args.steps)
        payload = {
            "type": "routine.save",
            "name": args.name,
            "steps": steps,
        }

    result = daemon_request(payload, host=host, port=port)
    print(json.dumps(result, ensure_ascii=False, indent=2))


def _run_agent(args, config) -> None:
    from .ai.desktop_agent import VisualDesktopAgent

    brain, text_client = _brain(config)
    client = brain.vision_client
    if not text_client.available():
        raise SystemExit(
            "Ollama is not reachable. Run installer.py or start 'ollama serve'."
        )
    agent = VisualDesktopAgent(client, max_steps=args.max_steps)
    result = agent.run(args.goal, auto_confirm=args.yes)
    print("Astra>", result)


def _run_benchmark(args, config) -> None:
    from .performance import benchmark_brain

    brain, client = _brain(config)
    if not client.available():
        raise SystemExit(
            "Ollama is not reachable. Run installer.py or start 'ollama serve'."
        )
    benchmark_brain(brain, rounds=args.rounds)


def _run_generate(args, config) -> None:
    from .media.comfyui import ComfyUIClient

    media = config.data.get("media", {})
    comfy_cfg = media.get("comfyui", {})
    client = ComfyUIClient(
        host=comfy_cfg.get("host", "http://127.0.0.1:8188"),
        timeout=int(comfy_cfg.get("timeout", 600)),
    )
    if not client.available():
        raise SystemExit(
            "ComfyUI is not reachable at the configured address. "
            "Start ComfyUI or change media.comfyui.host."
        )

    workflow = args.workflow or comfy_cfg.get("image_workflow")
    if not workflow:
        raise SystemExit("No ComfyUI workflow configured. Use --workflow.")

    checkpoint = args.checkpoint or comfy_cfg.get("checkpoint", "")
    if not checkpoint:
        raise SystemExit(
            "No ComfyUI checkpoint configured. Set media.comfyui.checkpoint "
            "in config/astra.json or pass --checkpoint."
        )

    replacements = {
        "PROMPT": args.prompt,
        "NEGATIVE": args.negative,
        "WIDTH": str(args.width),
        "HEIGHT": str(args.height),
        "SEED": str(args.seed if args.seed is not None else random.randrange(1, 2**31)),
        "CHECKPOINT": checkpoint,
    }
    outputs = client.run_workflow(
        workflow,
        replacements=replacements,
        output_dir=args.output,
    )
    for path in outputs:
        print(path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Astra-PC — local gesture + multimodal desktop assistant"
    )
    parser.add_argument("--config", type=Path, default=None)
    sub = parser.add_subparsers(dest="command")

    gestures = sub.add_parser("gestures", help="start real-time hand control")
    gestures.add_argument("--show-camera", action="store_true")
    gestures.add_argument("--dry-run", action="store_true")
    gestures.add_argument("--voice-model", type=Path)

    ask = sub.add_parser("ask", help="ask Astra's local Qwen brain")
    ask.add_argument("prompt")

    see = sub.add_parser("see", help="understand an image")
    see.add_argument("image", type=Path)
    see.add_argument("prompt", nargs="?", default="Describe and analyze this image.")

    screen = sub.add_parser("screen", help="capture and understand the current screen")
    screen.add_argument("prompt", nargs="?", default="What is visible on my screen?")
    screen.add_argument("--keep", action="store_true")

    video = sub.add_parser("video", help="understand a local video using sampled frames")
    video.add_argument("video", type=Path)
    video.add_argument("prompt", nargs="?", default="Summarize what happens in this video.")
    video.add_argument("--frames", type=int, default=6)

    sub.add_parser("chat", help="interactive local Astra chat")

    voice = sub.add_parser("voice", help="wake-word local voice assistant")
    voice.add_argument("--voice-model", type=Path, default=None, help="Vosk model path for fallback engine")
    voice.add_argument("--wake-word", default="astra")
    voice.add_argument("--engine", choices=["fast", "vosk"], default="fast")
    voice.add_argument("--whisper-model", default="base", help="faster-whisper model: tiny/base/small")
    voice.add_argument("--language", default="pt")
    voice.add_argument("--no-speak", action="store_true")

    benchmark = sub.add_parser("benchmark", help="measure local Astra response latency")
    benchmark.add_argument("--rounds", type=int, default=3)

    daemon = sub.add_parser("daemon", help="run the resident Astra core")
    daemon.add_argument("--voice", action="store_true", help="keep Astra listening in the daemon")
    daemon.add_argument("--no-speak", action="store_true", help="disable spoken replies")

    ctl = sub.add_parser("ctl", help="talk to the resident Astra daemon")
    ctl.add_argument("type", choices=["ping", "ask", "context", "stop"])
    ctl.add_argument("text", nargs="?")
    ctl.add_argument("--confirmed", action="store_true")
    ctl.add_argument("--timeout", type=float, default=30.0)

    profile = sub.add_parser("profile", help="switch Astra context profile")
    profile.add_argument("name")

    routine = sub.add_parser("routine", help="save or run a persistent routine")
    routine_sub = routine.add_subparsers(dest="routine_command", required=True)
    routine_run = routine_sub.add_parser("run")
    routine_run.add_argument("name")
    routine_run.add_argument("--yes", action="store_true")
    routine_save = routine_sub.add_parser("save")
    routine_save.add_argument("name")
    routine_save.add_argument(
        "steps",
        help='JSON list, e.g. [{"skill":"apps","action":"open_app","args":{"name":"vscode"}}]',
    )

    agent = sub.add_parser("agent", help="screen-aware local desktop agent")
    agent.add_argument("goal")
    agent.add_argument("--max-steps", type=int, default=8)
    agent.add_argument(
        "--yes",
        action="store_true",
        help="execute allowed agent actions without per-step confirmation",
    )

    generate = sub.add_parser("generate", help="run a local ComfyUI media workflow")
    generate.add_argument("prompt")
    generate.add_argument("--workflow", type=Path)
    generate.add_argument("--checkpoint", default=None)
    generate.add_argument("--negative", default="low quality, blurry, distorted")
    generate.add_argument("--width", type=int, default=512)
    generate.add_argument("--height", type=int, default=512)
    generate.add_argument("--seed", type=int)
    generate.add_argument("--output", type=Path, default=Path("outputs"))

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    config = load_config(args.config)

    command = args.command or "gestures"
    if args.command is None:
        args.show_camera = False
        args.dry_run = False
        args.voice_model = None

    runners = {
        "gestures": _run_gestures,
        "ask": _run_ask,
        "see": _run_see,
        "screen": _run_screen,
        "video": _run_video,
        "chat": _run_chat,
        "voice": _run_voice,
        "benchmark": _run_benchmark,
        "daemon": _run_daemon,
        "ctl": _run_ctl,
        "profile": _run_profile,
        "routine": _run_routine,
        "agent": _run_agent,
        "generate": _run_generate,
    }
    runners[command](args, config)


if __name__ == "__main__":
    main()
