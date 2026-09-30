import time

from astra_pc.voice.assistant import AstraVoiceAssistant
from astra_pc.voice.commands import CommandRouter


class ExplodingBrain:
    def ask_voice(self, *args, **kwargs):
        raise AssertionError("resident voice should use daemon context handler")

    def ask_voice_stream(self, *args, **kwargs):
        raise AssertionError("resident voice should use daemon context handler")


def test_resident_voice_routes_normal_conversation_through_daemon_context():
    assistant = object.__new__(AstraVoiceAssistant)
    assistant.router = CommandRouter()
    assistant.request_handler = lambda text: f"contextual:{text}"
    assistant.brain = ExplodingBrain()
    assistant.speaker = None
    assistant.conversation_window = 12.0
    assistant._conversation_until = 0.0

    spoken = []
    assistant._speak = spoken.append

    assistant._answer("e esse aplicativo?", time.perf_counter())

    assert spoken == ["contextual:e esse aplicativo?"]


def test_resident_voice_can_stream_daemon_answer():
    assistant = object.__new__(AstraVoiceAssistant)
    assistant.router = CommandRouter()
    assistant.request_handler = lambda text: f"fallback:{text}"
    assistant.stream_handler = lambda text: iter(("resposta ", "em ", "stream"))
    assistant.brain = ExplodingBrain()
    assistant.speaker = None
    assistant.conversation_window = 12.0
    assistant._conversation_until = 0.0

    spoken = []
    assistant._speak = spoken.append

    assistant._answer("fala comigo", time.perf_counter())

    assert spoken == ["resposta em stream"]
