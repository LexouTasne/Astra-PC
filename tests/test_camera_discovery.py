from astra_pc.vision import camera_source as camera


class DummyCap:
    def read(self):
        return False, None

    def release(self):
        pass


def test_camera_source_coercion():
    assert camera._coerce_source("0") == 0
    assert camera._coerce_source("  /dev/video4 ") == "/dev/video4"
    assert camera._coerce_source("http://10.0.0.2:4747/video") == "http://10.0.0.2:4747/video"
    assert camera._coerce_source("") is None


def test_configured_source_is_first_candidate(monkeypatch):
    monkeypatch.setattr(camera.platform, "system", lambda: "Linux")
    monkeypatch.setattr(camera.glob, "glob", lambda pattern: [])

    result = camera.candidate_cameras(
        preferred=0,
        configured_source="http://phone:4747/video",
        remembered_source="/dev/video7",
    )

    assert result[0][1] == "http://phone:4747/video"
    assert result[1][1] == "/dev/video7"


def test_manual_fallback_runs_after_auto_timeout(monkeypatch):
    monkeypatch.setattr(camera, "load_camera_state", lambda: {})
    monkeypatch.setattr(camera, "candidate_cameras", lambda *a, **k: [])
    monkeypatch.setattr(
        camera,
        "request_manual_camera_source",
        lambda **kwargs: "/dev/video9",
    )

    opened = camera.OpenedCamera(
        cap=DummyCap(),
        index=9,
        source="/dev/video9",
    )
    monkeypatch.setattr(
        camera,
        "_try_open_candidate",
        lambda source, **kwargs: opened if source == "/dev/video9" else None,
    )
    saved = []
    monkeypatch.setattr(
        camera,
        "save_camera_state",
        lambda source, index=None: saved.append((source, index)),
    )

    result = camera.open_camera_resilient(
        auto_timeout=0,
        manual_fallback=True,
    )

    assert result is opened
    assert saved == [("/dev/video9", 9)]


def test_camera_state_persists_last_working_source(tmp_path, monkeypatch):
    monkeypatch.setenv("ASTRA_DATA_DIR", str(tmp_path))

    camera.save_camera_state("http://phone:4747/video", None)
    state = camera.load_camera_state()

    assert state["source"] == "http://phone:4747/video"
    assert "last_success_at" in state


class DummyProcess:
    def __init__(self):
        self.terminated = False
        self.killed = False

    def poll(self):
        return None

    def terminate(self):
        self.terminated = True

    def wait(self, timeout=None):
        return 0

    def kill(self):
        self.killed = True


class DummyLatest:
    def __init__(self):
        self._owner_process = None


def test_droidcam_endpoint_is_canonicalized():
    assert camera._parse_droidcam_endpoint("192.168.1.20:4747") == ("192.168.1.20", 4747)
    assert camera._parse_droidcam_endpoint("http://192.168.1.20:4747/video") == ("192.168.1.20", 4747)
    assert camera._source_key("droidcam://192.168.1.20:4747") == camera._source_key(
        "http://192.168.1.20:4747/video"
    )


def test_successful_droidcam_bridge_keeps_cli_alive(monkeypatch):
    monkeypatch.setattr(camera.platform, "system", lambda: "Linux")
    monkeypatch.setattr(
        camera,
        "_droidcam_virtual_devices",
        lambda: [camera.Path("/dev/video9")],
    )
    process = DummyProcess()
    monkeypatch.setattr(camera, "_start_droidcam_cli", lambda *a, **k: process)

    opened = camera.OpenedCamera(
        cap=DummyLatest(),
        index=9,
        source="/dev/video9",
    )
    monkeypatch.setattr(camera, "_try_open_candidate", lambda *a, **k: opened)

    result = camera._open_droidcam_via_cli(
        "192.168.1.20:4747",
        width=640,
        height=360,
        fps=30,
        timeout_seconds=1.0,
    )

    assert result is opened
    assert result.source == "droidcam://192.168.1.20:4747"
    assert result.cap._owner_process is process
    assert not process.terminated
    assert not process.killed


class RecordingCap:
    def __init__(self):
        self.calls = []

    def set(self, prop, value):
        self.calls.append((prop, value))
        return True


def test_virtual_camera_is_not_reconfigured_by_opencv(monkeypatch):
    cap = RecordingCap()
    monkeypatch.setattr(camera, "_is_virtual_video_source", lambda source: True)

    camera._configure_capture(
        cap,
        source="/dev/video9",
        width=640,
        height=360,
        fps=60,
    )

    # Only queue depth is allowed. Resolution/FPS/FourCC belong to droidcam-cli.
    assert all(prop == camera.cv2.CAP_PROP_BUFFERSIZE for prop, _ in cap.calls)


def test_droidcam_cli_starts_with_safe_size(monkeypatch, tmp_path):
    class Proc:
        def poll(self):
            return None

    commands = []

    monkeypatch.setattr(camera, "_droidcam_cli_binary", lambda: camera.Path("/usr/bin/droidcam-cli"))
    monkeypatch.setattr(camera, "data_dir", lambda: tmp_path)

    def fake_popen(cmd, **kwargs):
        commands.append(cmd)
        return Proc()

    monkeypatch.setattr(camera.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(camera.time, "sleep", lambda *_: None)

    result = camera._start_droidcam_cli(
        "192.168.1.20",
        4747,
        camera.Path("/dev/video9"),
        size="640x480",
    )

    assert result is not None
    assert "-size=640x480" in commands[0]
    assert "-dev=/dev/video9" in commands[0]
