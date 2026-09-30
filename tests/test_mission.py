from __future__ import annotations

import threading
import unittest

from astra_pc.ai.mission import MissionAgent
from astra_pc.core.daemon import AstraDaemon


class SequenceClient:
    def __init__(self, outputs):
        self.outputs = iter(outputs)
        self.calls = 0

    def chat(self, *args, **kwargs):
        self.calls += 1
        return next(self.outputs)


def skills():
    return [
        {"name": "files", "description": "files"},
        {"name": "apps", "description": "apps"},
    ]


class MissionTests(unittest.TestCase):
    def test_mission_intent_is_explicit(self):
        self.assertTrue(AstraDaemon._wants_mission("Astra, faz isso inteiro pra mim"))
        self.assertTrue(AstraDaemon._wants_mission("modo missão: cuida disso pra mim"))
        self.assertFalse(AstraDaemon._wants_mission("abre o Firefox"))

    def test_skill_swarm_visual_then_answer(self):
        client = SequenceClient([
            '{"type":"skill","skill":"files","action":"list_dir","args":{"path":"/tmp"},"reason":"inspect"}',
            '{"type":"swarm","goal":"revise o estado","count":3,"vision":false,"reason":"review"}',
            '{"type":"visual","goal":"confira a janela","reason":"verify"}',
            '{"type":"answer","message":"feito","reason":"complete"}',
        ])
        calls = []
        agent = MissionAgent(
            client,
            skill_provider=skills,
            context_provider=lambda: "ctx",
            execute_skill=lambda step: calls.append(("skill", step)) or {"ok": True, "message": "listed"},
            execute_swarm=lambda goal, count, vision: calls.append(("swarm", goal, count, vision)) or {"ok": True, "message": "reviewed"},
            execute_visual=lambda goal: calls.append(("visual", goal)) or {"ok": True, "message": "verified"},
            max_steps=8,
        )
        result = agent.run("complete task")
        self.assertTrue(result.ok)
        self.assertEqual(result.message, "feito")
        self.assertEqual([item[0] for item in calls], ["skill", "swarm", "visual"])
        self.assertEqual(len(result.steps), 3)

    def test_invalid_json_is_repaired(self):
        client = SequenceClient([
            "not-json",
            '{"type":"answer","message":"corrigido","reason":"done"}',
        ])
        agent = MissionAgent(
            client,
            skill_provider=skills,
            context_provider=lambda: "ctx",
            execute_skill=lambda step: {"ok": True},
            execute_swarm=lambda goal, count, vision: {"ok": True},
            execute_visual=lambda goal: {"ok": True},
        )
        result = agent.run("x")
        self.assertTrue(result.ok)
        self.assertEqual(result.message, "corrigido")
        self.assertEqual(client.calls, 2)

    def test_unknown_skill_is_repaired_before_execution(self):
        client = SequenceClient([
            '{"type":"skill","skill":"inventada","action":"x","args":{}}',
            '{"type":"answer","message":"sem inventar","reason":"done"}',
        ])
        executed = []
        agent = MissionAgent(
            client,
            skill_provider=skills,
            context_provider=lambda: "ctx",
            execute_skill=lambda step: executed.append(step) or {"ok": True},
            execute_swarm=lambda goal, count, vision: {"ok": True},
            execute_visual=lambda goal: {"ok": True},
        )
        result = agent.run("x")
        self.assertTrue(result.ok)
        self.assertEqual(executed, [])

    def test_confirmation_required_stops_mission(self):
        client = SequenceClient([
            '{"type":"skill","skill":"files","action":"delete","args":{"path":"x"},"reason":"x"}',
        ])
        agent = MissionAgent(
            client,
            skill_provider=skills,
            context_provider=lambda: "ctx",
            execute_skill=lambda step: {"ok": False, "message": "confirmation required"},
            execute_swarm=lambda goal, count, vision: {"ok": True},
            execute_visual=lambda goal: {"ok": True},
        )
        result = agent.run("x")
        self.assertFalse(result.ok)
        self.assertIn("confirma", result.message.lower())
        self.assertEqual(len(result.steps), 1)

    def test_cancel_before_first_step(self):
        cancel = threading.Event()
        cancel.set()
        client = SequenceClient([])
        agent = MissionAgent(
            client,
            skill_provider=skills,
            context_provider=lambda: "ctx",
            execute_skill=lambda step: {"ok": True},
            execute_swarm=lambda goal, count, vision: {"ok": True},
            execute_visual=lambda goal: {"ok": True},
            cancel_event=cancel,
        )
        result = agent.run("x")
        self.assertFalse(result.ok)
        self.assertEqual(result.message, "Stopped by user.")

    def test_direct_file_steps_accept_new_named_folder_and_file(self):
        agent = object.__new__(MissionAgent)
        steps = agent._direct_file_steps(
            "Na pasta /tmp/astra-e2e crie uma pasta nova chamada created. "
            "Dentro dela crie um arquivo novo chamado status.txt contendo exatamente ASTRA OK."
        )
        self.assertEqual(steps[0]["args"]["path"], "/tmp/astra-e2e/created")
        self.assertEqual(steps[1]["args"]["path"], "/tmp/astra-e2e/created/status.txt")
        self.assertEqual(steps[1]["args"]["content"], "ASTRA OK")

    def test_direct_file_steps_cover_read_list_and_natural_search(self):
        agent = object.__new__(MissionAgent)
        read_steps = agent._direct_file_steps(
            "Leia o arquivo /tmp/astra-e2e/status.txt e diga exatamente o conteúdo."
        )
        self.assertEqual(read_steps[0]["action"], "read_file")
        self.assertEqual(read_steps[0]["args"]["path"], "/tmp/astra-e2e/status.txt")

        list_steps = agent._direct_file_steps(
            "Liste os arquivos e pastas em /tmp/astra-e2e e diga o que encontrou."
        )
        self.assertEqual(list_steps[0]["action"], "list_dir")
        self.assertEqual(list_steps[0]["args"]["path"], "/tmp/astra-e2e")

        search_steps = agent._direct_file_steps(
            "Procure dentro de /tmp/astra-e2e por um arquivo cujo nome contenha data."
        )
        self.assertEqual(search_steps[0]["action"], "search_files")
        self.assertEqual(search_steps[0]["args"]["pattern"], "*data*")

    def test_direct_file_steps_understand_natural_extension_counts(self):
        agent = object.__new__(MissionAgent)
        cases = {
            "Quantos arquivos Python existem recursivamente em /tmp/astra-e2e?": "*.py",
            "Conte os scripts Python em /tmp/astra-e2e e subpastas.": "*.py",
            "Quantos arquivos JavaScript existem em /tmp/astra-e2e?": "*.js",
            "Quantos JS existem em /tmp/astra-e2e?": "*.js",
            "Quantos arquivos TypeScript existem em /tmp/astra-e2e?": "*.ts",
            "Quantos arquivos Java existem em /tmp/astra-e2e?": "*.java",
            "Quantos CPP existem em /tmp/astra-e2e?": "*.cpp",
            "Quantos C++ existem em /tmp/astra-e2e?": "*.cpp",
            "Quantos CXX existem em /tmp/astra-e2e?": "*.cxx",
            "Quantos CC existem em /tmp/astra-e2e?": "*.cc",
            "Quantos arquivos .h existem em /tmp/astra-e2e?": "*.h",
            "Quantos HPP existem em /tmp/astra-e2e?": "*.hpp",
            "Quantos arquivos C existem em /tmp/astra-e2e?": "*.c",
            "Quantos C# existem em /tmp/astra-e2e?": "*.cs",
            "Quantos Rust existem em /tmp/astra-e2e?": "*.rs",
            "Quantos arquivos Go existem em /tmp/astra-e2e?": "*.go",
            "Quantos JSON existem em /tmp/astra-e2e recursivamente?": "*.json",
            "Quantos YAML existem em /tmp/astra-e2e?": "*.yaml",
            "Quantos YML existem em /tmp/astra-e2e?": "*.yml",
            "Quantos arquivos Markdown existem em /tmp/astra-e2e?": "*.md",
            "Quantos arquivos de texto existem em /tmp/astra-e2e?": "*.txt",
        }
        for goal, expected in cases.items():
            with self.subTest(goal=goal):
                steps = agent._direct_file_steps(goal)
                self.assertEqual(steps[0]["action"], "count_items")
                self.assertEqual(steps[0]["args"]["pattern"], expected)

    def test_direct_file_steps_understand_everyday_file_phrases(self):
        agent = object.__new__(MissionAgent)

        steps = agent._direct_file_steps("Me diga o que tem em /tmp/astra-e2e/docs.")
        self.assertEqual(steps[0]["action"], "list_dir")

        steps = agent._direct_file_steps("O que contém dentro de /tmp/astra-e2e/code/src?")
        self.assertEqual(steps[0]["args"]["path"], "/tmp/astra-e2e/code/src")

        steps = agent._direct_file_steps("Quantas coisas existem em /tmp/astra-e2e recursivamente?")
        self.assertEqual(steps[0]["action"], "count_items")
        self.assertTrue(steps[0]["args"]["recursive"])

        steps = agent._direct_file_steps("Encontre report-alpha dentro de /tmp/astra-e2e.")
        self.assertEqual(steps[0]["args"]["pattern"], "*report-alpha*")

        steps = agent._direct_file_steps(
            "Procure arquivos com report no nome dentro de /tmp/astra-e2e."
        )
        self.assertEqual(steps[0]["args"]["pattern"], "*report*")

        steps = agent._direct_file_steps("Me mostra o conteúdo de /tmp/astra-e2e/docs.")
        self.assertEqual(steps[0]["action"], "list_dir")

        steps = agent._direct_file_steps("Quais arquivos tem em /tmp/astra-e2e/docs?")
        self.assertEqual(steps[0]["action"], "list_dir")

        for verb in ("Ache", "Acha", "Busca", "Procura"):
            with self.subTest(verb=verb):
                steps = agent._direct_file_steps(f"{verb} target.txt em /tmp/astra-e2e.")
                self.assertEqual(steps[0]["action"], "search_files")
                self.assertEqual(steps[0]["args"]["pattern"], "target.txt")

    def test_multi_file_creation_and_delete_use_model_planner(self):
        agent = object.__new__(MissionAgent)
        self.assertEqual(
            agent._direct_file_steps(
                "Em /tmp/astra-e2e crie um arquivo a.py e crie um arquivo b.js."
            ),
            [],
        )
        delete_steps = agent._direct_file_steps("Apague /tmp/astra-e2e/a.py.")
        self.assertEqual(delete_steps[0]["action"], "delete_file")
        self.assertEqual(delete_steps[0]["args"]["path"], "/tmp/astra-e2e/a.py")

    def test_explicit_multifile_code_generation_uses_direct_tools(self):
        agent = object.__new__(MissionAgent)
        steps = agent._direct_file_steps(
            "Em /tmp/astra-e2e monte a.py que imprima A OK; b.js que imprima B OK."
        )
        self.assertEqual([step["args"]["path"] for step in steps], [
            "/tmp/astra-e2e/a.py", "/tmp/astra-e2e/b.js"
        ])
        self.assertIn('print("A OK")', steps[0]["args"]["content"])
        self.assertIn('console.log("B OK")', steps[1]["args"]["content"])

    def test_file_action_used_as_skill_name_is_normalized(self):
        step = MissionAgent._normalize_step({
            "type": "skill",
            "skill": "create_dir",
            "action": "create_dir",
            "args": {"path": "/tmp/x"},
        })
        self.assertEqual(step["skill"], "files")
        self.assertEqual(step["action"], "create_dir")

    def test_delete_file_step_keeps_only_path_argument(self):
        step = MissionAgent._normalize_step({
            "type": "skill",
            "skill": "files",
            "action": "delete_file",
            "args": {"path": "/tmp/a.py", "reason": "extra"},
        })
        self.assertEqual(step["args"], {"path": "/tmp/a.py"})

    def test_file_step_repair_fixes_subfolder_multifile_and_delete(self):
        agent = object.__new__(MissionAgent)
        sub_goal = "Prepare uma subpasta chamada codigo dentro de /tmp/astra-e2e."
        repaired = agent._repair_file_step_from_goal(
            sub_goal,
            {"type": "skill", "skill": "files", "action": "create_dir", "args": {"path": "/tmp/astra-e2e"}},
            [],
        )
        self.assertEqual(repaired["args"]["path"], "/tmp/astra-e2e/codigo")

        multi_goal = (
            "Em /tmp/astra-e2e/codigo monte main.py com Python que imprima ASTRA PY OK; "
            "app.js com JavaScript que imprima ASTRA JS OK."
        )
        first = agent._repair_file_step_from_goal(
            multi_goal,
            {"type": "skill", "skill": "files", "action": "create_text_file", "args": {"path": "/tmp/astra-e2e/codigo", "content": "wrong"}},
            [],
        )
        self.assertEqual(first["args"]["path"], "/tmp/astra-e2e/codigo/main.py")
        self.assertIn("ASTRA PY OK", first["args"]["content"])

        history = [{
            "request": first,
            "result": {"ok": True, "message": "created"},
        }]
        second = agent._repair_file_step_from_goal(
            multi_goal,
            {"type": "skill", "skill": "files", "action": "create_text_file", "args": {"path": "/tmp/astra-e2e/codigo", "content": "wrong"}},
            history,
        )
        self.assertEqual(second["args"]["path"], "/tmp/astra-e2e/codigo/app.js")
        self.assertIn("console.log", second["args"]["content"])
        self.assertIn("ASTRA JS OK", second["args"]["content"])

        delete = agent._repair_file_step_from_goal(
            "Apague /tmp/astra-e2e/codigo/main.py.",
            {"type": "skill", "skill": "files", "action": "write_file", "args": {"path": "/tmp/astra-e2e/codigo/main.py", "content": "fake delete"}},
            [],
        )
        self.assertEqual(delete["action"], "delete_file")
        self.assertEqual(delete["args"], {"path": "/tmp/astra-e2e/codigo/main.py"})

    def test_list_and_count_followup_gets_both_fast_steps(self):
        agent = object.__new__(MissionAgent)
        steps = agent._direct_file_steps(
            "Confira /tmp/astra-e2e e diga quais arquivos sobraram e quantos são."
        )
        self.assertEqual([step["action"] for step in steps], ["list_dir", "count_items"])

    def test_simple_creation_result_finishes_but_multifile_does_not(self):
        create_dir = {"skill": "files", "action": "create_dir"}
        self.assertTrue(MissionAgent._tool_result_completes_goal(
            "Crie a pasta /tmp/astra-e2e.", create_dir
        ))
        self.assertFalse(MissionAgent._tool_result_completes_goal(
            "Em /tmp/astra-e2e monte a.py e b.js.", create_dir
        ))

        create_file = {"skill": "files", "action": "create_text_file"}
        self.assertTrue(MissionAgent._tool_result_completes_goal(
            "Crie /tmp/astra-e2e/a.py.", create_file
        ))
        self.assertFalse(MissionAgent._tool_result_completes_goal(
            "Em /tmp/astra-e2e monte a.py e b.js.", create_file
        ))


if __name__ == "__main__":
    unittest.main()
