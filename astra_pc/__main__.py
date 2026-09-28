from __future__ import annotations

import argparse
import random
import subprocess
import sys
from pathlib import Path

from .config import load_config


def _brain(config):
    from .ai.agent import AstraBrain
    from .ai.ollama_client import OllamaClient

    ai = config.data.get("ai", {})
    host = ai.get("host", "http://127.0.0.1:11434")
    timeout = int(ai.get("timeout", 180))
    keep_alive = ai.get("keep_alive", -1)

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
    strong_name = str(ai.get("strong_model", "")).strip()
    strong_client = (
        OllamaClient(strong_name, host=host, timeout=timeout, keep_alive="5m")
        if strong_name else None
    )
    return AstraBrain(text_client, vision_client, strong_client), text_client


def _run_gestures(args, config) -> None:
    from .core.runtime import AstraRuntime

    try:
        tutorial = None
        if getattr(args, "tutorial", False):
            tutorial = True
        elif getattr(args, "no_tutorial", False):
            tutorial = False
        AstraRuntime(
            config=config,
            show_camera=args.show_camera,
            dry_run=args.dry_run,
            voice_model=args.voice_model,
            tutorial=tutorial,
        ).run()
    except RuntimeError as exc:
        detail = str(exc)
        if detail.startswith("camera_unavailable:"):
            print("Astra não encontrou nenhuma câmera produzindo frames.")
            print("Rode: astra setup camera")
            print("Se estiver usando DroidCam, conecte o celular e depois tente novamente.")
            raise SystemExit(2)
        if detail.startswith("gesture_input_unavailable:") or "Wayland input is not ready" in detail:
            print("Backend de mouse/teclado dos gestos não está pronto.")
            print(detail)
            print("Rode: astra setup gestures")
            raise SystemExit(3)
        if detail == "gesture_tutorial_failed":
            print("O tutorial não foi concluído; o controle real não foi ativado.")
            print("Tente novamente com: astra gestures --tutorial")
            raise SystemExit(4)
        raise


def _run_setup(args, config) -> None:
    installer = Path(__file__).resolve().parent.parent / "installer.py"
    if not installer.exists():
        raise SystemExit("installer.py não foi encontrado.")

    cmd = [sys.executable, str(installer)]
    if args.setup_command == "camera":
        cmd.append("--camera-only")
    elif args.setup_command == "gestures":
        cmd.append("--gestures-only")
    elif args.setup_command == "voice":
        cmd.append("--voice-only")
        if getattr(args, "tts_voice", None):
            cmd.extend(["--tts-voice", args.tts_voice])
        if getattr(args, "microphone", None):
            cmd.extend(["--microphone", args.microphone])
        if getattr(args, "asr_model", None):
            cmd.extend(["--asr-model", args.asr_model])
    elif args.setup_command == "full":
        cmd.append("--full")
    elif args.setup_command == "location":
        destination = Path(args.path).expanduser().resolve()
        if sys.platform == "win32":
            script = installer.parent / "install.ps1"
            ps = "powershell"
            cmd = [
                ps,
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(script),
                "-InstallDir",
                str(destination),
            ]
            if args.portable_data:
                cmd.append("-PortableData")
            if args.yes:
                cmd.append("-Yes")
            raise SystemExit(subprocess.call(cmd, cwd=str(installer.parent)))
        script = installer.parent / "install.sh"
        cmd = ["bash", str(script), "--dest", str(destination)]
        if args.portable_data:
            cmd.append("--portable-data")
        if args.runtime_dir:
            cmd.extend(["--runtime-dir", str(Path(args.runtime_dir).expanduser())])
        if args.data_dir:
            cmd.extend(["--data-dir", str(Path(args.data_dir).expanduser())])
        if args.yes:
            cmd.append("--yes")
        try:
            raise SystemExit(subprocess.call(cmd, cwd=str(installer.parent)))
        except KeyboardInterrupt:
            print("\nMudança de local cancelada.")
            raise SystemExit(130)
    else:
        raise SystemExit("setup inválido")

    if getattr(args, "yes", False):
        cmd.append("--yes")
    if getattr(args, "allow_layering", False):
        cmd.append("--allow-layering")
    if getattr(args, "droidcam", None):
        cmd.extend(["--droidcam", args.droidcam])
    if getattr(args, "camera_scan_timeout", None) is not None:
        cmd.extend(["--camera-scan-timeout", str(args.camera_scan_timeout)])

    try:
        raise SystemExit(subprocess.call(cmd, cwd=str(installer.parent)))
    except KeyboardInterrupt:
        print("\nSetup cancelado.")
        raise SystemExit(130)


def _run_home(args, config) -> None:
    from .core.ipc import daemon_request
    from .vision.camera_source import open_first_camera

    daemon_cfg = config.data.get("daemon", {})
    daemon_online = False
    daemon_starting = False
    awareness = None
    daemon_host = daemon_cfg.get("host", "127.0.0.1")
    daemon_port = int(daemon_cfg.get("port", 8765))

    for attempt in range(8):
        try:
            ping = daemon_request(
                {"type": "ping"},
                host=daemon_host,
                port=daemon_port,
                timeout=0.45,
            )
            if ping.get("ok"):
                daemon_online = True
                break
        except Exception:
            if attempt < 7:
                __import__("time").sleep(0.18)

    if daemon_online:
        try:
            awareness = daemon_request(
                {"type": "awareness"},
                host=daemon_host,
                port=daemon_port,
                timeout=1.5,
            )
        except Exception:
            awareness = None
    elif sys.platform.startswith("linux"):
        try:
            state = subprocess.run(
                ["systemctl", "--user", "is-active", "astra-pc.service"],
                capture_output=True,
                text=True,
                timeout=0.8,
                check=False,
            )
            daemon_starting = state.stdout.strip() in {"active", "activating"}
        except Exception:
            pass

    camera = open_first_camera(
        preferred=int(config.data.get("camera", {}).get("index", 0)),
        width=320,
        height=180,
        fps=15,
        limit=16,
        warmup_reads=3,
    )
    if camera:
        camera_label = f"OK (camera {camera.index})"
        camera.cap.release()
    else:
        camera_label = "indisponível"

    mesh_online = bool((awareness or {}).get("mesh", {}).get("enabled"))
    print("============================================================")
    print(" ASTRA 0.8 // MESH")
    print("============================================================")
    daemon_label = "ONLINE" if daemon_online else ("STARTING" if daemon_starting else "OFFLINE")
    print(f"Daemon : {daemon_label}")
    print(f"Mesh   : {'ONLINE' if mesh_online else 'OFFLINE'}")
    print(f"Camera : {camera_label}")
    print()
    print("1 - Chat")
    print("2 - Voz")
    print("3 - Gestos")
    print("4 - Parear Android / outro dispositivo")
    print("5 - Awareness / status")
    print("6 - Configurar/reparar câmera")
    print("7 - Rodar instalador completo")
    print("8 - Instalar/migrar Astra para outra pasta/disco")
    print("9 - Configurar voz natural")
    print("0 - Sair")

    if not sys.stdin.isatty():
        print()
        print("Comandos úteis:")
        print("  astra chat")
        print("  astra voice --engine fast")
        print("  astra gestures              # first run opens tutorial")
        print("  astra setup gestures        # repair gesture stack")
        print("  astra gestures --tutorial   # replay tutorial")
        print("  astra mesh pair-code")
        print("  astra setup camera")
        return

    while True:
        try:
            choice = input("\nAstra> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return

        commands = {
            "1": ["chat"],
            "2": ["voice", "--engine", "fast"],
            "3": ["gestures"],
            "4": ["mesh", "pair-code"],
            "5": ["awareness"],
            "6": ["setup", "camera"],
            "7": ["setup", "full"],
            "8": ["setup", "location"],
            "9": ["setup", "voice"],
        }
        if choice in {"0", "q", "quit", "sair"}:
            return
        command = commands.get(choice)
        if not command:
            print("Escolha 0-9.")
            continue
        if choice == "8":
            try:
                target = input(
                    "Nova pasta do Astra (ex: /mnt/SSD/Astra-PC ou /run/media/USB/Astra-PC): "
                ).strip()
            except (EOFError, KeyboardInterrupt):
                print()
                continue
            if not target:
                print("Nenhum destino informado.")
                continue
            portable = input(
                "Guardar memória/cache junto com o Astra nesse disco? [y/N] "
            ).strip().lower() in {"y", "yes", "s", "sim"}
            command = ["setup", "location", target]
            if portable:
                command.append("--portable-data")
        try:
            subprocess.call([sys.executable, "-m", "astra_pc", *command])
        except KeyboardInterrupt:
            print("\nVoltando ao menu Astra.")
            continue


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
    from .core.ipc import daemon_request
    from .screen.capture import capture_screen

    daemon_cfg = config.data.get("daemon", {})
    try:
        result = daemon_request(
            {"type": "screen", "text": args.prompt},
            host=daemon_cfg.get("host", "127.0.0.1"),
            port=int(daemon_cfg.get("port", 8765)),
            timeout=60.0,
        )
        if result.get("ok"):
            print(result.get("message", ""))
            return
    except Exception:
        pass

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
    from .core.ipc import daemon_request
    from .voice.assistant import AstraVoiceAssistant

    brain, client = _brain(config)
    voice_cfg = config.data.get("voice", {})
    daemon_cfg = config.data.get("daemon", {})
    host = daemon_cfg.get("host", "127.0.0.1")
    port = int(daemon_cfg.get("port", 8765))

    request_handler = None
    target_seconds = max(
        2.0,
        float(voice_cfg.get("target_response_ms", 7000)) / 1000.0,
    )
    try:
        probe = daemon_request(
            {"type": "ping"},
            host=host,
            port=port,
            timeout=0.8,
        )
        if probe.get("ok"):
            def resident_request(text: str) -> str:
                result = daemon_request(
                    {"type": "ask", "text": text},
                    host=host,
                    port=port,
                    timeout=target_seconds,
                )
                if not result.get("ok"):
                    raise RuntimeError(result.get("error") or "daemon request failed")
                return str(result.get("message", ""))
            request_handler = resident_request
            print("[voice] using resident Astra daemon")
    except Exception:
        request_handler = None

    restore_resident_voice = False
    if request_handler is not None:
        try:
            status = daemon_request(
                {"type": "voice.status"},
                host=host,
                port=port,
                timeout=1.0,
            )
            if status.get("active"):
                stopped = daemon_request(
                    {"type": "voice.stop"},
                    host=host,
                    port=port,
                    timeout=3.0,
                )
                restore_resident_voice = bool(stopped.get("ok"))
                if restore_resident_voice:
                    print("[voice] resident microphone handed to foreground session")
                    __import__("time").sleep(0.2)
        except Exception:
            restore_resident_voice = False

    if request_handler is None and not client.available():
        raise SystemExit(
            "Ollama is not reachable. Run installer.py or start 'ollama serve'."
        )

    from .voice.piper_tts import load_voice_state, resolve_piper_model
    voice_state = load_voice_state()
    piper_model = resolve_piper_model(voice_cfg.get("piper_model") or None)
    whisper_model = (
        args.whisper_model
        or voice_state.get("whisper_model")
        or voice_cfg.get("whisper_model", "small")
    )
    language = (
        args.language
        or voice_state.get("language")
        or voice_cfg.get("language", "pt")
    )
    input_device = voice_state.get("input_device_name") or None
    if not input_device and voice_state.get("input_device_index") is not None:
        input_device = int(voice_state["input_device_index"])

    assistant = AstraVoiceAssistant(
        brain,
        args.voice_model,
        wake_word=args.wake_word,
        speak=not args.no_speak,
        engine=args.engine,
        whisper_model=whisper_model,
        language=language,
        request_handler=request_handler,
        conversation_window=float(voice_cfg.get("conversation_window", 9.0)),
        wakeword_model=args.wakeword_model,
        wakeword_threshold=args.wakeword_threshold,
        piper_model=piper_model,
        input_device=input_device,
        silence_ms=int(voice_state.get("silence_ms", voice_cfg.get("silence_ms", 260))),
        pre_roll_ms=int(voice_state.get("pre_roll_ms", voice_cfg.get("pre_roll_ms", 200))),
        adaptive_retry=bool(voice_state.get("adaptive_retry", True)),
    )
    try:
        assistant.run()
    finally:
        if restore_resident_voice:
            try:
                daemon_request(
                    {"type": "voice.start", "no_speak": args.no_speak},
                    host=host,
                    port=port,
                    timeout=3.0,
                )
                print("[voice] resident microphone restored")
            except Exception as exc:
                print(f"[voice] could not restore resident listener: {exc}")


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


def _run_awareness(args, config) -> None:
    import json
    from .core.ipc import daemon_request
    daemon_cfg = config.data.get("daemon", {})
    result = daemon_request(
        {"type": "awareness"},
        host=daemon_cfg.get("host", "127.0.0.1"),
        port=int(daemon_cfg.get("port", 8765)),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


def _run_memory(args, config) -> None:
    import json
    from .core.ipc import daemon_request
    daemon_cfg = config.data.get("daemon", {})
    result = daemon_request(
        {"type": "memory.search", "text": args.query},
        host=daemon_cfg.get("host", "127.0.0.1"),
        port=int(daemon_cfg.get("port", 8765)),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


def _run_learn(args, config) -> None:
    from .automation.recorder import ActionRecorder
    print("Learning mode: perform the task now. Press ESC to finish recording.")
    path = ActionRecorder().record(args.name, max_seconds=args.max_seconds)
    print(path)


def _run_replay(args, config) -> None:
    from pathlib import Path
    from .automation.replay import ActionReplayer
    from .paths import data_dir
    base = data_dir() / "macros"
    path = Path(args.path_or_name).expanduser()
    if not path.exists():
        path = base / (args.path_or_name.lower().replace(" ", "-") + ".json")
    ActionReplayer().replay(path, speed=args.speed)
    print("Replay complete.")


def _run_mobile(args, config) -> None:
    from .mobile.server import MobileCompanionServer
    mobile = config.data.get("mobile", {})
    MobileCompanionServer(
        host=args.host or mobile.get("host", "0.0.0.0"),
        port=args.port or int(mobile.get("port", 8766)),
        token=args.token,
    ).run()


def _run_mesh(args, config) -> None:
    import json
    import socket
    from .core.ipc import daemon_request
    from .mesh.discovery import discover
    from .mesh.client import MeshHttpClient, MeshPeer
    from .mesh.qr import render_terminal_qr

    daemon_cfg = config.data.get("daemon", {})
    host = daemon_cfg.get("host", "127.0.0.1")
    port = int(daemon_cfg.get("port", 8765))

    if args.mesh_command == "pair-code":
        payload = {"type": "mesh.pair_code", "ttl": args.ttl}
        if args.qr:
            payload["qr"] = str(args.qr)
        result = daemon_request(payload, host=host, port=port)
        if result.get("ok"):
            print(f"Pairing code: {result.get('code')}")
            print(f"Host: {result.get('host')}:{result.get('port')}")
            print(f"Fingerprint: {result.get('fingerprint')}")
            print(f"Expires: {result.get('expires_at')}")
            print()
            render_terminal_qr(str(result.get("uri", "")))
            if result.get("qr_path"):
                print("\nQR image:", result["qr_path"])
        else:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    if args.mesh_command == "devices":
        result = daemon_request({"type": "mesh.devices"}, host=host, port=port)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    if args.mesh_command == "revoke":
        result = daemon_request(
            {"type": "mesh.revoke", "device_id": args.device_id},
            host=host,
            port=port,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    if args.mesh_command == "discover":
        print(json.dumps(discover(args.timeout_ms), ensure_ascii=False, indent=2))
        return

    if args.mesh_command == "send":
        payload = {
            "type": "mesh.device_command",
            "device_id": args.device_id,
            "action": args.action,
            "payload": {"text": args.text},
        }
        result = daemon_request(payload, host=host, port=port)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    if args.mesh_command == "pair":
        peer = MeshPeer(
            host=args.host,
            port=args.port,
            fingerprint=args.fingerprint,
        )
        client = MeshHttpClient(peer)
        result = client.pair(
            args.code,
            name=args.name or socket.gethostname(),
            device_id=args.device_id,
            platform="desktop",
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return


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
    gestures.add_argument("--tutorial", action="store_true", help="force interactive gesture tutorial")
    gestures.add_argument("--no-tutorial", action="store_true", help="skip first-run tutorial")

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
    voice.add_argument("--whisper-model", default=None, help="override faster-whisper model: tiny/base/small")
    voice.add_argument("--language", default=None)
    voice.add_argument("--no-speak", action="store_true")
    voice.add_argument("--wakeword-model", type=Path, default=None)
    voice.add_argument("--wakeword-threshold", type=float, default=0.55)

    benchmark = sub.add_parser("benchmark", help="measure local Astra response latency")
    benchmark.add_argument("--rounds", type=int, default=3)

    sub.add_parser("awareness", help="show Astra's current context/perception state")

    memory = sub.add_parser("memory", help="semantic search through local Astra memory")
    memory.add_argument("query")

    learn = sub.add_parser("learn", help="observe mouse/keyboard actions and save a local macro")
    learn.add_argument("name")
    learn.add_argument("--max-seconds", type=int, default=120)

    replay = sub.add_parser("replay", help="replay an explicitly learned local macro")
    replay.add_argument("path_or_name")
    replay.add_argument("--speed", type=float, default=1.0)

    mobile = sub.add_parser("mobile", help="run the local phone/sensor companion bridge")
    mobile.add_argument("--host", default=None)
    mobile.add_argument("--port", type=int, default=None)
    mobile.add_argument("--token", default=None)

    mesh = sub.add_parser("mesh", help="Astra Mesh multi-device networking")
    mesh_sub = mesh.add_subparsers(dest="mesh_command", required=True)

    mesh_pair_code = mesh_sub.add_parser("pair-code", help="create a one-time Android/PC pairing code")
    mesh_pair_code.add_argument("--ttl", type=int, default=300)
    mesh_pair_code.add_argument("--qr", type=Path, default=None)

    mesh_sub.add_parser("devices", help="list paired Mesh devices")

    mesh_revoke = mesh_sub.add_parser("revoke", help="revoke a paired device")
    mesh_revoke.add_argument("device_id")

    mesh_discover = mesh_sub.add_parser("discover", help="discover Astra Mesh nodes on the LAN")
    mesh_discover.add_argument("--timeout-ms", type=int, default=1800)

    mesh_send = mesh_sub.add_parser("send", help="send a safe command to a paired device")
    mesh_send.add_argument("device_id")
    mesh_send.add_argument("action", choices=["notify", "clipboard.set"])
    mesh_send.add_argument("text")

    mesh_pair = mesh_sub.add_parser("pair", help="pair this desktop to another Astra Mesh node")
    mesh_pair.add_argument("host")
    mesh_pair.add_argument("port", type=int)
    mesh_pair.add_argument("fingerprint")
    mesh_pair.add_argument("code")
    mesh_pair.add_argument("--name", default=None)
    mesh_pair.add_argument("--device-id", default=None)

    setup = sub.add_parser("setup", help="guided Astra setup/repair")
    setup_sub = setup.add_subparsers(dest="setup_command", required=True)
    setup_gestures = setup_sub.add_parser(
        "gestures",
        help="repair camera/input backend and prepare interactive gesture tutorial",
    )
    setup_gestures.add_argument("--yes", action="store_true")
    setup_gestures.add_argument("--allow-layering", action="store_true")

    setup_camera = setup_sub.add_parser("camera", help="detect/install/configure camera or DroidCam")
    setup_camera.add_argument("--yes", action="store_true")
    setup_camera.add_argument("--allow-layering", action="store_true")
    setup_camera.add_argument(
        "--droidcam",
        default=None,
        help="DroidCam IP:port, e.g. 192.168.1.50:4747",
    )
    setup_camera.add_argument(
        "--scan-timeout",
        dest="camera_scan_timeout",
        type=float,
        default=10.0,
        help="automatic LAN discovery timeout in seconds",
    )

    setup_voice = setup_sub.add_parser(
        "voice",
        help="install/change Astra's natural local pt-BR voice",
    )
    setup_voice.add_argument(
        "--voice",
        dest="tts_voice",
        default=None,
        choices=["pt_BR-faber-medium", "pt_BR-cadu-medium", "pt_BR-jeff-medium"],
    )
    setup_voice.add_argument("--microphone", default=None, help="microphone index or name substring")
    setup_voice.add_argument(
        "--asr-model",
        choices=["base", "small"],
        default=None,
        help="speech recognition model",
    )
    setup_voice.add_argument("--yes", action="store_true")
    setup_full = setup_sub.add_parser("full", help="run the complete guided installer")
    setup_full.add_argument("--yes", action="store_true")
    setup_full.add_argument("--allow-layering", action="store_true")

    setup_location = setup_sub.add_parser(
        "location",
        help="install/migrate Astra to another folder, disk or USB drive",
    )
    setup_location.add_argument("path")
    setup_location.add_argument("--portable-data", action="store_true")
    setup_location.add_argument("--runtime-dir", default=None)
    setup_location.add_argument("--data-dir", default=None)
    setup_location.add_argument("--yes", action="store_true")

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

    command = args.command or "home"

    runners = {
        "home": _run_home,
        "setup": _run_setup,
        "gestures": _run_gestures,
        "ask": _run_ask,
        "see": _run_see,
        "screen": _run_screen,
        "video": _run_video,
        "chat": _run_chat,
        "voice": _run_voice,
        "benchmark": _run_benchmark,
        "awareness": _run_awareness,
        "memory": _run_memory,
        "learn": _run_learn,
        "replay": _run_replay,
        "mobile": _run_mobile,
        "mesh": _run_mesh,
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
