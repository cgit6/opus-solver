from __future__ import annotations

from pathlib import Path
import re

from mkp.problem.scvrp import load_legacy_scvrp_problem
from mkp.solver.scvrp_legacy import LegacySCVRPCore


FIXTURES = Path(__file__).parent / "fixtures" / "scvrp"


def _problem():
    return load_legacy_scvrp_problem(
        FIXTURES / "p_n16_k8.vrp",
        FIXTURES / "p_n16_k8_routecap2_transfer1.txt",
        dataset="P",
        problem_id="P-n16-k8-routecap2-transfer1",
        best_known=350,
    )


def test_seed_one_initial_population_matches_archived_generation_one() -> None:
    report = (FIXTURES / "p_n16_k8_seed1_initial_report.txt").read_text(encoding="ascii")
    expected_best = int(re.search(r"Best solution:\s*(\d+)", report).group(1))
    expected_feasible = int(re.search(r"Number of feasible solutions:\s*(\d+)", report).group(1))
    core = LegacySCVRPCore(_problem(), seed=1)

    generation = core.initialize_population()
    trace = core.trace_generation(generation, stage="initial_population")

    assert trace.generation_id == 1
    assert trace.population_size == 48
    assert trace.best_cost == expected_best == 493
    assert trace.feasible_solutions == expected_feasible == 32
    assert trace.best_index == 27
    assert trace.rng_draw_count == 14_456
    assert trace.rng_state == 0x999C_D719
    assert trace.population_sha256 == "02af4625c92df9098a7038983dd8ef4237b09387a99a7f5f48611ded7473e67b"


def test_seed_one_initial_population_trace_is_repeatable() -> None:
    core_a = LegacySCVRPCore(_problem(), seed=1)
    core_b = LegacySCVRPCore(_problem(), seed=1)

    trace_a = core_a.trace_generation(core_a.initialize_population(), stage="initial_population")
    trace_b = core_b.trace_generation(core_b.initialize_population(), stage="initial_population")

    assert trace_a == trace_b
