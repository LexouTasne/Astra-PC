import queue
import threading

from astra_pc.voice.assistant import AstraVoiceAssistant


def test_resident_dictation_consumes_next_transcript_without_wakeword():
    assistant = object.__new__(AstraVoiceAssistant)
    assistant._dictation_lock = threading.Lock()
    target = queue.Queue(maxsize=1)
    assistant._dictation_target = target

    assistant._on_text("fecha o Discord")

    assert target.get_nowait() == "fecha o Discord"
    assert assistant._dictation_target is None
