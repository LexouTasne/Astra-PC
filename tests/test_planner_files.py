from astra_pc.core.planner import AstraPlanner


def test_natural_downloads_question_routes_to_real_list_dir():
    text = "me diga oque contém em home/lex/Downloads"
    assert AstraPlanner.needs_planning(text)
    plan = AstraPlanner._fast_plan(text)
    assert plan == {
        "type": "skill",
        "skill": "files",
        "action": "list_dir",
        "args": {"path": "home/lex/Downloads"},
    }


def test_bare_path_is_treated_as_directory_request():
    plan = AstraPlanner._fast_plan("home/lex/Downloads")
    assert plan["skill"] == "files"
    assert plan["action"] == "list_dir"
    assert plan["args"]["path"] == "home/lex/Downloads"


def test_quoted_file_path_can_route_to_read_file():
    plan = AstraPlanner._fast_plan('leia o arquivo "~/Documents/nota.txt"')
    assert plan == {
        "type": "skill",
        "skill": "files",
        "action": "read_file",
        "args": {"path": "~/Documents/nota.txt"},
    }


def _listing():
    return {
        "path": "/var/home/lex/Downloads",
        "entries": [
            {
                "name": "bestclient-2.3-linux_x86_64",
                "path": "/var/home/lex/Downloads/bestclient-2.3-linux_x86_64",
                "type": "folder",
            },
            {
                "name": "video.mp4",
                "path": "/var/home/lex/Downloads/video.mp4",
                "type": "file",
            },
        ],
    }


def test_first_item_followup_resolves_to_real_folder():
    plan = AstraPlanner.file_followup_plan(
        "oque tem dentro desse primeiro item da lista? uma pasta",
        _listing(),
    )
    assert plan["skill"] == "files"
    assert plan["action"] == "list_dir"
    assert plan["args"]["path"].endswith("bestclient-2.3-linux_x86_64")
    assert plan["resolved_from_context"] is True


def test_named_folder_followup_uses_last_real_listing():
    plan = AstraPlanner.file_followup_plan(
        "porra, dentro do bestclient",
        _listing(),
    )
    assert plan["action"] == "list_dir"
    assert plan["args"]["path"].endswith("bestclient-2.3-linux_x86_64")


def test_small_typo_in_folder_name_still_resolves():
    plan = AstraPlanner.file_followup_plan(
        "PORRA, DENTRO DE BESTCLIOENT-2.3-LINUX",
        _listing(),
    )
    assert plan["action"] == "list_dir"
    assert "bestclient-2.3-linux_x86_64" in plan["args"]["path"]


def test_followup_without_literal_path_still_needs_planning():
    assert AstraPlanner.needs_planning("me lista oque tem dentro")
    assert AstraPlanner.needs_planning("dentro do bestclient")
