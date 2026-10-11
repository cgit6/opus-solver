from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from mkp.engine.builders import solverBuilders
from mkp.engine.repository import ProblemRepository
from mkp.problem import buildProblemRegistry, problemBuilders
from mkp.problem.continuous import ContinuousProblem
from mkp.solver.TLBO import TLBOSolver
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
        "solver_id": "tlbo",
        "run_seed": 12345,
        "stop_condition": {"type": "max_iterations", "max_iterations": 3},
        "params": {
            "compatibility_profile": "book_archive_tlbo_v1",
            "population_size": 8,
            "constraint_penalty": 1.0e33,
        },
    }


def test_tlbo_is_registered_and_default_config_resolves() -> None:
    builders = solverBuilders()
    config = SolverConfigLoader(ROOT / "configs" / "solvers").load(
        "tlbo",
        param_set_index=0,
    )

    assert isinstance(builders["tlbo"](), TLBOSolver)
    assert config["solver_class"] == "TLBOSolver"
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
        "compatibility_profile": "book_archive_tlbo_v1",
        "population_size": 50,
        "constraint_penalty": 1.0e33,
    }


def test_tlbo_adapter_matches_frozen_archive_result() -> None:
    problem = _sphere_problem()
    result = TLBOSolver().solve(
        problem,
        _short_config(),
        np.random.default_rng(999),
    )

    assert [float(value).hex() for value in result.best_solution] == [
        "0x1.53c1f68e06cc0p-1",
        "0x1.9ff0c33acc1f8p-1",
    ]
    assert float(result.best_objective).hex() == "0x1.19ae705646a2dp+0"
    assert result.run_seed == 12345
    assert result.evaluation_count == 80
    assert result.stop_reason == "max_iterations_reached"
    assert result.feasible is True
    assert result.metadata["curve_sha256"] == (
        "5d8fa235720a7743207edf27bb8bbedaae24b469a27ea3758755647246014298"
    )
    assert result.metadata["numpy_rng_state_sha256"] == (
        "275b109995034b6f7590f7486ca29eb55e38560ada001abb0d833a6f3ebcfaba"
    )
    assert result.metadata["python_rng_state_sha256"] == (
        "83082cf90133bd5bd53a95223ef3eeedb446a0768c24f436c43b89bd3cc73278"
    )
    report = problem.validate(result)
    assert report.is_feasible is True
    assert report.objective_valid is True


def test_tlbo_adapter_is_independent_of_engine_default_rng() -> None:
    problem = _sphere_problem()
    first = TLBOSolver().solve(problem, _short_config(), np.random.default_rng(1))
    second = TLBOSolver().solve(problem, _short_config(), np.random.default_rng(987654))

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
def test_tlbo_adapter_rejects_settings_that_break_compatibility(
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
        TLBOSolver().solve(
            _sphere_problem(),
            config,
            np.random.default_rng(1),
        )


def test_tlbo_adapter_rejects_one_dimensional_problem_instead_of_hanging() -> None:
    problem = ContinuousProblem(
        problem_id="sphere_1d",
        dataset="unit",
        best_known=0.0,
        dimension=1,
        lower_bounds=np.array([-10.0]),
        upper_bounds=np.array([10.0]),
        objective_id="sphere",
    )

    with pytest.raises(ValueError, match="requires dimension > 1"):
        TLBOSolver().solve(
            problem,
            _short_config(),
            np.random.default_rng(1),
        )
