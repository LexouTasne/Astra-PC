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
            "Quantos JSON existem em /tmp/astra-e2e recursivamente?": "*.json",
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


if __name__ == "__main__":
    unittest.main()
