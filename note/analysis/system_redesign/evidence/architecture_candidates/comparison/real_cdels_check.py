"""Selected real CDELS semantic regression, NOT a parallel C++ port."""
from pathlib import Path
import json
import sys
import time

from mkp.problem.scvrp import load_legacy_scvrp_problem
from mkp.solver.CDELS import CDELS
from mkp.tools.scvrp_dataset import _comparison_fields
from mkp.tools.scvrp_native_oracle import (
    SCVRPLegacyKernelRequest, build_scvrp_legacy_kernel, run_scvrp_legacy_kernel,
)

ROOT = Path(__file__).resolve().parent
REPO = Path("/home/sean/optiforge-optimization-solver")
fixtures = REPO / "tests/fixtures/scvrp"
problem = load_legacy_scvrp_problem(fixtures / "p_n16_k8.vrp",
    fixtures / "p_n16_k8_routecap2_transfer1.txt", dataset="P",
    problem_id="P-n16-k8-routecap2-transfer1", best_known=350)
binary = build_scvrp_legacy_kernel(cache_root=ROOT / "real-cpp-build")
rows = []
inputs = [(seed, limit) for limit in (0, 3, 111) for seed in (1, 2)] + [(2, 3), (1, 3)]
for seed, limit in inputs:
    native = run_scvrp_legacy_kernel(problem, SCVRPLegacyKernelRequest(seed=seed,
        termination_mode="fixed_iterations", limit=limit, max_transitions=max(1, limit),
        trace=False, process_trace=True), executable=binary)
    result = CDELS(problem, seed=seed).solve(termination_mode="fixed_iterations",
        limit=limit, max_transitions=max(1, limit), trace=False, process_trace=True)
    comparisons = _comparison_fields(result, native)
    mismatches = [name for name, (a, b) in comparisons.items() if a != b]
    assert not mismatches, (seed, limit, mismatches)
    row = {"seed": seed, "iterations": limit, "passed": True,
           "checks": list(comparisons), "generation_count": result.generation_count,
           "rng_state": result.rng_state, "rng_draw_count": result.rng_draw_count,
           "process_trace_sha256": result.process_trace_sha256}
    rows.append(row)
    print(json.dumps(row), flush=True)
(ROOT / "real_cdels_results.json").write_text(json.dumps({"passed": True,
    "problem_id": problem.problem_id, "cases": rows,
    "cpp_parallel_thread_port_verified": False,
    "limitations": ["One selected small instance, not all 112 configurations",
                    "Original C++ oracle launches a fresh process per request",
                    "Global RNG, NP and generation id still require task-private redesign",
                    "No C++/Numba performance ranking is derived from this check"]}, indent=2) + "\n")
