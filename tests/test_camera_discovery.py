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
