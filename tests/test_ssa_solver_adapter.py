from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from mkp.engine.builders import solverBuilders
from mkp.engine.repository import ProblemRepository
from mkp.problem import buildProblemRegistry, problemBuilders
from mkp.solver.SSA import SSASolver
from mkp.tools.solver_config_loader import SolverConfigLoader


ROOT = Path(__file__).resolve().parents[1]


def _sphere_problem():
    repository = ProblemRepository(
        ROOT / "configs" / "problems",
        registry=buildProblemRegistry(problemBuilders()),
    )
    return repository.load("book_examples", "sphere_2d", "continuous")


def _short_config() -> dict[str, object]:
    return {
        "solver_id": "ssa",
        "run_seed": 12345,
        "stop_condition": {"type": "max_iterations", "max_iterations": 3},
        "params": {
            "compatibility_profile": "book_archive_ssa_v1",
            "population_size": 8,
            "constraint_penalty": 1.0e33,
        },
    }


def test_ssa_is_registered_and_default_config_resolves() -> None:
    builders = solverBuilders()
    config = SolverConfigLoader(ROOT / "configs" / "solvers").load(
        "ssa",
        param_set_index=0,
    )

    assert isinstance(builders["ssa"](), SSASolver)
    assert config["solver_class"] == "SSASolver"
    assert config["capabilities"] == {
        "problem_types": ["continuous"],
        "encodings": ["real_vector"],
        "directions": ["min"],
    }
    assert config["stop_condition"] == {
        "type": "max_iterations",
        "max_iterations": 100,
    }
    assert config["params"] == {
        "compatibility_profile": "book_archive_ssa_v1",
        "population_size": 50,
        "constraint_penalty": 1.0e33,
    }


def test_ssa_adapter_matches_frozen_archive_result() -> None:
    problem = _sphere_problem()
    result = SSASolver().solve(
        problem,
        _short_config(),
        np.random.default_rng(999),
    )

    assert [float(value).hex() for value in result.best_solution] == [
        "0x1.08d3b320088a4p-10",
        "0x1.08cc667a1455ap-10",
    ]
    assert float(result.best_objective).hex() == "0x1.11edc3890da3cp-19"
    assert result.run_seed == 12345
    assert result.evaluation_count == 80
    assert result.stop_reason == "max_iterations_reached"
    assert result.feasible is True
    assert result.metadata["curve_sha256"] == (
        "3546918374fd4e8877f73622ce4ec6cb446cfd1906ee0dddec399807ed97daa4"
    )
    assert result.metadata["numpy_rng_state_sha256"] == (
        "633e0d96e938111b01041572f4be0c184bcecc34484d99600f83f46db429c426"
    )
    assert result.metadata["python_rng_state_sha256"] == (
        "ed6cefa857a5dce216dcb7fe77199e910d6dc2b65c4a92738a68c5b42bbdbfd5"
    )
    report = problem.validate(result)
    assert report.is_feasible is True
    assert report.objective_valid is True


def test_ssa_adapter_is_independent_of_engine_default_rng() -> None:
    problem = _sphere_problem()
    first = SSASolver().solve(problem, _short_config(), np.random.default_rng(1))
    second = SSASolver().solve(problem, _short_config(), np.random.default_rng(987654))

    np.testing.assert_array_equal(first.best_solution, second.best_solution)
    assert first.best_objective == second.best_objective
    assert first.evaluation_count == second.evaluation_count
    assert first.stop_reason == second.stop_reason
    assert first.metadata == second.metadata


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("run_seed", None, "run_seed is required"),
        ("population_size", 1, "population_size must be > 1"),
        ("compatibility_profile", "changed", "compatibility_profile"),
    ],
)
def test_ssa_adapter_rejects_settings_that_break_compatibility(
    field: str,
    value: object,
    message: str,
) -> None:
    config = _short_config()
    if field == "run_seed":
        config.pop("run_seed")
    else:
        config["params"][field] = value  # type: ignore[index]

    with pytest.raises(ValueError, match=message):
        SSASolver().solve(
            _sphere_problem(),
            config,
            np.random.default_rng(1),
        )
