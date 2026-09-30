from __future__ import annotations

import threading
import time
import unittest

from astra_pc.ai.swarm import SubAgentPool, SubAgentTask
from astra_pc.core.daemon import AstraDaemon
from astra_pc.voice.assistant import AstraVoiceAssistant


class FakeClient:
    def __init__(self):
        self.lock = threading.Lock()
        self.running = 0
        self.peak = 0

    def chat(self, prompt, **kwargs):
        if "Divida o objetivo" in prompt:
            return (
                '[{"role":"pesquisa","instruction":"levante fatos","use_vision":false},'
                '{"role":"critico","instruction":"revise riscos","use_vision":false}]'
            )
        with self.lock:
            self.running += 1
            self.peak = max(self.peak, self.running)
        try:
            time.sleep(0.025)
            return "resultado"
        finally:
            with self.lock:
                self.running -= 1


class SwarmTests(unittest.TestCase):
    def test_count_parser_and_router(self):
        self.assertTrue(AstraDaemon._wants_swarm("usa 20 agentes pra revisar isso"))
        self.assertTrue(AstraDaemon._wants_swarm("pensa em paralelo nisso"))
        self.assertFalse(AstraDaemon._wants_swarm("abre o Firefox"))
        self.assertEqual(AstraDaemon._requested_agent_count("usa 20 agentes"), 20)
        self.assertEqual(AstraDaemon._requested_agent_count("usa 999 agentes"), 100)
        self.assertEqual(AstraDaemon._requested_agent_count("usa agentes", 4), 4)

    def test_decomposition(self):
        client = FakeClient()
        pool = SubAgentPool(client, client, planner_client=client, max_agents=100, max_workers=3)
        tasks = pool.plan_tasks("teste", count=8)
        self.assertEqual(len(tasks), 8)
        self.assertEqual([task.role for task in tasks[:2]], ["pesquisa", "critico"])
        self.assertTrue(all(task.model_tier == "fast" for task in tasks[2:]))

    def test_hundred_logical_agents(self):
        client = FakeClient()
        pool = SubAgentPool(client, client, planner_client=client, max_agents=100, max_workers=3)
        tasks = pool.plan_tasks("analise ampla", count=100)
        self.assertEqual(len(tasks), 100)
        self.assertEqual(len({task.task_id for task in tasks}), 100)
        self.assertTrue(all(task.model_tier == "fast" for task in tasks[2:]))

    def test_pool_caps_single_mission(self):
        client = FakeClient()
        pool = SubAgentPool(client, client, max_agents=100, max_workers=3)
        tasks = [SubAgentTask(f"r{i}", f"t{i}") for i in range(12)]
        results = pool.run(tasks)
        self.assertEqual(len(results), 12)
        self.assertTrue(all(result.ok for result in results))
        self.assertLessEqual(client.peak, 3)
        self.assertEqual([r.role for r in results], [f"r{i}" for i in range(12)])

    def test_global_cap_across_two_missions(self):
        client = FakeClient()
        pool = SubAgentPool(client, client, max_agents=100, max_workers=3)
        outputs = []

        def mission(prefix):
            tasks = [SubAgentTask(f"{prefix}{i}", "x") for i in range(9)]
            outputs.append(pool.run(tasks))

        a = threading.Thread(target=mission, args=("a",))
        b = threading.Thread(target=mission, args=("b",))
        a.start(); b.start(); a.join(); b.join()
        self.assertEqual(sum(len(x) for x in outputs), 18)
        self.assertLessEqual(client.peak, 3)
        self.assertEqual(pool.status()["running"], 0)


    def test_runtime_parallel_override(self):
        client = FakeClient()
        pool = SubAgentPool(client, client, planner_client=client, max_agents=100, max_workers=3)
        tasks = [SubAgentTask(f"r{i}", "x") for i in range(8)]
        results = pool.run(tasks, max_parallel=1)
        self.assertEqual(len(results), 8)
        self.assertEqual(client.peak, 1)

    def test_voice_stop_calls_cancel_handler(self):
        called = []
        voice = object.__new__(AstraVoiceAssistant)
        voice._last_preview = ""
        voice._dictation_lock = threading.Lock()
        voice._dictation_target = None
        voice.wake_word = "astra"
        voice._conversation_until = time.monotonic() + 10.0
        voice._dedicated_wake_until = 0.0
        voice.speaker = None
        voice.cancel_handler = lambda: called.append(True)
        voice._requests = __import__("queue").Queue(maxsize=4)
        voice._on_text("para")
        self.assertEqual(called, [True])
        self.assertTrue(voice._requests.empty())


if __name__ == "__main__":
    unittest.main()
