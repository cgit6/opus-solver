from __future__ import annotations

from pathlib import Path

import numpy as np

from mkp.engine.builders import solverBuilders
from mkp.problem.scvrp import load_legacy_scvrp_problem
from mkp.solver.CDELS import CDELSSolver
from mkp.solver.CDELS_2 import CDELS2Solver
from mkp.solver.CDELS_2_numba import CDELS2NumbaSolver
from mkp.solver.CDELS_numba import CDELSNumbaSolver
from mkp.solver.CDELS_packed_numba import CDELSPackedNumbaSolver
from mkp.tools.solver_config_loader import SolverConfigLoader


FIXTURES = Path(__file__).parent / "fixtures" / "scvrp"
REPO_ROOT = Path(__file__).resolve().parents[1]


def _problem():
    return load_legacy_scvrp_problem(
        FIXTURES / "p_n16_k8.vrp",
        FIXTURES / "p_n16_k8_routecap2_transfer1.txt",
        dataset="P",
        problem_id="P-n16-k8-routecap2-transfer1",
        best_known=350,
    )


def _config(solver_id: str) -> dict[str, object]:
    return {
        "solver_id": solver_id,
        "run_seed": 1,
        "stop_condition": {"type": "max_iterations", "max_iterations": 2},
        "params": {
            "compatibility_profile": "vs2019_v142_archive",
            "de_technique": "rand_1_exp",
            "termination_mode": "fixed_iterations",
            "start_temperature": 1.0,
            "cooling_rate": 0.95,
            "iterations_per_temperature": 110,
        },
    }


def test_numba_solvers_are_registered_and_configs_resolve() -> None:
    builders = solverBuilders()
    assert isinstance(builders["cdels_numba"](), CDELSNumbaSolver)
    assert isinstance(
        builders["cdels_packed_numba"](),
        CDELSPackedNumbaSolver,
    )
    assert isinstance(builders["cdels_2_numba"](), CDELS2NumbaSolver)

    loader = SolverConfigLoader(REPO_ROOT / "configs" / "solvers")
    for solver_id, class_name in (
        ("cdels_numba", "CDELSNumbaSolver"),
        ("cdels_packed_numba", "CDELSPackedNumbaSolver"),
        ("cdels_2_numba", "CDELS2NumbaSolver"),
    ):
        config = loader.load(solver_id, param_set_index=0)
        assert config["solver_id"] == solver_id
        assert config["solver_class"] == class_name


def test_numba_engine_adapters_match_python_adapters() -> None:
    problem = _problem()
    pairs = (
        (CDELSSolver(), "cdels", CDELSNumbaSolver(), "cdels_numba", "numba"),
        (
            CDELSSolver(),
            "cdels",
            CDELSPackedNumbaSolver(),
            "cdels_packed_numba",
            "numba_packed_population",
        ),
        (
            CDELS2Solver(),
            "cdels_2",
            CDELS2NumbaSolver(),
            "cdels_2_numba",
            "numba_workspace",
        ),
    )
    for baseline_solver, baseline_id, numba_solver, numba_id, backend in pairs:
        baseline = baseline_solver.solve(
            problem, _config(baseline_id), np.random.default_rng(999)
        )
        actual = numba_solver.solve(
            problem, _config(numba_id), np.random.default_rng(999)
        )
        assert actual.solver_id == numba_id
        assert np.array_equal(actual.best_solution, baseline.best_solution)
        assert actual.best_objective == baseline.best_objective
        assert actual.feasible == baseline.feasible
        assert actual.evaluation_count == baseline.evaluation_count
        assert actual.stop_reason == baseline.stop_reason
        assert actual.metadata["execution_backend"] == backend
        for key in (
            "generation_count",
            "transition_count",
            "feasible_solution_count",
            "final_temperature_hex",
            "rng_state",
            "rng_draw_count",
            "transfer_vehicle_count",
            "raw_objective",
            "legacy_penalty",
            "legacy_search_score",
        ):
            assert actual.metadata[key] == baseline.metadata[key]
