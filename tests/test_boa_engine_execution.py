from __future__ import annotations

from pathlib import Path

import numpy as np

from mkp.engine import build
from mkp.engine.models import ExperimentSpec, SolveResult
from mkp.machine import SimulatorRunRow
from mkp.rng import SharedRepeatSeedListStrategy


ROOT = Path(__file__).resolve().parents[1]


def _row_key(row: SimulatorRunRow) -> tuple[int, int]:
    return row.task.param_set_index, row.task.repeat_index


def _assert_same_deterministic_result(
    sequential: SimulatorRunRow,
    batch: SimulatorRunRow,
) -> None:
    """Exclude wall time while requiring every algorithm-owned value to match."""

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


def test_boa_engine_all_profiles_match_between_sequential_and_batch() -> None:
    seeds = (12345, 23456)
    spec = ExperimentSpec(
        experiment_name="boa-sequential-batch-equivalence",
        problem_type="continuous",
        dataset="book_examples",
        problem_ids=("sphere_2d",),
        solver_ids=("boa",),
        repeat=len(seeds),
        worker_count=2,
        base_seed=0,
    )
    bundle = build(
        spec=spec,
        problem_root=ROOT / "configs" / "problems",
        solver_root=ROOT / "configs" / "solvers",
        seed_strategy=SharedRepeatSeedListStrategy(seeds=seeds),
    )
    try:
        simulator = bundle.new_simulator()
        sequential = simulator.run_sequential(show_progress=False)
        batch = simulator.run_batch(show_progress=False)
    finally:
        bundle.problem_bank.close()

    sequential_rows = {_row_key(row): row for row in sequential.iter_rows()}
    batch_rows = {_row_key(row): row for row in batch.iter_rows()}
    assert sequential_rows.keys() == batch_rows.keys()
    assert len(sequential_rows) == len(batch_rows) == 2 * len(seeds)
    assert {
        row.solve_result.metadata["compatibility_profile"]
        for row in sequential_rows.values()
    } == {
        "book_archive_boa_base_v1",
        "book_archive_boa_spring_v1",
    }
    for key in sequential_rows:
        _assert_same_deterministic_result(sequential_rows[key], batch_rows[key])
