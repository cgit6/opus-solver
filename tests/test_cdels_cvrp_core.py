from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from mkp.engine.repository import ProblemRepository
from mkp.problem import CVRPProblem, buildProblemRegistry, problemBuilders
from mkp.problem.cvrp import decode_cvrp_solution
from mkp.solver.CDELS_CVRP import CDELSCVRP, CDELSCVRPSolver


ROOT = Path(__file__).resolve().parents[1]


def _problem() -> CVRPProblem:
    repository = ProblemRepository(
        ROOT / "configs" / "problems",
        registry=buildProblemRegistry(problemBuilders()),
    )
    problem = repository.load("P", "P-n16-k8", "cvrp")
    assert isinstance(problem, CVRPProblem)
    return problem


def _config(*, seed: int = 1, iterations: int = 3) -> dict[str, object]:
    return {
        "solver_id": "cdels_cvrp",
        "run_seed": seed,
        "stop_condition": {
            "type": "max_iterations",
            "max_iterations": iterations,
        },
        "params": {
            "algorithm_profile": "cdels_cvrp_v1",
            "de_technique": "rand_1_exp",
            "termination_mode": "fixed_iterations",
            "start_temperature": 1.0,
            "cooling_rate": 0.95,
            "iterations_per_temperature": 110,
        },
    }


def _assert_internal_state_is_valid(
    algorithm: CDELSCVRP,
    *,
    require_feasible: bool,
) -> None:
    generation = algorithm.initialize_population()
    assert len(generation.individuals) == 3 * algorithm.problem.n_customers
    assert generation.generation_id == 1

    expected_customers = list(range(1, algorithm.problem.n_customers))
    for individual in generation.individuals:
        routed = sorted(customer for route in individual.routes for customer in route)
        assert routed == expected_customers
        assert np.count_nonzero(individual.transfer_mask) == 0
        evaluation = algorithm.problem.evaluate(individual.routes)
        assert individual.feasible is evaluation.feasible
        assert individual.cost == evaluation.objective + (
            0 if evaluation.feasible else 100
        )
        assert individual.route_capacities_free == list(
            evaluation.route_capacities_free
        )
    if require_feasible:
        assert generation.feasible_solutions > 0


def test_cdels_cvrp_initial_population_has_complete_routes() -> None:
    _assert_internal_state_is_valid(CDELSCVRP(_problem(), seed=1), require_feasible=True)


def test_cdels_cvrp_fixed_seed_reproduces_every_generation() -> None:
    problem = _problem()
    outputs = []
    for _ in range(2):
        outputs.append(
            CDELSCVRP(problem, seed=1).solve(
                termination_mode="fixed_iterations",
                limit=3,
                start_temperature=1.0,
                cooling_rate=0.95,
                iterations_per_temperature=2,
                max_transitions=3,
                trace=True,
                process_trace=True,
            )
        )

    left, right = outputs
    assert left.result == right.result
    assert left.trace == right.trace
    assert left.process_trace == right.process_trace
    assert left.process_trace_sha256 == right.process_trace_sha256
    assert left.rng_state == right.rng_state
    assert left.rng_draw_count == right.rng_draw_count
    assert left.transition_count == right.transition_count == 3
    assert left.generation_count == right.generation_count == 4

    evaluation = problem.evaluate(left.result.routes)
    assert evaluation.feasible is left.result.feasible
    assert evaluation.objective == left.result.objective
    assert left.result.transferred_customers == ()
    assert left.result.transfer_vehicle_count == 0


def test_cdels_cvrp_adapter_returns_a_self_validating_result() -> None:
    problem = _problem()
    result = CDELSCVRPSolver().solve(
        problem,
        _config(),
        np.random.default_rng(999),
    )

    routes = decode_cvrp_solution(
        result.best_solution,
        vehicle_count=problem.vehicle_count,
        n_customers=problem.n_customers,
    )
    evaluation = problem.evaluate(routes)
    assert evaluation.feasible is True
    assert evaluation.objective == result.best_objective == 450
    assert result.solver_id == "cdels_cvrp"
    assert result.run_seed == 1
    assert result.evaluation_count == 192
    assert result.metadata["search_penalty"] == 0
    assert result.metadata["search_score"] == 450

    validation = problem.validate(result)
    assert validation.is_feasible is True
    assert validation.objective_valid is True
    assert validation.recomputed_objective == 450


def test_cdels_cvrp_adapter_rejects_wrong_problem_and_unknown_param() -> None:
    problem = _problem()
    config = _config()
    params = config["params"]
    assert isinstance(params, dict)
    params["typo"] = 1
    with pytest.raises(ValueError, match="unsupported CDELS-CVRP params"):
        CDELSCVRPSolver().solve(
            problem,
            config,
            np.random.default_rng(1),
        )


@pytest.mark.slow
@pytest.mark.parametrize(
    ("dataset", "problem_id", "raw_objective", "search_score", "feasible", "digest"),
    (
        ("P", "P-n16-k8", 450, 450, True, "9a8cc9d3eea63558db63225d3b2df64f7b3866ff3cc4aafa57f8b649fb85b751"),
        ("P", "P-n19-k2", 221, 221, True, "3e080decf4969fccf3d72de5ce62fa6867eaa05397ba15efccec460d76bf95af"),
        ("P", "P-n23-k8", 751, 851, False, "682671e00e9e4ad3f7fb56e263dd54946f41592655c5129c357a8b7ecd639fdc"),
        ("A", "A-n32-k5", 794, 794, True, "b7b6483634be500dfb195fd062971673d661fcf959a8f6d1f870780f90bf64af"),
        ("A", "A-n48-k7", 1136, 1136, True, "819cc12644ae8e09a910247d293a1450501a0d56e15bc43f425d0dbab21839df"),
        ("A", "A-n64-k9", 1515, 1515, True, "e6f31b1ce2652c74f345d0e4ad0c502eb6545f4b46403ac9e0373a3a47f914a7"),
        ("A", "A-n80-k10", 1934, 1934, True, "ae3e15014cc844d1faa307249f873078867698dfd47de3b363d93ee7ce2786dc"),
    ),
)
def test_cdels_cvrp_one_transition_baseline_for_every_instance(
    dataset: str,
    problem_id: str,
    raw_objective: int,
    search_score: int,
    feasible: bool,
    digest: str,
) -> None:
    repository = ProblemRepository(
        ROOT / "configs" / "problems",
        registry=buildProblemRegistry(problemBuilders()),
    )
    problem = repository.load(dataset, problem_id, "cvrp")
    assert isinstance(problem, CVRPProblem)
    output = CDELSCVRP(problem, seed=1).solve(
        termination_mode="fixed_iterations",
        limit=1,
        max_transitions=1,
        trace=True,
        process_trace=True,
    )
    evaluation = problem.evaluate(output.result.routes)

    assert evaluation.objective == raw_objective
    assert output.result.objective == search_score
    assert output.result.feasible is evaluation.feasible is feasible
    assert output.process_trace_sha256 == digest
