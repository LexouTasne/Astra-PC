import subprocess
import sys
import time

from astra_pc.core import process_guard


def test_registered_process_is_terminated_cross_platform(tmp_path, monkeypatch):
    monkeypatch.setenv("ASTRA_DATA_DIR", str(tmp_path))

    child = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import time; time.sleep(60)",
        ]
    )
    try:
        process_guard.register_process("test-helper", child.pid)
        assert child.poll() is None

        assert process_guard.terminate_recorded_process(
            "test-helper",
            timeout=1.0,
        )

        deadline = time.monotonic() + 2.0
        while child.poll() is None and time.monotonic() < deadline:
            time.sleep(0.02)

        assert child.poll() is not None
        assert "test-helper" not in process_guard._read_state()
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=2)


def test_unregister_does_not_remove_different_pid(tmp_path, monkeypatch):
    monkeypatch.setenv("ASTRA_DATA_DIR", str(tmp_path))

    process_guard.register_process("gestures")
    own_pid = process_guard._read_state()["gestures"]["pid"]

    process_guard.unregister_process("gestures", own_pid + 123)

    assert process_guard._read_state()["gestures"]["pid"] == own_pid
    process_guard.unregister_process("gestures", own_pid)
    assert "gestures" not in process_guard._read_state()
