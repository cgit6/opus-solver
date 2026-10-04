from __future__ import annotations

import ast
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from typing import Callable

import numpy as np
import pytest

import mkp.solver.CDELS as cdels_module
from mkp.problem.scvrp import (
    SCVRPProblem,
    decode_scvrp_solution,
    load_legacy_scvrp_problem,
)
from mkp.solver.CDELS import (
    CDELS,
    CDELSSolver,
    CDELSSolverError,
    _cpp_hexfloat,
)


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
        "solver_id": "cdels",
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
        },
    }


def test_seed_one_first_transition_matches_archive_and_validates(
    problem: SCVRPProblem,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[int, dict[str, object]]] = []
    original_run = CDELS.solve

    def spy_run(core, **kwargs):
        calls.append((core.seed, dict(kwargs)))
        return original_run(core, **kwargs)

    monkeypatch.setattr(
        CDELS,
        "solve",
        spy_run,
    )
    result = CDELSSolver().solve(
        problem,
        _config(),
        np.random.default_rng(999),
    )

    assert calls == [
        (
            1,
            {
                "termination_mode": "fixed_iterations",
                "limit": 1,
                "start_temperature": 1.0,
                "cooling_rate": 0.95,
                "iterations_per_temperature": 110,
                "max_transitions": 1,
                "trace": False,
                "process_trace": False,
            },
        )
    ]

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
    assert result.solver_id == "cdels"
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
        "execution_backend": "python",
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
        "raw_objective": 437,
        "legacy_penalty": 0,
        "legacy_search_score": 437,
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


def _add_removed_timeout_param(config: dict[str, object]) -> None:
    params = config["params"]
    assert isinstance(params, dict)
    params["timeout_seconds"] = 120.0


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
        pytest.param(_add_unknown_param, "unsupported CDELS params", id="unknown-param"),
        pytest.param(
            _add_removed_timeout_param,
            "unsupported CDELS params: \\['timeout_seconds'\\]",
            id="removed-native-timeout",
        ),
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
        CDELSSolver().solve(problem, config, np.random.default_rng(123))


def test_solver_rejects_core_objective_that_evaluator_cannot_reproduce(
    problem: SCVRPProblem,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_run = CDELS.solve

    def malformed_run(core, **kwargs):
        output = original_run(core, **kwargs)
        return replace(
            output,
            result=replace(output.result, objective=output.result.objective + 1),
        )

    monkeypatch.setattr(
        CDELS,
        "solve",
        malformed_run,
    )

    with pytest.raises(
        CDELSSolverError,
        match=r"CDELS/evaluator objective mismatch: 438 != 437",
    ):
        CDELSSolver().solve(problem, _config(), np.random.default_rng(123))


def test_solver_accepts_and_exposes_legacy_penalty_for_infeasible_result(
    problem: SCVRPProblem,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_run = CDELS.solve
    routes = (tuple(range(1, problem.n_customers)),) + ((),) * (problem.vehicle_count - 1)
    evaluation = problem.evaluate(routes, ())

    def infeasible_run(core, **kwargs):
        output = original_run(core, **kwargs)
        return replace(
            output,
            result=replace(
                output.result,
                objective=evaluation.legacy_search_score,
                feasible=False,
                transfer_vehicle_count=0,
                routes=routes,
                transferred_customers=(),
            ),
        )

    monkeypatch.setattr(
        CDELS,
        "solve",
        infeasible_run,
    )
    result = CDELSSolver().solve(
        problem,
        _config(),
        np.random.default_rng(123),
    )

    assert result.feasible is False
    assert result.best_objective == evaluation.legacy_search_score
    assert result.metadata["raw_objective"] == evaluation.objective
    assert result.metadata["legacy_penalty"] == 100
    assert result.metadata["legacy_search_score"] == evaluation.legacy_search_score
    validation = problem.validate(result)
    assert validation.is_feasible is False
    assert validation.objective_valid is True
    assert validation.recomputed_objective == evaluation.legacy_search_score


def test_solver_rejects_invalid_core_result_type(
    problem: SCVRPProblem,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        CDELS,
        "solve",
        lambda *args, **kwargs: None,
    )

    with pytest.raises(
        CDELSSolverError,
        match=r"CDELS returned an invalid loop result",
    ):
        CDELSSolver().solve(problem, _config(), np.random.default_rng(123))


@pytest.mark.parametrize(
    ("corrupt", "error_match"),
    (
        pytest.param(
            lambda output: replace(output, rng_state=0x1_0000_0000),
            "RNG state must fit in an unsigned 32-bit integer",
            id="rng-state-overflow",
        ),
        pytest.param(
            lambda output: replace(output, final_temperature=float("inf")),
            "final temperature must be finite and >= 0",
            id="non-finite-temperature",
        ),
        pytest.param(
            lambda output: replace(
                output,
                result=replace(output.result, feasible=1),
            ),
            "feasible flag must be a boolean",
            id="non-boolean-feasibility",
        ),
    ),
)
def test_solver_rejects_corrupt_core_contract(
    problem: SCVRPProblem,
    monkeypatch: pytest.MonkeyPatch,
    corrupt,
    error_match: str,
) -> None:
    original_run = CDELS.solve

    def malformed_run(core, **kwargs):
        return corrupt(original_run(core, **kwargs))

    monkeypatch.setattr(
        CDELS,
        "solve",
        malformed_run,
    )

    with pytest.raises(CDELSSolverError, match=error_match):
        CDELSSolver().solve(problem, _config(), np.random.default_rng(123))


def test_formal_adapter_has_no_native_kernel_dependency() -> None:
    source_path = Path(cdels_module.__file__)
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    imported_modules = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    imported_modules.update(
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    )

    assert not any(
        module.endswith("scvrp_native_oracle")
        for module in imported_modules
    )


@pytest.mark.parametrize(
    ("value", "expected"),
    (
        pytest.param(1.0, "0x1p+0", id="one"),
        pytest.param(0.95, "0x1.e666666666666p-1", id="first-cooling"),
        pytest.param(0.0, "0x0p+0", id="underflow-zero"),
        pytest.param(
            float.fromhex("0x1.5e2d52a31c76bp-8"),
            "0x1.5e2d52a31c76bp-8",
            id="archive-final-temperature",
        ),
    ),
)
def test_cpp_hexfloat_matches_native_metadata(value: float, expected: str) -> None:
    assert _cpp_hexfloat(value) == expected
