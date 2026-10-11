from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from mkp.engine.bank import ProblemBank, ProblemWorkerView
from mkp.engine.models import ExperimentSpec, SolveResult
from mkp.engine.repository import ProblemRepository
from mkp.problem import CVRPProblem, buildProblemRegistry, problemBuilders
from mkp.problem.cvrp import (
    decode_cvrp_solution,
    encode_cvrp_solution,
    load_legacy_cvrp_problem,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "scvrp"
LEGACY_INSTANCE_ROOT = (
    ROOT / "note" / "study" / "scvrp" / "dataset" / "legacy_sa" / "instances"
)
CVRP_INSTANCES = (
    ("P", "P-n16-k8"),
    ("P", "P-n19-k2"),
    ("P", "P-n23-k8"),
    ("A", "A-n32-k5"),
    ("A", "A-n48-k7"),
    ("A", "A-n64-k9"),
    ("A", "A-n80-k10"),
)
FEASIBLE_ROUTES = (
    (2,),
    (6,),
    (8, 11),
    (4, 10),
    (1, 5),
    (3, 7),
    (12, 14),
    (9, 13, 15),
)


def _repository() -> ProblemRepository:
    return ProblemRepository(
        ROOT / "configs" / "problems",
        registry=buildProblemRegistry(problemBuilders()),
    )


@pytest.mark.parametrize(("dataset", "problem_id"), CVRP_INSTANCES)
def test_cvrp_yaml_and_legacy_instance_build_the_same_problem(
    dataset: str,
    problem_id: str,
) -> None:
    canonical = _repository().load(dataset, problem_id, "cvrp")
    legacy = load_legacy_cvrp_problem(
        LEGACY_INSTANCE_ROOT / dataset / f"{problem_id}.vrp",
        dataset=dataset,
    )

    assert isinstance(canonical, CVRPProblem)
    assert canonical.problem_id == legacy.problem_id == problem_id
    assert canonical.dataset == legacy.dataset == dataset
    assert canonical.best_known == legacy.best_known
    assert canonical.vehicle_count == legacy.vehicle_count
    assert canonical.capacity == legacy.capacity
    np.testing.assert_array_equal(canonical.coords, legacy.coords)
    np.testing.assert_array_equal(canonical.demands, legacy.demands)
    np.testing.assert_array_equal(canonical.distance_matrix, legacy.distance_matrix)


def test_cvrp_encoding_evaluation_and_validation_preserve_complete_routes() -> None:
    problem = _repository().load("P", "P-n16-k8", "cvrp")
    encoded = encode_cvrp_solution(FEASIBLE_ROUTES)
    assert decode_cvrp_solution(
        encoded,
        vehicle_count=problem.vehicle_count,
        n_customers=problem.n_customers,
    ) == FEASIBLE_ROUTES

    evaluation = problem.evaluate(FEASIBLE_ROUTES)
    assert evaluation.feasible is True
    assert evaluation.objective == 555
    assert evaluation.route_loads == (30, 31, 35, 31, 30, 31, 33, 25)
    assert problem.fitness(encoded) == 555

    result = SolveResult(
        problem_id=problem.problem_id,
        solver_id="test",
        run_seed=1,
        best_solution=encoded,
        best_objective=555,
        feasible=True,
        evaluation_count=1,
        stop_reason="done",
        runtime=0.0,
    )
    report = problem.validate(result)
    assert report.is_feasible is True
    assert report.objective_valid is True
    assert report.metadata["cvrp_state"]["routes"] == [
        list(route) for route in FEASIBLE_ROUTES
    ]


def test_cvrp_rejects_capacity_duplicate_and_missing_customer() -> None:
    problem = _repository().load("P", "P-n16-k8", "cvrp")
    capacity_routes = list(FEASIBLE_ROUTES)
    capacity_routes[0] = (2, 6)
    capacity_routes[1] = ()
    assert problem.evaluate(capacity_routes).feasible is False
    assert "route_capacity:0" in problem.evaluate(capacity_routes).violations

    duplicate_routes = list(FEASIBLE_ROUTES)
    duplicate_routes[0] = (2, 2)
    duplicate_routes[1] = ()
    assert problem.evaluate(duplicate_routes).feasible is False
    assert "duplicate_customers" in problem.evaluate(duplicate_routes).violations
    assert "missing_customers:[6]" in problem.evaluate(duplicate_routes).violations


def test_cvrp_shared_memory_round_trip_preserves_objective() -> None:
    registry = buildProblemRegistry(problemBuilders())
    repository = ProblemRepository(ROOT / "configs" / "problems", registry=registry)
    spec = ExperimentSpec(
        experiment_name="cvrp-shared-memory",
        problem_type="cvrp",
        dataset="P",
        problem_ids=("P-n16-k8",),
        solver_ids=("demo",),
        repeat=1,
    )
    bank = ProblemBank.build(repository=repository, spec=spec, registry=registry)
    worker = None
    try:
        worker = ProblemWorkerView(
            bank.export_worker_packs(),
            bank.export_worker_problem_specs(),
        )
        original = bank.get("P", "P-n16-k8", "cvrp")
        attached = worker.get("P", "P-n16-k8", "cvrp")
        encoded = encode_cvrp_solution(FEASIBLE_ROUTES)
        assert attached.fitness(encoded) == original.fitness(encoded) == 555
        assert attached.coords.flags.writeable is False
        assert attached.demands.flags.writeable is False
        assert attached.distance_matrix.flags.writeable is False
    finally:
        if worker is not None:
            for shared in worker._shms:  # noqa: SLF001 - explicit lifecycle check
                shared.close()
        bank.close()
