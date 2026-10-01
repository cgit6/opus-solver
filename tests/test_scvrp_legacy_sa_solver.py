from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Callable

import numpy as np
import pytest

import mkp.solver.scvrp_legacy_sa as legacy_sa
from mkp.problem.scvrp import (
    SCVRPProblem,
    decode_scvrp_solution,
    load_legacy_scvrp_problem,
)
from mkp.solver.scvrp_legacy_kernel import SCVRPLegacyKernelError
from mkp.solver.scvrp_legacy_sa import SCVRPLegacySASolver


FIXTURES = Path(__file__).parent / "fixtures" / "scvrp"


@pytest.fixture(scope="module")
def problem() -> SCVRPProblem:
    return load_legacy_scvrp_problem(
        FIXTURES / "p_n16_k8.vrp",
        FIXTURES / "p_n16_k8_routecap2_transfer1.txt",
        dataset="P",
        problem_id="P-n16-k8-routecap2-transfer1",
        best_known=350,
    )


def _config(*, run_seed: int = 1, max_iterations: int = 1) -> dict[str, object]:
    return {
        "solver_id": "scvrp_legacy_sa",
        "run_seed": run_seed,
        "stop_condition": {
            "type": "max_iterations",
            "max_iterations": max_iterations,
        },
        "params": {
            "compatibility_profile": "vs2019_v142_archive",
            "de_technique": "rand_1_exp",
            "termination_mode": "fixed_iterations",
            "start_temperature": 1.0,
            "cooling_rate": 0.95,
            "iterations_per_temperature": 110,
            "timeout_seconds": 120.0,
        },
    }


def test_seed_one_first_transition_matches_archive_and_validates(
    problem: SCVRPProblem,
) -> None:
    result = SCVRPLegacySASolver().solve(
        problem,
        _config(),
        np.random.default_rng(999),
    )

    routes, transferred = decode_scvrp_solution(
        result.best_solution,
        vehicle_count=problem.vehicle_count,
        n_customers=problem.n_customers,
    )
    assert routes == (
        (9, 7),
        (2,),
        (8, 13),
        (10, 12, 15),
        (1, 3),
        (14, 5),
        (11, 4),
        (6,),
    )
    assert transferred == (2,)
    assert result.problem_id == problem.problem_id
    assert result.solver_id == "scvrp_legacy_sa"
    assert result.run_seed == 1
    assert result.best_objective == 437
    assert result.feasible is True
    assert result.evaluation_count == 96
    assert result.stop_reason == "max_iterations_reached"
    assert result.runtime >= 0.0
    assert result.linprog_runtime == 0.0
    assert result.error is None
    assert result.metadata == {
        "compatibility_profile": "vs2019_v142_archive",
        "de_technique": "rand_1_exp",
        "native_protocol": "SCVRP_LEGACY_RESULT_V1",
        "termination_mode": "fixed_iterations",
        "stop_cause": "fixed_iterations",
        "population_size": 48,
        "generation_count": 2,
        "transition_count": 1,
        "feasible_solution_count": 42,
        "temperature_stagnation": 0,
        "final_temperature_hex": "0x1p+0",
        "rng_algorithm": "msvc_rand",
        "rng_state": 2_587_854_408,
        "rng_draw_count": 16_073,
        "transfer_vehicle_count": 1,
    }

    validation = problem.validate(result)
    assert validation.is_feasible is True
    assert validation.objective_valid is True
    assert validation.recomputed_objective == 437
    assert validation.best_known_reached is False
    assert validation.best_known_gap == 87
    assert validation.metadata["scvrp_state"]["routes"] == [list(route) for route in routes]
    assert validation.metadata["scvrp_state"]["transferred_customers"] == [2]
    assert validation.metadata["scvrp_state"]["transfer_vehicle_count"] == 1


def _remove_run_seed(config: dict[str, object]) -> None:
    config.pop("run_seed")


def _use_boolean_seed(config: dict[str, object]) -> None:
    config["run_seed"] = True


def _use_zero_seed(config: dict[str, object]) -> None:
    config["run_seed"] = 0


def _overflow_seed(config: dict[str, object]) -> None:
    config["run_seed"] = 0x1_0000_0000


def _use_time_stop(config: dict[str, object]) -> None:
    config["stop_condition"] = {"type": "max_seconds", "max_seconds": 1.0}


def _use_boolean_iteration_limit(config: dict[str, object]) -> None:
    config["stop_condition"] = {"type": "max_iterations", "max_iterations": True}


def _overflow_generation_counter(config: dict[str, object]) -> None:
    config["stop_condition"] = {
        "type": "max_iterations",
        "max_iterations": 0x7FFF_FFFF,
    }


def _add_unknown_param(config: dict[str, object]) -> None:
    params = config["params"]
    assert isinstance(params, dict)
    params["typo_parameter"] = 1


@pytest.mark.parametrize(
    ("mutate", "error_match"),
    (
        pytest.param(_remove_run_seed, "run_seed is required", id="missing-seed"),
        pytest.param(_use_boolean_seed, "run_seed must be an integer", id="boolean-seed"),
        pytest.param(_use_zero_seed, "run_seed must be > 0", id="zero-seed"),
        pytest.param(_overflow_seed, "unsigned 32-bit", id="overflow-seed"),
        pytest.param(_use_time_stop, "stop_condition.type=max_iterations", id="time-stop"),
        pytest.param(
            _use_boolean_iteration_limit,
            "stop_condition.max_iterations must be an integer",
            id="boolean-iteration-limit",
        ),
        pytest.param(
            _overflow_generation_counter,
            "stop_condition.max_iterations is too large",
            id="generation-counter-overflow",
        ),
        pytest.param(_add_unknown_param, "unsupported SCVRP legacy params", id="unknown-param"),
    ),
)
def test_solver_rejects_incompatible_seed_and_config(
    problem: SCVRPProblem,
    mutate: Callable[[dict[str, object]], None],
    error_match: str,
) -> None:
    config = deepcopy(_config())
    mutate(config)

    with pytest.raises(ValueError, match=error_match):
        SCVRPLegacySASolver().solve(problem, config, np.random.default_rng(123))


def test_solver_rejects_native_objective_that_python_cannot_reproduce(
    problem: SCVRPProblem,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    malformed_native = {
        "protocol": "SCVRP_LEGACY_RESULT_V1",
        "seed": 1,
        "termination": "fixed_iterations",
        "stop_cause": "fixed_iterations",
        "generation_count": 2,
        "transition_count": 1,
        "temperature_stagnation": 0,
        "final_temperature_hex": "0x1p+0",
        "rng_state": 2_587_854_408,
        "rng_draw_count": 16_073,
        "result": {
            "generation": 2,
            "objective": 438,
            "feasible_solutions": 42,
            "feasible": True,
            "transfer_vehicle_count": 1,
            "routes": [
                [9, 7],
                [2],
                [8, 13],
                [10, 12, 15],
                [1, 3],
                [14, 5],
                [11, 4],
                [6],
            ],
            "transferred_customers": [2],
        },
        "trace": [],
    }
    monkeypatch.setattr(
        legacy_sa,
        "build_scvrp_legacy_kernel",
        lambda: Path("/unused/scvrp_legacy_runner"),
    )
    monkeypatch.setattr(
        legacy_sa,
        "run_scvrp_legacy_kernel",
        lambda *args, **kwargs: malformed_native,
    )

    with pytest.raises(
        SCVRPLegacyKernelError,
        match=r"native/Python objective mismatch: 438 != 437",
    ):
        SCVRPLegacySASolver().solve(problem, _config(), np.random.default_rng(123))


def test_solver_rejects_non_boolean_native_feasibility(
    problem: SCVRPProblem,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    malformed_native = {
        "protocol": "SCVRP_LEGACY_RESULT_V1",
        "seed": 1,
        "termination": "fixed_iterations",
        "stop_cause": "fixed_iterations",
        "generation_count": 2,
        "transition_count": 1,
        "temperature_stagnation": 0,
        "final_temperature_hex": "0x1p+0",
        "rng_state": 2_587_854_408,
        "rng_draw_count": 16_073,
        "result": {
            "generation": 2,
            "objective": 437,
            "feasible_solutions": 42,
            "feasible": "false",
            "transfer_vehicle_count": 1,
            "routes": [[9, 7], [2], [8, 13], [10, 12, 15], [1, 3], [14, 5], [11, 4], [6]],
            "transferred_customers": [2],
        },
        "trace": [],
    }
    monkeypatch.setattr(
        legacy_sa,
        "build_scvrp_legacy_kernel",
        lambda: Path("/unused/scvrp_legacy_runner"),
    )
    monkeypatch.setattr(
        legacy_sa,
        "run_scvrp_legacy_kernel",
        lambda *args, **kwargs: malformed_native,
    )

    with pytest.raises(
        SCVRPLegacyKernelError,
        match=r"native kernel field result.feasible must be a boolean",
    ):
        SCVRPLegacySASolver().solve(problem, _config(), np.random.default_rng(123))
