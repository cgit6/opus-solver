from __future__ import annotations

import json
from pathlib import Path

import pytest

from mkp.engine import Engine
from mkp.engine.models import ExperimentSpec
from mkp.problem.scvrp import decode_scvrp_solution
from mkp.rng import SharedRepeatSeedListStrategy


REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).parent / "fixtures" / "scvrp"
PROBLEM_ID = "P-n16-k8-routecap2-transfer1"
SOLVER_ID = "scvrp_legacy_sa"
LEGACY_SEEDS = tuple(range(1, 11))


@pytest.mark.slow
def test_scvrp_legacy_seeds_one_to_ten_run_through_sequential_engine() -> None:
    golden = json.loads(
        (FIXTURES / "p_n16_k8_seeds_1_10_golden.json").read_text(encoding="ascii")
    )
    common = golden["common_result"]
    golden_by_seed = {int(seed_result["seed"]): seed_result for seed_result in golden["seeds"]}
    assert set(golden_by_seed) == set(LEGACY_SEEDS)

    spec = ExperimentSpec(
        experiment_name="scvrp_legacy_seeds_one_to_ten_engine_integration",
        problem_type="scvrp",
        dataset="P",
        problem_ids=(PROBLEM_ID,),
        solver_ids=(SOLVER_ID,),
        repeat=len(LEGACY_SEEDS),
        worker_count=1,
        base_seed=0,
    )
    bundle = Engine.build(
        spec=spec,
        problem_root=REPO_ROOT / "configs/problems",
        solver_root=REPO_ROOT / "configs/solvers",
        seed_strategy=SharedRepeatSeedListStrategy(seeds=LEGACY_SEEDS),
        solver_param_set_indices={SOLVER_ID: (0,)},
    )
    try:
        simulator = bundle.new_simulator()
        result = simulator.run_sequential(show_progress=False)
        rows = result.iter_rows()
        rows_by_seed = {row.task.task_seed: row for row in rows}
        assert len(rows) == len(rows_by_seed) == len(LEGACY_SEEDS)
        assert set(rows_by_seed) == set(LEGACY_SEEDS)

        generation_count = int(common["generation_count"])
        transition_count = generation_count - 1
        population_size = 3 * 16
        evaluation_count = population_size * generation_count
        expected_transfers = tuple(int(customer) for customer in common["transferred_customers"])

        for repeat_index, seed in enumerate(LEGACY_SEEDS):
            row = rows_by_seed[seed]
            seed_golden = golden_by_seed[seed]
            expected_routes = tuple(
                tuple(int(customer) for customer in route) for route in seed_golden["routes"]
            )

            assert row.task.repeat_index == repeat_index
            assert row.task.task_seed == seed
            assert row.solve_result.run_seed == seed
            assert row.solve_result.best_objective == common["objective"]
            assert row.solve_result.feasible is common["feasible"]
            assert row.solve_result.evaluation_count == evaluation_count == 538_608
            assert row.solve_result.stop_reason == "max_iterations_reached"

            routes, transferred_customers = decode_scvrp_solution(
                row.solve_result.best_solution,
                vehicle_count=8,
                n_customers=16,
            )
            assert routes == expected_routes
            assert transferred_customers == expected_transfers

            metadata = row.solve_result.metadata
            assert metadata["population_size"] == population_size
            assert metadata["generation_count"] == generation_count == 11_221
            assert metadata["transition_count"] == transition_count == 11_220
            assert metadata["transfer_vehicle_count"] == common["transfer_vehicle_count"]
            if seed == 1:
                # Seed 1 is the only full-run RNG fingerprint independently
                # verified against the archived generation trace.
                assert metadata["rng_state"] == 0xB921_E7B6
                assert metadata["rng_draw_count"] == 9_603_103

            validation = row.validation_report
            assert validation.is_feasible is common["feasible"]
            assert validation.objective_valid is True
            assert validation.recomputed_objective == common["objective"]
            assert validation.best_known_reached is True
            assert validation.best_known_gap == 0
            state = validation.metadata["scvrp_state"]
            assert state["routes"] == [list(route) for route in expected_routes]
            assert state["transferred_customers"] == list(expected_transfers)
            assert state["route_cost"] == common["route_cost"]
            assert state["transfer_cost"] == common["transfer_cost"]
            assert state["transferred_demand"] == common["transferred_demand"]
            assert state["transfer_vehicle_count"] == common["transfer_vehicle_count"]
            assert state["strict_feasible"] is True
            assert state["violations"] == []
    finally:
        bundle.problem_bank.close()
