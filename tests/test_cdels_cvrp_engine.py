from __future__ import annotations

from pathlib import Path

import numpy as np

from mkp.engine import Engine, SolverConfigsSnapshot
from mkp.engine.models import ExperimentSpec
from mkp.problem.cvrp import decode_cvrp_solution
from mkp.rng import SharedRepeatSeedListStrategy
from mkp.tools.solver_config_loader import SolverConfigLoader


ROOT = Path(__file__).resolve().parents[1]


def _short_config() -> SolverConfigsSnapshot:
    config = SolverConfigLoader(ROOT / "configs/solvers").load(
        "cdels_cvrp",
        param_set_index=0,
    )
    config["stop_condition"]["max_iterations"] = 3
    return SolverConfigsSnapshot.from_configs([config])


def test_cdels_cvrp_runs_through_engine_and_validation() -> None:
    spec = ExperimentSpec(
        experiment_name="cdels-cvrp-short",
        problem_type="cvrp",
        dataset="P",
        problem_ids=("P-n16-k8",),
        solver_ids=("cdels_cvrp",),
        repeat=1,
        worker_count=1,
        base_seed=0,
    )
    bundle = Engine.build(
        spec=spec,
        problem_root=ROOT / "configs/problems",
        solver_root=ROOT / "configs/solvers",
        seed_strategy=SharedRepeatSeedListStrategy(seeds=(1,)),
        solver_configs=_short_config(),
    )
    simulator = bundle.new_simulator()
    try:
        result = simulator.run_sequential(show_progress=False)
        (row,) = result.iter_rows()
        solve_result = row.solve_result
        report = row.validation_report

        problem = bundle.problem_bank.get("P", "P-n16-k8", "cvrp")
        routes = decode_cvrp_solution(
            solve_result.best_solution,
            vehicle_count=problem.vehicle_count,
            n_customers=problem.n_customers,
        )
        assert problem.evaluate(routes).objective == 450
        assert solve_result.best_objective == 450
        assert solve_result.run_seed == 1
        assert solve_result.metadata["transition_count"] == 3
        assert report.is_feasible is True
        assert report.objective_valid is True
        assert report.best_known_reached is True
        assert report.best_known_gap == 0
    finally:
        simulator.close()


def test_cdels_cvrp_batch_matches_sequential_for_fixed_seeds() -> None:
    seeds = (1, 2)

    def run(worker_count: int):
        spec = ExperimentSpec(
            experiment_name=f"cdels-cvrp-workers-{worker_count}",
            problem_type="cvrp",
            dataset="P",
            problem_ids=("P-n16-k8",),
            solver_ids=("cdels_cvrp",),
            repeat=len(seeds),
            worker_count=worker_count,
            base_seed=0,
        )
        bundle = Engine.build(
            spec=spec,
            problem_root=ROOT / "configs/problems",
            solver_root=ROOT / "configs/solvers",
            seed_strategy=SharedRepeatSeedListStrategy(seeds=seeds),
            solver_configs=_short_config(),
        )
        simulator = bundle.new_simulator()
        try:
            result = (
                simulator.run_sequential(show_progress=False)
                if worker_count == 1
                else simulator.run_batch(show_progress=False)
            )
            return {
                row.task.task_seed: row
                for row in result.iter_rows()
            }
        finally:
            simulator.close()

    sequential = run(1)
    batch = run(2)
    assert sequential.keys() == batch.keys() == set(seeds)
    for seed in seeds:
        left = sequential[seed]
        right = batch[seed]
        assert left.task == right.task
        np.testing.assert_array_equal(
            left.solve_result.best_solution,
            right.solve_result.best_solution,
        )
        assert left.solve_result.best_objective == right.solve_result.best_objective
        assert left.solve_result.feasible is right.solve_result.feasible
        assert left.solve_result.metadata == right.solve_result.metadata
        assert left.validation_report == right.validation_report
