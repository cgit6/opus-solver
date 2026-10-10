from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from mkp.engine.repository import ProblemRepository
from mkp.problem import buildProblemRegistry, problemBuilders
from mkp.solver.ABC import ABCSolver
from mkp.tools.book_continuous_oracle import (
    ABC_ENGINEERING_CASES,
    load_abc_engineering_archive_objective,
    run_abc_engineering_archive_oracle,
)


ROOT = Path(__file__).resolve().parents[1]


def _archive_path() -> Path:
    matches = sorted((ROOT / "note").glob("《Python智能优化算法：从原理到代码实现与应用》代码-*.zip"))
    if not matches:
        pytest.skip("book continuous source archive is not present")
    if len(matches) != 1:
        raise AssertionError(f"expected one book continuous source archive, found {len(matches)}")
    return matches[0]


def _problem(problem_id: str):
    repository = ProblemRepository(
        ROOT / "configs" / "problems",
        registry=buildProblemRegistry(problemBuilders()),
    )
    return repository.load("book_engineering", problem_id, "continuous")


@pytest.mark.parametrize(
    ("problem_id", "feasible", "infeasible"),
    [
        (
            "pressure_vessel",
            np.array([2.0, 1.0, 100.0, 10.0]),
            np.array([0.0, 0.0, 10.0, 10.0]),
        ),
        (
            "three_bar_truss",
            np.array([0.7886751346, 0.4082482905]),
            np.array([0.1, 0.1]),
        ),
        (
            "tension_compression_spring",
            np.array([0.052, 0.36, 11.5]),
            np.array([0.05, 0.25, 2.0]),
        ),
    ],
)
def test_registered_engineering_objective_and_penalty_match_source_fun(
    problem_id: str,
    feasible: np.ndarray,
    infeasible: np.ndarray,
) -> None:
    problem = _problem(problem_id)
    source_objective, _, _ = load_abc_engineering_archive_objective(
        _archive_path(),
        problem_id,
    )

    assert problem.violates_constraints(feasible) is False
    assert float(source_objective(feasible)).hex() == float(problem.fitness(feasible)).hex()
    assert problem.violates_constraints(infeasible) is True
    assert float(source_objective(infeasible)).hex() == float(1.0e33).hex()


@pytest.mark.parametrize("problem_id", tuple(ABC_ENGINEERING_CASES))
def test_abc_adapter_matches_full_book_engineering_run(problem_id: str) -> None:
    case = ABC_ENGINEERING_CASES[problem_id]
    oracle = run_abc_engineering_archive_oracle(
        _archive_path(),
        problem_id=problem_id,
        seed=12345,
    )
    config = {
        "solver_id": "abc",
        "run_seed": 12345,
        "stop_condition": {
            "type": "max_iterations",
            "max_iterations": case.max_iterations,
        },
        "params": {
            "compatibility_profile": "book_archive_abc_v1",
            "population_size": case.population_size,
            "constraint_penalty": 1.0e33,
        },
    }
    result = ABCSolver().solve(
        _problem(problem_id),
        config,
        np.random.default_rng(999),
    )
    expected = oracle["result"]

    assert float(result.best_objective).hex() == expected["best_score"]["float_hex"][0]
    assert [float(value).hex() for value in result.best_solution] == expected["best_position"]["float_hex"]
    assert result.metadata["curve_sha256"] == expected["curve"]["sha256"]
    assert result.metadata["numpy_rng_state_sha256"] == expected["numpy_rng_state_sha256"]
    assert result.metadata["python_rng_state_sha256"] == expected["python_rng_state_sha256"]
    assert result.evaluation_count == case.population_size * (1 + 3 * case.max_iterations)
    assert result.feasible is True
