from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import numpy as np

from mkp.engine.models import SolveResult
from mkp.engine.repository import ProblemRepository
from mkp.problem import buildProblemRegistry, problemBuilders
from mkp.problem.scvrp import (
    LegacySCVRPSolution,
    SCVRPProblem,
    attach_scvrp_shm_pack,
    decode_scvrp_solution,
    encode_scvrp_solution,
    make_scvrp_shm_pack,
    parse_legacy_cvrp_instance,
    parse_legacy_fixed_route_plan,
    parse_legacy_scvrp_solutions,
)


FIXTURES = Path(__file__).parent / "fixtures" / "scvrp"


def _archived_problem_and_solution() -> tuple[SCVRPProblem, LegacySCVRPSolution]:
    instance = parse_legacy_cvrp_instance(FIXTURES / "p_n16_k8.vrp")
    fixed_plan = parse_legacy_fixed_route_plan(
        FIXTURES / "p_n16_k8_routecap2_transfer1.txt",
        n_customers=instance.n_customers,
    )
    legacy_solution = parse_legacy_scvrp_solutions(FIXTURES / "p_n16_k8_seed1_solution.txt")[0]
    problem = SCVRPProblem(
        problem_id="P-n16-k8-routecap2-transfer1",
        dataset="P",
        best_known=350,
        n_customers=instance.n_customers,
        vehicle_count=instance.vehicle_count,
        capacity=instance.capacity,
        coords=instance.coords,
        demands=instance.demands,
        fixed_routes=fixed_plan.routes,
        fixed_route_capacities=np.asarray(fixed_plan.capacities_free),
    )
    return problem, legacy_solution


def test_archived_seed_one_recomputes_complete_scvrp_state() -> None:
    problem, legacy_solution = _archived_problem_and_solution()

    evaluation = problem.evaluate(
        legacy_solution.routes,
        legacy_solution.transferred_customers,
    )

    assert problem.transfer_cost_once == 26
    assert evaluation.objective == legacy_solution.objective == 350
    assert evaluation.route_cost == 272
    assert evaluation.transfer_cost == 78
    assert evaluation.transferred_demand == 100
    assert evaluation.transfer_vehicle_count == legacy_solution.transfer_vehicle_count == 3
    assert evaluation.route_capacities_free == (7, 35, 12, 4, 5, 35, 35, 1)
    assert evaluation.transfer_capacities_free == (0, 0, 0, 0, 0, 31, 0, 0, 0)
    assert evaluation.legacy_feasible is legacy_solution.feasible is True
    assert evaluation.strict_feasible is True
    assert evaluation.violations == ()


def test_scvrp_solution_encoding_preserves_empty_routes_and_validates_result() -> None:
    problem, legacy_solution = _archived_problem_and_solution()
    encoded = encode_scvrp_solution(
        legacy_solution.routes,
        legacy_solution.transferred_customers,
        n_customers=problem.n_customers,
    )

    decoded_routes, decoded_transfers = decode_scvrp_solution(
        encoded,
        vehicle_count=problem.vehicle_count,
        n_customers=problem.n_customers,
    )
    result = SolveResult(
        problem_id=problem.problem_id,
        solver_id="legacy_scvrp",
        run_seed=legacy_solution.seed,
        best_solution=encoded,
        best_objective=legacy_solution.objective,
        feasible=legacy_solution.feasible,
        evaluation_count=0,
        stop_reason="legacy_fixture",
        runtime=0.0,
    )
    report = problem.validate(result)

    assert decoded_routes == legacy_solution.routes
    assert decoded_routes[5] == ()
    assert decoded_transfers == legacy_solution.transferred_customers
    assert report.is_feasible is True
    assert report.objective_valid is True
    assert report.recomputed_objective == 350
    assert report.metadata["scvrp_state"]["transfer_capacities_free"] == [0, 0, 0, 0, 0, 31, 0, 0, 0]


def test_scvrp_infeasible_result_keeps_raw_objective_and_validates_legacy_score() -> None:
    problem, _ = _archived_problem_and_solution()
    routes = (tuple(range(1, problem.n_customers)),) + ((),) * (problem.vehicle_count - 1)
    evaluation = problem.evaluate(routes, ())

    assert evaluation.legacy_feasible is False
    assert evaluation.objective == evaluation.route_cost + evaluation.transfer_cost
    assert evaluation.legacy_penalty == 100
    assert evaluation.legacy_search_score == evaluation.objective + 100

    encoded = encode_scvrp_solution(routes, (), n_customers=problem.n_customers)
    result = SolveResult(
        problem_id=problem.problem_id,
        solver_id="legacy_scvrp",
        run_seed=1,
        best_solution=encoded,
        best_objective=evaluation.legacy_search_score,
        feasible=False,
        evaluation_count=0,
        stop_reason="legacy_fixture",
        runtime=0.0,
    )
    report = problem.validate(result)

    assert report.is_feasible is False
    assert report.objective_valid is True
    assert report.objective_mismatch is False
    assert report.recomputed_objective == evaluation.legacy_search_score
    assert report.metadata["scvrp_state"]["raw_objective"] == evaluation.objective
    assert report.metadata["scvrp_state"]["legacy_penalty"] == 100
    assert (
        report.metadata["scvrp_state"]["legacy_search_score"]
        == evaluation.legacy_search_score
    )

    wrong_result = replace(result, best_objective=evaluation.objective)
    wrong_report = problem.validate(wrong_result)
    assert wrong_report.objective_valid is False
    assert wrong_report.objective_mismatch is True


def test_scvrp_rejects_duplicate_customer_route_stream() -> None:
    problem, legacy_solution = _archived_problem_and_solution()
    routes = list(legacy_solution.routes)
    routes[0] = routes[0] + (13,)
    encoded = encode_scvrp_solution(
        routes,
        legacy_solution.transferred_customers,
        n_customers=problem.n_customers,
    )

    assert problem.violates_constraints(encoded) is True


def test_scvrp_registry_repository_loads_canonical_yaml(tmp_path: Path) -> None:
    root = tmp_path / "problems"
    path = root / "scvrp" / "SMALL" / "demo.yaml"
    path.parent.mkdir(parents=True)
    path.write_text(
        """
problem_id: demo
dataset: SMALL
problem_type: scvrp
n_customers: 4
vehicle_count: 2
capacity: 4
best_known: 14
coords:
  - [0, 0]
  - [3, 0]
  - [0, 4]
  - [3, 4]
demands: [0, 2, 2, 2]
fixed_routes:
  - [1, 2]
  - [3]
fixed_route_capacities: [4, 4]
""".strip(),
        encoding="utf-8",
    )

    repository = ProblemRepository(root, registry=buildProblemRegistry(problemBuilders()))
    problem = repository.load("SMALL", "demo", "scvrp")

    assert isinstance(problem, SCVRPProblem)
    assert problem.encoding == "scvrp_route_transfer"
    assert problem.direction == "min"
    assert problem.distance_matrix.tolist() == [
        [0, 3, 4, 5],
        [3, 0, 5, 4],
        [4, 5, 0, 3],
        [5, 4, 3, 0],
    ]


def test_scvrp_shared_memory_round_trip_preserves_evaluation() -> None:
    problem, legacy_solution = _archived_problem_and_solution()
    owned_blocks = []
    attached_blocks = []
    try:
        pack = make_scvrp_shm_pack(problem, owned_blocks)
        attached = attach_scvrp_shm_pack(pack, attached_blocks)

        assert attached.evaluate(
            legacy_solution.routes,
            legacy_solution.transferred_customers,
        ) == problem.evaluate(
            legacy_solution.routes,
            legacy_solution.transferred_customers,
        )
    finally:
        for block in attached_blocks:
            block.close()
        for block in owned_blocks:
            block.close()
            block.unlink()
