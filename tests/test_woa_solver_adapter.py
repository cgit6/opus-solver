from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from mkp.engine.builders import solverBuilders
from mkp.engine.repository import ProblemRepository
from mkp.problem import buildProblemRegistry, problemBuilders
from mkp.solver.WOA import WOASolver
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
        "solver_id": "woa",
        "run_seed": 12345,
        "stop_condition": {"type": "max_iterations", "max_iterations": 3},
        "params": {
            "compatibility_profile": "book_archive_woa_v1",
            "population_size": 8,
            "constraint_penalty": 1.0e33,
        },
    }


def test_woa_is_registered_and_default_config_resolves() -> None:
    builders = solverBuilders()
    config = SolverConfigLoader(ROOT / "configs" / "solvers").load(
        "woa",
        param_set_index=0,
    )

    assert isinstance(builders["woa"](), WOASolver)
    assert config["solver_class"] == "WOASolver"
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
        "compatibility_profile": "book_archive_woa_v1",
        "population_size": 50,
        "constraint_penalty": 1.0e33,
    }


def test_woa_adapter_matches_frozen_archive_result() -> None:
    problem = _sphere_problem()
    result = WOASolver().solve(
        problem,
        _short_config(),
        np.random.default_rng(999),
    )

    assert [float(value).hex() for value in result.best_solution] == [
        "0x1.5a81daf1c6cd8p-3",
        "-0x1.43329afcb81cep-2",
    ]
    assert float(result.best_objective).hex() == "0x1.06a4c743ce9ccp-3"
    assert result.run_seed == 12345
    assert result.evaluation_count == 32
    assert result.stop_reason == "max_iterations_reached"
    assert result.feasible is True
    assert result.metadata["curve_sha256"] == (
        "8ebfb55be18ba88ff5a74b686a13b043459d89064f99aa0597871160145f66b9"
    )
    assert result.metadata["numpy_rng_state_sha256"] == (
        "3dba7f963ef6811ccfb353da80a7447f190235bfd5882e60884ece67544d8288"
    )
    assert result.metadata["python_rng_state_sha256"] == (
        "787224fa6e6b557ebcf0dbf1e6382ba6304f382b655b06c87e84c0ab5ae5c968"
    )
    report = problem.validate(result)
    assert report.is_feasible is True
    assert report.objective_valid is True


def test_woa_adapter_is_independent_of_engine_default_rng() -> None:
    problem = _sphere_problem()
    first = WOASolver().solve(problem, _short_config(), np.random.default_rng(1))
    second = WOASolver().solve(problem, _short_config(), np.random.default_rng(987654))

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
def test_woa_adapter_rejects_settings_that_break_compatibility(
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
        WOASolver().solve(
            _sphere_problem(),
            config,
            np.random.default_rng(1),
        )
