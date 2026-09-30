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


if __name__ == "__main__":
    unittest.main()
