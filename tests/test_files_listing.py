from pathlib import Path

from astra_pc.skills.files import FilesSkill


def test_home_alias_resolves_inside_real_home(tmp_path):
    skill = FilesSkill()
    skill.home = tmp_path.resolve()
    folder = tmp_path / "Downloads"
    folder.mkdir()
    path = skill._safe_path(f"home/{tmp_path.name}/Downloads")
    assert path == folder.resolve()


def test_list_dir_returns_real_entries(tmp_path):
    skill = FilesSkill()
    skill.home = tmp_path.resolve()
    folder = tmp_path / "Downloads"
    folder.mkdir()
    (folder / "foto.png").write_bytes(b"x")
    (folder / "Projetos").mkdir()

    result = skill.execute("list_dir", {"path": "Downloads"})
    assert result.ok
    assert result.data is not None
    names = [item["name"] for item in result.data["entries"]]
    assert names == ["Projetos", "foto.png"]
    assert "Projetos/" in result.message
    assert "foto.png" in result.message
