from __future__ import annotations

from pathlib import Path

import numpy as np

from mkp.engine import build
from mkp.engine.models import ExperimentSpec, SolveResult
from mkp.machine import SimulatorRunRow
from mkp.rng import SharedRepeatSeedListStrategy


ROOT = Path(__file__).resolve().parents[1]


def _assert_same_deterministic_result(
    sequential: SimulatorRunRow,
    batch: SimulatorRunRow,
) -> None:
    assert sequential.task == batch.task
    left: SolveResult = sequential.solve_result
    right: SolveResult = batch.solve_result
    assert left.problem_id == right.problem_id
    assert left.solver_id == right.solver_id
    assert left.run_seed == right.run_seed
    np.testing.assert_array_equal(left.best_solution, right.best_solution)
    assert left.best_objective == right.best_objective
    assert left.feasible == right.feasible
    assert left.evaluation_count == right.evaluation_count
    assert left.stop_reason == right.stop_reason
    assert left.linprog_runtime == right.linprog_runtime
    assert left.error == right.error
    assert left.metadata == right.metadata
    assert sequential.validation_report == batch.validation_report


def test_goa_engine_sequential_and_process_batch_are_identical(tmp_path: Path) -> None:
    # Process scheduling is tested with the already verified short parameters;
    # the full 50 x 500 engineering parity lives in the dedicated long test.
    solver_root = tmp_path / "solvers"
    solver_root.mkdir(parents=True)
    (solver_root / "goa.yaml").write_text(
        """
solver_id: goa
solver_class: GOASolver
capabilities:
  problem_types: [continuous]
  encodings: [real_vector]
  directions: [min]
stop_condition:
  type: max_iterations
  max_iterations: 3
params:
  - compatibility_profile: book_archive_goa_v1
    population_size: 8
    constraint_penalty: 1.0e33
""".strip(),
        encoding="utf-8",
    )
    seeds = (12345, 23456)
    spec = ExperimentSpec(
        experiment_name="goa-sequential-batch-equivalence",
        problem_type="continuous",
        dataset="book_examples",
        problem_ids=("sphere_2d",),
        solver_ids=("goa",),
        repeat=len(seeds),
        worker_count=2,
        base_seed=0,
    )
    bundle = build(
        spec=spec,
        problem_root=ROOT / "configs" / "problems",
        solver_root=solver_root,
        seed_strategy=SharedRepeatSeedListStrategy(seeds=seeds),
    )
    try:
        simulator = bundle.new_simulator()
        sequential = simulator.run_sequential(show_progress=False)
        batch = simulator.run_batch(show_progress=False)
    finally:
        bundle.problem_bank.close()

    sequential_rows = sequential.iter_rows()
    batch_rows = batch.iter_rows()
    assert len(sequential_rows) == len(batch_rows) == len(seeds)
    assert [row.task.task_seed for row in sequential_rows] == list(seeds)
    assert [row.task.task_seed for row in batch_rows] == list(seeds)
    for sequential_row, batch_row in zip(sequential_rows, batch_rows, strict=True):
        _assert_same_deterministic_result(sequential_row, batch_row)
