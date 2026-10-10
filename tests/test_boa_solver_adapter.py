from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from mkp.engine.builders import solverBuilders
from mkp.engine.repository import ProblemRepository
from mkp.problem import buildProblemRegistry, problemBuilders
from mkp.solver.BOA import BOASolver
from mkp.tools.solver_config_loader import SolverConfigLoader


ROOT = Path(__file__).resolve().parents[1]
PROFILE_RESULTS = {
    "book_archive_boa_base_v1": {
        "position": ["0x1.297503e66ae58p+0", "0x1.a3a50af0039a2p+0"],
        "objective": "0x1.0261992f7e971p+2",
        "curve_sha256": "b77add2b12aa54e7586690ac28b9231caf9b158f77ff72cb6292694de8a380fc",
    },
    "book_archive_boa_spring_v1": {
        "position": ["0x1.59c032094c988p+0", "0x1.e7c6b1d2c0dfep+0"],
        "objective": "0x1.5d174a7be3e23p+2",
        "curve_sha256": "e1f02c3c33b28a0fa8a235c4ffeab2c0be039b910e5d4c4b1cef8ca1070533a7",
    },
}


def _sphere_problem():
    repository = ProblemRepository(
        ROOT / "configs" / "problems",
        registry=buildProblemRegistry(problemBuilders()),
    )
    return repository.load("book_examples", "sphere_2d", "continuous")


def _short_config(profile: str) -> dict[str, object]:
    return {
        "solver_id": "boa",
        "run_seed": 12345,
        "stop_condition": {"type": "max_iterations", "max_iterations": 3},
        "params": {
            "compatibility_profile": profile,
            "population_size": 8,
            "constraint_penalty": 1.0e33,
        },
    }


def test_boa_is_registered_and_both_profile_configs_resolve() -> None:
    builders = solverBuilders()
    loader = SolverConfigLoader(ROOT / "configs" / "solvers")
    configs = loader.load_all("boa")

    assert isinstance(builders["boa"](), BOASolver)
    assert len(configs) == 2
    assert [config["group_key"] for config in configs] == [
        "book_base_pop50",
        "book_spring_pop30",
    ]
    assert [config["params"]["compatibility_profile"] for config in configs] == [
        "book_archive_boa_base_v1",
        "book_archive_boa_spring_v1",
    ]
    assert all(config["solver_class"] == "BOASolver" for config in configs)
    assert all(
        config["capabilities"]
        == {
            "problem_types": ["continuous"],
            "encodings": ["real_vector"],
            "directions": ["min"],
        }
        for config in configs
    )


@pytest.mark.parametrize("profile", tuple(PROFILE_RESULTS))
def test_boa_adapter_matches_profile_golden(profile: str) -> None:
    problem = _sphere_problem()
    result = BOASolver().solve(
        problem,
        _short_config(profile),
        np.random.default_rng(999),
    )
    expected = PROFILE_RESULTS[profile]

    assert [float(value).hex() for value in result.best_solution] == expected["position"]
    assert float(result.best_objective).hex() == expected["objective"]
    assert result.run_seed == 12345
    assert result.evaluation_count == 76
    assert result.stop_reason == "max_iterations_reached"
    assert result.feasible is True
    assert result.metadata["compatibility_profile"] == profile
    assert result.metadata["curve_sha256"] == expected["curve_sha256"]
    assert result.metadata["numpy_rng_state_sha256"] == (
        "3dba7f963ef6811ccfb353da80a7447f190235bfd5882e60884ece67544d8288"
    )
    assert result.metadata["python_rng_state_sha256"] == (
        "dac690dbe81c7079ff0354fe5a6d02c65d381a60531542b5ea0e7a6c1e83475d"
    )
    report = problem.validate(result)
    assert report.is_feasible is True
    assert report.objective_valid is True


@pytest.mark.parametrize("profile", tuple(PROFILE_RESULTS))
def test_boa_adapter_is_independent_of_engine_default_rng(profile: str) -> None:
    problem = _sphere_problem()
    first = BOASolver().solve(problem, _short_config(profile), np.random.default_rng(1))
    second = BOASolver().solve(problem, _short_config(profile), np.random.default_rng(987654))

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
def test_boa_adapter_rejects_settings_that_break_compatibility(
    field: str,
    value: object,
    message: str,
) -> None:
    config = _short_config("book_archive_boa_base_v1")
    if field == "run_seed":
        config.pop("run_seed")
    else:
        config["params"][field] = value  # type: ignore[index]

    with pytest.raises(ValueError, match=message):
        BOASolver().solve(
            _sphere_problem(),
            config,
            np.random.default_rng(1),
        )
