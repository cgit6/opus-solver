from __future__ import annotations

import json
from multiprocessing.shared_memory import SharedMemory
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from mkp.engine import Engine, SimulationBundle, SolverConfigsSnapshot
from mkp.engine.models import ExperimentSpec
from mkp.problem.scvrp import decode_scvrp_solution, encode_scvrp_solution
from mkp.rng import SharedRepeatSeedListStrategy
from mkp.simulator import SimulatorResult
from mkp.solver.scvrp_legacy_kernel import (
    SCVRPLegacyKernelError,
    build_scvrp_legacy_kernel,
)
from mkp.tools.show import write_simulator_result
from mkp.tools.solver_config_loader import SolverConfigLoader


REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).parent / "fixtures" / "scvrp"
PROBLEM_ID = "P-n16-k8-routecap2-transfer1"
SOLVER_ID = "scvrp_legacy_sa"
LEGACY_SEEDS = tuple(range(1, 11))
DEMANDS = (0, 19, 30, 16, 23, 11, 31, 15, 28, 8, 8, 7, 14, 6, 19, 11)
EXPECTED_METADATA_KEYS = {
    "compatibility_profile",
    "de_technique",
    "native_protocol",
    "termination_mode",
    "stop_cause",
    "population_size",
    "generation_count",
    "transition_count",
    "feasible_solution_count",
    "temperature_stagnation",
    "final_temperature_hex",
    "rng_algorithm",
    "rng_state",
    "rng_draw_count",
    "transfer_vehicle_count",
}


def _build_bundle(*, experiment_name: str, worker_count: int) -> SimulationBundle:
    spec = ExperimentSpec(
        experiment_name=experiment_name,
        problem_type="scvrp",
        dataset="P",
        problem_ids=(PROBLEM_ID,),
        solver_ids=(SOLVER_ID,),
        repeat=len(LEGACY_SEEDS),
        worker_count=worker_count,
        base_seed=0,
    )
    return Engine.build(
        spec=spec,
        problem_root=REPO_ROOT / "configs/problems",
        solver_root=REPO_ROOT / "configs/solvers",
        seed_strategy=SharedRepeatSeedListStrategy(seeds=LEGACY_SEEDS),
        solver_param_set_indices={SOLVER_ID: (0,)},
    )


def _build_bundle_with_snapshot(
    *,
    experiment_name: str,
    seeds: tuple[int, ...],
    worker_count: int,
    solver_configs: SolverConfigsSnapshot,
) -> SimulationBundle:
    spec = ExperimentSpec(
        experiment_name=experiment_name,
        problem_type="scvrp",
        dataset="P",
        problem_ids=(PROBLEM_ID,),
        solver_ids=(SOLVER_ID,),
        repeat=len(seeds),
        worker_count=worker_count,
        base_seed=0,
    )
    return Engine.build(
        spec=spec,
        problem_root=REPO_ROOT / "configs/problems",
        solver_root=REPO_ROOT / "configs/solvers",
        seed_strategy=SharedRepeatSeedListStrategy(seeds=seeds),
        solver_configs=solver_configs,
    )


def _production_solver_snapshot(
    *,
    max_iterations: int | None = None,
    timeout_seconds: float | None = None,
) -> SolverConfigsSnapshot:
    config = SolverConfigLoader(REPO_ROOT / "configs/solvers").load(
        SOLVER_ID,
        param_set_index=0,
    )
    assert config["stop_condition"]["max_iterations"] == 11_220
    assert config["params"]["timeout_seconds"] == 120.0
    if max_iterations is not None:
        config["stop_condition"]["max_iterations"] = max_iterations
    if timeout_seconds is not None:
        config["params"]["timeout_seconds"] = timeout_seconds
    return SolverConfigsSnapshot.from_configs([config])


def _problem_bank_shm_names(bundle: SimulationBundle) -> tuple[str, str, str]:
    (pack,) = bundle.problem_bank.export_worker_packs()
    return (
        pack.shm_name_coords,
        pack.shm_name_demands,
        pack.shm_name_distance_matrix,
    )


def _assert_shared_memory_unlinked(shm_names: tuple[str, ...]) -> None:
    for shm_name in shm_names:
        try:
            leaked = SharedMemory(name=shm_name)
        except FileNotFoundError:
            continue
        leaked.close()
        pytest.fail(f"ProblemBank shared memory was not unlinked: {shm_name}")


def _assert_all_seed_golden_results(result: SimulatorResult) -> None:
    golden = json.loads(
        (FIXTURES / "p_n16_k8_seeds_1_10_golden.json").read_text(encoding="ascii")
    )
    common = golden["common_result"]
    golden_by_seed: dict[int, dict[str, Any]] = {
        int(seed_result["seed"]): seed_result for seed_result in golden["seeds"]
    }
    assert set(golden_by_seed) == set(LEGACY_SEEDS)

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
        assert row.task.problem_id == PROBLEM_ID
        assert row.task.solver_id == SOLVER_ID
        assert row.task.param_set_index == 0
        assert row.task.task_seed == seed
        assert row.solve_result.problem_id == PROBLEM_ID
        assert row.solve_result.solver_id == SOLVER_ID
        assert row.solve_result.run_seed == seed
        assert row.solve_result.best_objective == common["objective"]
        assert row.solve_result.feasible is common["feasible"]
        assert row.solve_result.evaluation_count == evaluation_count == 538_608
        assert row.solve_result.stop_reason == "max_iterations_reached"
        assert row.solve_result.linprog_runtime == 0.0
        assert row.solve_result.error is None

        routes, transferred_customers = decode_scvrp_solution(
            row.solve_result.best_solution,
            vehicle_count=8,
            n_customers=16,
        )
        assert routes == expected_routes
        assert transferred_customers == expected_transfers
        expected_solution = encode_scvrp_solution(
            expected_routes,
            expected_transfers,
            n_customers=16,
        )
        assert row.solve_result.best_solution.dtype == np.int64
        assert np.array_equal(row.solve_result.best_solution, expected_solution)
        assert row.solve_result.best_solution.flags.writeable is False

        metadata = row.solve_result.metadata
        assert set(metadata) == EXPECTED_METADATA_KEYS
        assert metadata["compatibility_profile"] == "vs2019_v142_archive"
        assert metadata["de_technique"] == "rand_1_exp"
        assert metadata["native_protocol"] == "SCVRP_LEGACY_RESULT_V1"
        assert metadata["termination_mode"] == "fixed_iterations"
        assert metadata["stop_cause"] == "fixed_iterations"
        assert metadata["population_size"] == population_size
        assert metadata["generation_count"] == generation_count == 11_221
        assert metadata["transition_count"] == transition_count == 11_220
        assert metadata["feasible_solution_count"] == population_size
        assert metadata["temperature_stagnation"] == 101
        assert metadata["final_temperature_hex"] == "0x1.5e2d52a31c76bp-8"
        assert metadata["rng_algorithm"] == "msvc_rand"
        assert 0 <= metadata["rng_state"] <= 0xFFFF_FFFF
        assert metadata["rng_draw_count"] > 0
        assert metadata["transfer_vehicle_count"] == common["transfer_vehicle_count"]
        if seed == 1:
            # Derived compatibility fingerprint. The independent archive
            # oracle is the complete route/transfer and generation trace.
            assert metadata["rng_state"] == 0xB921_E7B6
            assert metadata["rng_draw_count"] == 9_603_103

        validation = row.validation_report
        assert validation.is_feasible is common["feasible"]
        assert validation.feasibility_violations == ()
        assert validation.objective_valid is True
        assert validation.recomputed_objective == common["objective"]
        assert validation.objective_mismatch is False
        assert validation.best_known_reached is True
        assert validation.best_known_gap == 0
        assert validation.problem_type == "scvrp"
        assert validation.encoding == "scvrp_route_transfer"
        assert validation.direction == "min"
        assert validation.best_known == common["objective"]
        state = validation.metadata["scvrp_state"]
        assert set(state) == {
            "routes",
            "transferred_customers",
            "route_cost",
            "transfer_cost",
            "transferred_demand",
            "transfer_vehicle_count",
            "route_capacities_free",
            "transfer_capacities_free",
            "strict_feasible",
            "violations",
        }
        assert state["routes"] == [list(route) for route in expected_routes]
        assert state["transferred_customers"] == list(expected_transfers)
        assert state["route_cost"] == common["route_cost"]
        assert state["transfer_cost"] == common["transfer_cost"]
        assert state["transferred_demand"] == common["transferred_demand"]
        assert state["transfer_vehicle_count"] == common["transfer_vehicle_count"]
        assert state["route_capacities_free"] == [
            35
            - sum(
                DEMANDS[customer]
                for customer in route
                if customer not in expected_transfers
            )
            for route in expected_routes
        ]
        assert state["transfer_capacities_free"] == [0, 0, 0, 0, 0, 31, 0, 0, 0]
        assert state["strict_feasible"] is True
        assert state["violations"] == []


@pytest.mark.slow
def test_scvrp_legacy_seeds_one_to_ten_run_through_sequential_engine() -> None:
    bundle = _build_bundle(
        experiment_name="scvrp_legacy_seeds_one_to_ten_engine_integration",
        worker_count=1,
    )
    try:
        simulator = bundle.new_simulator()
        result = simulator.run_sequential(show_progress=False)
    finally:
        bundle.problem_bank.close()
    _assert_all_seed_golden_results(result)


@pytest.mark.slow
def test_scvrp_legacy_seeds_one_to_ten_run_through_batch_engine() -> None:
    bundle = _build_bundle(
        experiment_name="scvrp_legacy_seeds_one_to_ten_batch_engine_integration",
        worker_count=2,
    )
    shm_names = _problem_bank_shm_names(bundle)
    try:
        simulator = bundle.new_simulator()
        result = simulator.run_batch(show_progress=False)
    finally:
        bundle.problem_bank.close()
    _assert_shared_memory_unlinked(shm_names)
    _assert_all_seed_golden_results(result)


@pytest.mark.slow
def test_scvrp_seed_one_writer_preserves_complete_archive_solution_state(
    tmp_path: Path,
) -> None:
    experiment_name = "scvrp_legacy_seed_one_writer_integration"
    bundle = _build_bundle_with_snapshot(
        experiment_name=experiment_name,
        seeds=(1,),
        worker_count=1,
        solver_configs=_production_solver_snapshot(),
    )
    try:
        simulator = bundle.new_simulator()
        result = simulator.run_sequential(show_progress=False)
        written_dirs = write_simulator_result(
            result,
            experiment_name=experiment_name,
            output_root=tmp_path,
        )
    finally:
        bundle.problem_bank.close()

    expected_output_dir = tmp_path / experiment_name / SOLVER_ID / "param_0"
    assert written_dirs == (expected_output_dir,)
    payloads = json.loads(
        (expected_output_dir / "runs.json").read_text(encoding="utf-8")
    )
    assert len(payloads) == 1
    payload = payloads[0]

    golden = json.loads(
        (FIXTURES / "p_n16_k8_seeds_1_10_golden.json").read_text(encoding="ascii")
    )
    common = golden["common_result"]
    seed_one = next(seed_result for seed_result in golden["seeds"] if seed_result["seed"] == 1)
    expected_state = {
        "routes": seed_one["routes"],
        "transferred_customers": common["transferred_customers"],
        "route_cost": common["route_cost"],
        "transfer_cost": common["transfer_cost"],
        "transferred_demand": common["transferred_demand"],
        "transfer_vehicle_count": common["transfer_vehicle_count"],
        "route_capacities_free": [7, 35, 12, 4, 5, 35, 35, 1],
        "transfer_capacities_free": [0, 0, 0, 0, 0, 31, 0, 0, 0],
        "strict_feasible": True,
        "violations": [],
    }

    # Runtime is intentionally observable but excluded from the deterministic
    # oracle: wall-clock duration can differ while the restored solution is exact.
    assert "runtime" in payload
    assert isinstance(payload["runtime"], (int, float))
    assert payload["runtime"] >= 0.0

    assert payload["run_seed"] == 1
    assert payload["best_objective"] == common["objective"] == 350
    assert payload["feasible"] is True
    assert payload["objective_valid"] is True
    assert payload["objective_mismatch"] is False
    assert payload["best_known_reached"] is True
    assert payload["best_known_gap"] == 0
    assert payload["error"] is None
    written_state = payload["metadata"]["validation"]["scvrp_state"]
    assert written_state == expected_state

    restored_solution = encode_scvrp_solution(
        written_state["routes"],
        written_state["transferred_customers"],
        n_customers=16,
    )
    (source_row,) = result.iter_rows()
    assert np.array_equal(restored_solution, source_row.solve_result.best_solution)


@pytest.mark.slow
def test_scvrp_batch_worker_timeout_does_not_poison_recovery() -> None:
    seeds = (1, 2)
    build_scvrp_legacy_kernel()

    timeout_bundle = _build_bundle_with_snapshot(
        experiment_name="scvrp_legacy_batch_worker_timeout",
        seeds=seeds,
        worker_count=2,
        solver_configs=_production_solver_snapshot(timeout_seconds=1.0e-9),
    )
    timeout_shm_names = _problem_bank_shm_names(timeout_bundle)
    try:
        timeout_simulator = timeout_bundle.new_simulator()
        with pytest.raises(SCVRPLegacyKernelError):
            timeout_simulator.run_batch(show_progress=False)
    finally:
        timeout_bundle.problem_bank.close()
    _assert_shared_memory_unlinked(timeout_shm_names)

    recovery_bundle = _build_bundle_with_snapshot(
        experiment_name="scvrp_legacy_batch_worker_timeout_recovery",
        seeds=seeds,
        worker_count=2,
        solver_configs=_production_solver_snapshot(max_iterations=1),
    )
    recovery_shm_names = _problem_bank_shm_names(recovery_bundle)
    try:
        recovery_simulator = recovery_bundle.new_simulator()
        recovery_result = recovery_simulator.run_batch(show_progress=False)
    finally:
        recovery_bundle.problem_bank.close()
    _assert_shared_memory_unlinked(recovery_shm_names)

    rows = recovery_result.iter_rows()
    rows_by_seed = {row.task.task_seed: row for row in rows}
    assert len(rows) == len(rows_by_seed) == len(seeds)
    assert set(rows_by_seed) == set(seeds)
    for repeat_index, seed in enumerate(seeds):
        row = rows_by_seed[seed]
        assert row.task.repeat_index == repeat_index
        assert row.solve_result.run_seed == seed
        assert row.solve_result.error is None
        assert row.solve_result.evaluation_count == 96
        assert row.solve_result.best_solution.flags.writeable is False
        assert row.solve_result.metadata["generation_count"] == 2
        assert row.solve_result.metadata["transition_count"] == 1
        assert row.solve_result.metadata["stop_cause"] == "fixed_iterations"
        assert row.validation_report.is_feasible is True
        assert row.validation_report.objective_valid is True
        routes, transferred_customers = decode_scvrp_solution(
            row.solve_result.best_solution,
            vehicle_count=8,
            n_customers=16,
        )
        assert np.array_equal(
            row.solve_result.best_solution,
            encode_scvrp_solution(routes, transferred_customers, n_customers=16),
        )

    seed_one = rows_by_seed[1].solve_result
    seed_one_routes, seed_one_transfers = decode_scvrp_solution(
        seed_one.best_solution,
        vehicle_count=8,
        n_customers=16,
    )
    assert seed_one.best_objective == 437
    assert seed_one_routes == (
        (9, 7),
        (2,),
        (8, 13),
        (10, 12, 15),
        (1, 3),
        (14, 5),
        (11, 4),
        (6,),
    )
    assert seed_one_transfers == (2,)
