from __future__ import annotations

import threading
import unittest

from astra_pc.ai.desktop_agent import VisualDesktopAgent
from astra_pc.ai.tools import DesktopTools
from astra_pc.core.daemon import AstraDaemon
from astra_pc.input.wayland_backend import YdotoolBackend, _KEYCODES
from astra_pc.perception.monitors import Monitor, virtual_bounds


class VisualAgentCoreTests(unittest.TestCase):
    def test_visual_intent_routes_visual_actions_only(self):
        yes = (
            "Astra, olha a tela e clica no WhatsApp",
            "clica no WhatsApp",
            "segura W até chegar lá",
            "acha o botão de entrar e clica",
        )
        no = ("que horas são?", "me explica Python", "abre o Firefox")
        for text in yes:
            self.assertTrue(AstraDaemon._wants_visual_agent(text), text)
        for text in no:
            self.assertFalse(AstraDaemon._wants_visual_agent(text), text)

    def test_virtual_desktop_bounds(self):
        monitors = [
            Monitor(x=0, y=643, width=1280, height=720, name="secondary"),
            Monitor(x=1280, y=0, width=1920, height=1080, name="primary", primary=True),
        ]
        self.assertEqual(virtual_bounds(monitors), (0, 0, 3200, 1363))

    def test_screenshot_to_desktop_mapping_supports_negative_origins(self):
        tools = object.__new__(DesktopTools)
        tools.origin_x, tools.origin_y = -1920, 0
        tools.width, tools.height = 3840, 1080
        self.assertEqual(tools._screen_to_desktop(0, 0), (-1920, 0))
        self.assertEqual(tools._screen_to_desktop(3839, 1079), (1919, 1079))

    def test_action_parser_accepts_plain_and_fenced_json(self):
        plain = '{"action":"wait","seconds":0}'
        fence = chr(96) * 3
        fenced = fence + 'json\n{"action":"click","x":10,"y":20}\n' + fence
        self.assertEqual(VisualDesktopAgent._parse_action(plain)["action"], "wait")
        self.assertEqual(VisualDesktopAgent._parse_action(fenced)["action"], "click")

    def test_wayland_key_hold_release_without_hardware(self):
        backend = object.__new__(YdotoolBackend)
        backend._left_down = False
        backend._keys_down = set()
        backend._pending_wheel = 0
        backend._wheel_lock = threading.Lock()
        backend._wake = threading.Event()
        calls = []
        backend._queue_command = lambda *args: calls.append(args)
        backend._execute = lambda args: calls.append(("direct", *args))

        for key in ("w", "a", "s", "d", "space", "shift", "f12", "1", "left"):
            backend.key_down(key)
        for key in ("left", "1", "f12", "shift", "space", "d", "s", "a", "w"):
            backend.key_up(key)

        self.assertFalse(backend._keys_down)
        self.assertIn(("key", "17:1"), calls)
        self.assertIn(("key", "17:0"), calls)
        self.assertGreaterEqual(len(_KEYCODES), 100)


class VoicePartialPipelineTests(unittest.TestCase):
    def test_partial_voice_preview_queues_before_final(self):
        import queue
        import time
        from astra_pc.voice.assistant import AstraVoiceAssistant

        voice = object.__new__(AstraVoiceAssistant)
        voice.preview_handler = lambda text: None
        voice._dictation_lock = threading.Lock()
        voice._dictation_target = None
        voice.wake_word = "astra"
        voice._conversation_until = 0.0
        voice._dedicated_wake_until = 0.0
        voice._last_preview = ""
        voice._previews = queue.Queue(maxsize=1)

        voice._on_partial("Astra clica no WhatsApp")
        self.assertEqual(voice._previews.get_nowait(), "clica no WhatsApp")

        voice._on_partial("Astra clica no WhatsApp")
        self.assertTrue(voice._previews.empty())

        voice._conversation_until = time.monotonic() + 5.0
        voice._on_partial("agora abre essa janela")
        self.assertEqual(voice._previews.get_nowait(), "agora abre essa janela")

    def test_partial_queue_keeps_latest_snapshot(self):
        import queue
        from astra_pc.voice.fast_whisper import FastWhisperVoiceEngine

        engine = object.__new__(FastWhisperVoiceEngine)
        engine.on_partial = lambda text: None
        engine._partials = queue.Queue(maxsize=1)

        engine._enqueue_partial(b"first")
        engine._enqueue_partial(b"second")
        self.assertEqual(engine._partials.get_nowait(), b"second")

if __name__ == "__main__":
    unittest.main()
