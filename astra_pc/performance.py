from __future__ import annotations

import statistics
import time

from astra_pc.ai.agent import AstraBrain


def benchmark_brain(brain: AstraBrain, rounds: int = 3) -> dict[str, float]:
    print("Preloading fast text model...")
    t0 = time.perf_counter()
    brain.preload()
    preload_ms = (time.perf_counter() - t0) * 1000.0

    samples = []
    for i in range(rounds):
        started = time.perf_counter()
        brain.ask("Responda apenas com: pronto")
        elapsed = (time.perf_counter() - started) * 1000.0
        samples.append(elapsed)
        print(f"text round {i + 1}: {elapsed:.0f} ms")

    result = {
        "preload_ms": preload_ms,
        "text_median_ms": statistics.median(samples),
        "text_best_ms": min(samples),
        "text_worst_ms": max(samples),
    }
    print(
        "summary: "
        f"preload={result['preload_ms']:.0f}ms "
        f"median={result['text_median_ms']:.0f}ms "
        f"best={result['text_best_ms']:.0f}ms "
        f"worst={result['text_worst_ms']:.0f}ms"
    )
    return result
