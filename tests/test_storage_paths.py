from pathlib import Path

from astra_pc.config import load_config


def test_storage_overrides(monkeypatch, tmp_path):
    data = tmp_path / "portable data"
    cache = tmp_path / "portable cache"
    monkeypatch.setenv("ASTRA_DATA_DIR", str(data))
    monkeypatch.setenv("ASTRA_CACHE_DIR", str(cache))

    config = load_config()
    assert Path(config.data["daemon"]["memory_path"]) == data / "astra.db"
    assert Path(config.data["daemon"]["cache_path"]) == cache / "responses.db"
    assert Path(config.data["mesh"]["state_path"]) == data / "mesh"
    assert Path(config.data["skills"]["plugin_dir"]) == data / "skills"
