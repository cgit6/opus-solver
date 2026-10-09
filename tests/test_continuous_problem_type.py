from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from mkp.engine.bank import ProblemBank, ProblemWorkerView, scanProblemCatalog
from mkp.engine.models import ExperimentSpec, SolveResult
from mkp.engine.repository import ProblemRepository
from mkp.problem import ContinuousProblem, buildProblemRegistry, problemBuilders
from mkp.problem.continuous_objectives import get_continuous_objective


def _write_sphere(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        """
problem_id: sphere_2d
dataset: book_examples
problem_type: continuous
dimension: 2
objective_id: sphere
lower_bounds: -10
upper_bounds: 10
best_known: 0
""".strip(),
        encoding="utf-8",
    )


def test_continuous_repository_loads_scalar_bounds_and_zero_best_known(tmp_path: Path) -> None:
    root = tmp_path / "problems"
    _write_sphere(root / "continuous" / "book_examples" / "sphere_2d.yaml")
    registry = buildProblemRegistry(problemBuilders())

    problem = ProblemRepository(root, registry=registry).load(
        "book_examples",
        "sphere_2d",
        "continuous",
    )

    assert isinstance(problem, ContinuousProblem)
    assert problem.encoding == "real_vector"
    assert problem.direction == "min"
    assert problem.best_known == 0
    np.testing.assert_array_equal(problem.lower_bounds, [-10.0, -10.0])
    np.testing.assert_array_equal(problem.upper_bounds, [10.0, 10.0])


def test_continuous_sphere_fitness_constraints_and_validation() -> None:
    problem = ContinuousProblem(
        problem_id="sphere_2d",
        dataset="book_examples",
        best_known=0,
        dimension=2,
        lower_bounds=np.array([-10.0, -10.0]),
        upper_bounds=np.array([10.0, 10.0]),
        objective_id="sphere",
    )
    result = SolveResult(
        problem_id=problem.problem_id,
        solver_id="demo",
        run_seed=1,
        best_solution=np.array([3.0, 4.0]),
        best_objective=25.0,
        feasible=True,
        evaluation_count=1,
        stop_reason="done",
        runtime=0.0,
    )

    assert problem.fitness(np.array([3.0, 4.0])) == 25.0
    assert problem.violates_constraints(np.array([10.0, -10.0])) is False
    assert problem.violates_constraints(np.array([10.01, 0.0])) is True
    assert problem.violates_constraints(np.array([np.nan, 0.0])) is True
    report = problem.validate(result)
    assert report.is_feasible is True
    assert report.objective_valid is True
    assert report.best_known_gap == 25.0


def test_continuous_problem_bank_shared_memory_round_trip(tmp_path: Path) -> None:
    root = tmp_path / "problems"
    _write_sphere(root / "continuous" / "book_examples" / "sphere_2d.yaml")
    registry = buildProblemRegistry(problemBuilders())
    repository = ProblemRepository(root, registry=registry)
    spec = ExperimentSpec(
        experiment_name="continuous-shm",
        problem_type="continuous",
        dataset="book_examples",
        problem_ids=("sphere_2d",),
        solver_ids=("demo",),
        repeat=1,
    )
    bank = ProblemBank.build(repository=repository, spec=spec, registry=registry)
    worker = None
    try:
        worker = ProblemWorkerView(bank.export_worker_packs(), bank.export_worker_problem_specs())
        problem = worker.get("book_examples", "sphere_2d", "continuous")
        assert isinstance(problem, ContinuousProblem)
        assert problem.fitness(np.array([3.0, 4.0])) == 25.0
        assert problem.lower_bounds.flags.writeable is False
        assert problem.upper_bounds.flags.writeable is False
    finally:
        if worker is not None:
            for shm in worker._shms:  # noqa: SLF001 - lifecycle assertion for the worker view
                shm.close()
        bank.close()


@pytest.mark.parametrize(
    ("objective_id", "solution", "expected", "absolute_tolerance"),
    [
        ("sphere", np.zeros(30), 0.0, 1e-12),
        ("f02_schwefel_222", np.zeros(30), 0.0, 1e-12),
        ("f03_schwefel_12", np.zeros(30), 0.0, 1e-12),
        ("f04_schwefel_221", np.zeros(30), 0.0, 1e-12),
        ("f05_rosenbrock", np.ones(30), 0.0, 1e-12),
        ("f06_book_shifted_quadratic", np.full(30, -0.5), 0.0, 1e-12),
        ("f07_weighted_quartic_deterministic", np.zeros(30), 0.0, 1e-12),
        ("f08_schwefel_226", np.full(30, 420.968746), -12569.486618, 1e-5),
        ("f09_rastrigin", np.zeros(30), 0.0, 1e-12),
        ("f10_ackley", np.zeros(30), 0.0, 1e-12),
        ("f11_griewank_corrected", np.zeros(30), 0.0, 1e-12),
        ("f12_penalized_1_corrected", -np.ones(30), 0.0, 1e-12),
        ("f13_penalized_2", np.ones(30), 0.0, 1e-12),
        ("f14_shekel_foxholes", np.array([-32.0, -32.0]), 0.998003838, 1e-9),
        ("f15_kowalik", np.array([0.1928, 0.1908, 0.1231, 0.1358]), 0.000307486, 1e-8),
        ("f16_six_hump_camel", np.array([0.089842, -0.712656]), -1.031628453, 1e-8),
        ("f17_branin", np.array([-np.pi, 12.275]), 0.397887358, 1e-9),
        ("f18_goldstein_price", np.array([0.0, -1.0]), 3.0, 1e-12),
        ("f19_hartmann_3", np.array([0.114614, 0.555649, 0.852547]), -3.862782148, 1e-7),
        (
            "f20_hartmann_6_corrected",
            np.array([0.20169, 0.150011, 0.476874, 0.275332, 0.311652, 0.6573]),
            -3.322368011,
            1e-7,
        ),
        ("f21_shekel_5", np.full(4, 4.0), -10.153195850979039, 1e-12),
        ("f22_shekel_7", np.full(4, 4.0), -10.402818836930305, 1e-12),
        ("f23_shekel_10", np.full(4, 4.0), -10.536283726219605, 1e-12),
    ],
)
def test_book_benchmark_objectives_at_known_points(
    objective_id: str,
    solution: np.ndarray,
    expected: float,
    absolute_tolerance: float,
) -> None:
    actual = get_continuous_objective(objective_id).evaluate(solution)
    assert actual == pytest.approx(expected, abs=absolute_tolerance)


def test_f07_registered_objective_is_reproducible() -> None:
    objective = get_continuous_objective("f07_weighted_quartic_deterministic")
    solution = np.linspace(-1.0, 1.0, 30)

    assert objective.evaluate(solution) == objective.evaluate(solution)


def test_all_book_benchmark_yamls_load() -> None:
    root = Path(__file__).resolve().parents[1] / "configs" / "problems"
    repository = ProblemRepository(root, registry=buildProblemRegistry(problemBuilders()))

    problems = [repository.load("book_benchmarks", f"f{index:02d}", "continuous") for index in range(1, 24)]

    assert len(problems) == 23
    assert all(isinstance(problem, ContinuousProblem) for problem in problems)
    assert [problem.dimension for problem in problems[13:]] == [2, 4, 2, 2, 2, 3, 6, 4, 4, 4]


def test_fixed_dimension_objective_rejects_wrong_dimension() -> None:
    with pytest.raises(ValueError, match="requires dimension=2"):
        ContinuousProblem(
            problem_id="bad-f14",
            dataset="book_benchmarks",
            best_known=None,
            dimension=3,
            lower_bounds=np.full(3, -65.536),
            upper_bounds=np.full(3, 65.536),
            objective_id="f14_shekel_foxholes",
        )


@pytest.mark.parametrize(
    ("problem_id", "feasible_solution", "infeasible_solution", "expected_objective"),
    [
        (
            "pressure_vessel",
            np.array([2.0, 1.0, 100.0, 10.0]),
            np.array([0.0, 0.0, 10.0, 10.0]),
            27088.444,
        ),
        (
            "three_bar_truss",
            np.array([0.7886751346, 0.4082482905]),
            np.array([0.1, 0.1]),
            263.89584338154924,
        ),
        (
            "tension_compression_spring",
            np.array([0.052, 0.36, 11.5]),
            np.array([0.05, 0.25, 2.0]),
            0.01314144,
        ),
    ],
)
def test_book_engineering_objectives_and_constraints(
    problem_id: str,
    feasible_solution: np.ndarray,
    infeasible_solution: np.ndarray,
    expected_objective: float,
) -> None:
    root = Path(__file__).resolve().parents[1] / "configs" / "problems"
    repository = ProblemRepository(root, registry=buildProblemRegistry(problemBuilders()))
    problem = repository.load("book_engineering", problem_id, "continuous")

    assert problem.best_known is None
    assert problem.violates_constraints(feasible_solution) is False
    assert problem.violates_constraints(infeasible_solution) is True
    assert problem.fitness(feasible_solution) == pytest.approx(expected_objective, abs=1e-12)


def test_continuous_catalog_contains_all_27_problem_instances() -> None:
    root = Path(__file__).resolve().parents[1] / "configs" / "problems"
    registry = buildProblemRegistry(problemBuilders())
    repository = ProblemRepository(root, registry=registry)
    entries, _ = scanProblemCatalog(root, registry)
    continuous_entries = [entry for entry in entries if entry.problem_type == "continuous"]

    assert len(continuous_entries) == 27
    assert sum(entry.dataset == "book_benchmarks" for entry in continuous_entries) == 23
    assert sum(entry.dataset == "book_examples" for entry in continuous_entries) == 1
    assert sum(entry.dataset == "book_engineering" for entry in continuous_entries) == 3

    loaded = [
        repository.load(entry.dataset, entry.problem_id, entry.problem_type)
        for entry in continuous_entries
    ]
    assert len(loaded) == 27
    assert all(isinstance(problem, ContinuousProblem) for problem in loaded)


@pytest.mark.parametrize(
    ("dataset", "problem_ids"),
    [
        ("book_benchmarks", tuple(f"f{index:02d}" for index in range(1, 24))),
        ("book_examples", ("sphere_2d",)),
        (
            "book_engineering",
            ("pressure_vessel", "three_bar_truss", "tension_compression_spring"),
        ),
    ],
)
def test_all_continuous_problems_survive_shared_memory_round_trip(
    dataset: str,
    problem_ids: tuple[str, ...],
) -> None:
    root = Path(__file__).resolve().parents[1] / "configs" / "problems"
    registry = buildProblemRegistry(problemBuilders())
    repository = ProblemRepository(root, registry=registry)
    spec = ExperimentSpec(
        experiment_name=f"continuous-shm-{dataset}",
        problem_type="continuous",
        dataset=dataset,
        problem_ids=problem_ids,
        solver_ids=("demo",),
        repeat=1,
    )
    bank = ProblemBank.build(repository=repository, spec=spec, registry=registry)
    worker = None
    try:
        worker = ProblemWorkerView(bank.export_worker_packs(), bank.export_worker_problem_specs())
        for problem_id in problem_ids:
            original = bank.get(dataset, problem_id, "continuous")
            attached = worker.get(dataset, problem_id, "continuous")
            midpoint = (original.lower_bounds + original.upper_bounds) / 2.0
            assert attached.objective_id == original.objective_id
            assert attached.constraint_id == original.constraint_id
            np.testing.assert_array_equal(attached.lower_bounds, original.lower_bounds)
            np.testing.assert_array_equal(attached.upper_bounds, original.upper_bounds)
            assert attached.fitness(midpoint) == original.fitness(midpoint)
    finally:
        if worker is not None:
            for shm in worker._shms:  # noqa: SLF001 - lifecycle assertion for the worker view
                shm.close()
        bank.close()
