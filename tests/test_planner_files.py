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
