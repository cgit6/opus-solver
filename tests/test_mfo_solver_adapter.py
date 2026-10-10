from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from mkp.engine.builders import solverBuilders
from mkp.engine.repository import ProblemRepository
from mkp.problem import buildProblemRegistry, problemBuilders
from mkp.solver.MFO import MFOSolver
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
        "solver_id": "mfo",
        "run_seed": 12345,
        "stop_condition": {"type": "max_iterations", "max_iterations": 3},
        "params": {
            "compatibility_profile": "book_archive_mfo_v1",
            "population_size": 8,
            "constraint_penalty": 1.0e33,
        },
    }


def test_mfo_is_registered_and_default_config_resolves() -> None:
    builders = solverBuilders()
    config = SolverConfigLoader(ROOT / "configs" / "solvers").load(
        "mfo",
        param_set_index=0,
    )

    assert isinstance(builders["mfo"](), MFOSolver)
    assert config["solver_class"] == "MFOSolver"
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
        "compatibility_profile": "book_archive_mfo_v1",
        "population_size": 50,
        "constraint_penalty": 1.0e33,
    }


def test_mfo_adapter_matches_frozen_archive_result() -> None:
    problem = _sphere_problem()
    result = MFOSolver().solve(
        problem,
        _short_config(),
        np.random.default_rng(999),
    )

    assert [float(value).hex() for value in result.best_solution] == [
        "0x1.5ac08cd487a50p+0",
        "0x1.e9305a6409d38p+0",
    ]
    assert float(result.best_objective).hex() == "0x1.5f1db3fd8f79bp+2"
    assert result.run_seed == 12345
    assert result.evaluation_count == 32
    assert result.stop_reason == "max_iterations_reached"
    assert result.feasible is True
    assert result.metadata["curve_sha256"] == (
        "df0127882446bbc703dae6244d3d03f157a8ca65770fb07b5fadc1f74bcc4b6d"
    )
    assert result.metadata["numpy_rng_state_sha256"] == (
        "3dba7f963ef6811ccfb353da80a7447f190235bfd5882e60884ece67544d8288"
    )
    assert result.metadata["python_rng_state_sha256"] == (
        "345acdef26e968c5a96433950ff61c6d52bd1d91a7a5ae4df30184734181470c"
    )
    report = problem.validate(result)
    assert report.is_feasible is True
    assert report.objective_valid is True


def test_mfo_adapter_is_independent_of_engine_default_rng() -> None:
    problem = _sphere_problem()
    first = MFOSolver().solve(problem, _short_config(), np.random.default_rng(1))
    second = MFOSolver().solve(problem, _short_config(), np.random.default_rng(987654))

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
def test_mfo_adapter_rejects_settings_that_break_compatibility(
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
        MFOSolver().solve(
            _sphere_problem(),
            config,
            np.random.default_rng(1),
        )
