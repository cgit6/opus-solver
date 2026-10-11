"""Teaching-Learning-Based Optimization (TLBO) archive-compatible core.

The implementation preserves the chapter 10 source's scalar population mean,
teacher and learner update order, accepted in-place replacements, and its
independent NumPy and Python legacy RNG streams.  Engine integration is
deferred until the detailed execution trace matches the read-only oracle.
"""

from __future__ import annotations

import copy
import hashlib
import random
import time
from dataclasses import dataclass
from typing import Any, Callable, ClassVar

import numpy as np

from ..engine.models import SolveResult
from ..problem.continuous import ContinuousProblem
from ..problem.interface import Problem


ObjectiveFn = Callable[[np.ndarray], float]
TLBO_SOLVER_ID = "tlbo"
TLBO_COMPATIBILITY_PROFILE = "book_archive_tlbo_v1"


def _array_record(value: Any) -> dict[str, Any]:
    array = np.ascontiguousarray(np.asarray(value))
    record: dict[str, Any] = {
        "shape": list(array.shape),
        "dtype": array.dtype.str,
        "sha256": hashlib.sha256(array.tobytes(order="C")).hexdigest(),
    }
    if array.dtype.kind == "f" and array.size <= 32:
        record["float_hex"] = [float(item).hex() for item in array.reshape(-1)]
    elif array.dtype.kind in "iu" and array.size <= 32:
        record["values"] = [int(item) for item in array.reshape(-1)]
    return record


def _numpy_rng_state_sha256(rng: np.random.RandomState) -> str:
    algorithm, keys, position, has_gauss, cached_gaussian = rng.get_state()
    digest = hashlib.sha256()
    digest.update(algorithm.encode("ascii"))
    digest.update(np.ascontiguousarray(keys).tobytes())
    digest.update(str(position).encode("ascii"))
    digest.update(str(has_gauss).encode("ascii"))
    digest.update(float(cached_gaussian).hex().encode("ascii"))
    return digest.hexdigest()


def _python_rng_state_sha256(rng: random.Random) -> str:
    return hashlib.sha256(repr(rng.getstate()).encode("ascii")).hexdigest()


@dataclass
class _TLBOTrace:
    numpy_rng: np.random.RandomState
    python_rng: random.Random
    events: list[dict[str, Any]]

    def record(self, name: str, **values: Any) -> None:
        self.events.append(
            {
                "name": name,
                "values": {key: _array_record(value) for key, value in values.items()},
                "numpy_rng_state_sha256": _numpy_rng_state_sha256(self.numpy_rng),
                "python_rng_state_sha256": _python_rng_state_sha256(self.python_rng),
            }
        )


@dataclass(frozen=True)
class TLBOCompatibilityResult:
    best_score: np.ndarray | np.floating[Any]
    best_position: np.ndarray
    curve: np.ndarray
    evaluation_count: int
    trace: tuple[dict[str, Any], ...]
    numpy_rng_state_sha256: str
    python_rng_state_sha256: str


def _initialization(
    population_size: int,
    upper_bounds: np.ndarray,
    lower_bounds: np.ndarray,
    dimension: int,
    rng: np.random.RandomState,
    trace: _TLBOTrace | None,
) -> np.ndarray:
    population = np.zeros([population_size, dimension])
    for individual_index in range(population_size):
        for dimension_index in range(dimension):
            population[individual_index, dimension_index] = (
                (upper_bounds[dimension_index] - lower_bounds[dimension_index])
                * rng.random_sample()
                + lower_bounds[dimension_index]
            )
    if trace is not None:
        trace.record("initialization", result=population)
    return population


def _calculate_fitness(
    population: np.ndarray,
    objective: ObjectiveFn,
    trace: _TLBOTrace | None,
) -> np.ndarray:
    population_size = population.shape[0]
    fitness = np.zeros([population_size, 1])
    for individual_index in range(population_size):
        fitness[individual_index] = objective(population[individual_index, :])
    if trace is not None:
        trace.record("CaculateFitness", result=fitness)
    return fitness


def run_tlbo_compatibility(
    *,
    compatibility_profile: str,
    population_size: int,
    dimension: int,
    lower_bounds: np.ndarray,
    upper_bounds: np.ndarray,
    max_iterations: int,
    objective: ObjectiveFn,
    seed: int,
    process_trace: bool = False,
) -> TLBOCompatibilityResult:
    """Run TLBO with the archived implementation's exact numerical flow."""

    if compatibility_profile != TLBO_COMPATIBILITY_PROFILE:
        raise ValueError(f"unknown TLBO compatibility profile: {compatibility_profile!r}")
    if population_size <= 0:
        raise ValueError("population_size must be > 0.")
    # 原書從 0..dimension-1 選學習對象；dimension=1 時 i=0 會無限迴圈。
    if dimension <= 1:
        raise ValueError("dimension must be > 1 for the archive TLBO profile.")
    if max_iterations <= 0:
        raise ValueError("max_iterations must be > 0.")
    lower = np.ascontiguousarray(np.asarray(lower_bounds, dtype=np.float64))
    upper = np.ascontiguousarray(np.asarray(upper_bounds, dtype=np.float64))
    if lower.shape != (dimension,) or upper.shape != (dimension,):
        raise ValueError("lower_bounds and upper_bounds must have shape (dimension,).")
    if np.any(lower >= upper):
        raise ValueError("lower_bounds must be strictly smaller than upper_bounds.")

    numpy_rng = np.random.RandomState(int(seed))
    python_rng = random.Random(int(seed))
    trace = _TLBOTrace(numpy_rng, python_rng, []) if process_trace else None
    evaluation_count = 0

    def evaluated_objective(candidate: np.ndarray) -> float:
        nonlocal evaluation_count
        value = objective(candidate)
        evaluation_count += 1
        if trace is not None:
            trace.record("objective", candidate=candidate, result=value)
        return value

    population = _initialization(
        population_size,
        upper,
        lower,
        dimension,
        numpy_rng,
        trace,
    )
    fitness = _calculate_fitness(population, evaluated_objective, trace)
    best_score = np.min(fitness)
    best_index = np.argmin(fitness)
    best_position = np.zeros([1, dimension])
    best_position[0, :] = copy.copy(population[best_index, :])
    curve = np.zeros([max_iterations, 1])

    for iteration in range(max_iterations):
        for individual_index in range(population_size):
            # 教階段：原書對整個矩陣取單一平均值，不是逐維平均。
            population_mean = np.mean(population)
            best_index = np.argmin(fitness)
            teacher = copy.copy(population[best_index, :])
            teaching_factor = python_rng.randint(0, 1)
            candidate = population[individual_index, :] + numpy_rng.random_sample(
                dimension
            ) * (teacher - teaching_factor * population_mean)
            for dimension_index in range(dimension):
                if candidate[dimension_index] > upper[dimension_index]:
                    candidate[dimension_index] = upper[dimension_index]
                if candidate[dimension_index] < lower[dimension_index]:
                    candidate[dimension_index] = lower[dimension_index]
            candidate_fitness = evaluated_objective(candidate)
            if candidate_fitness < fitness[individual_index]:
                population[individual_index, :] = copy.copy(candidate)
                fitness[individual_index] = copy.copy(candidate_fitness)

            # 學階段：刻意保留原書以 dimension 而非 population_size
            # 作為 randint 上限的行為。
            peer_index = python_rng.randint(0, dimension - 1)
            while individual_index == peer_index:
                peer_index = python_rng.randint(0, dimension - 1)
            if fitness[individual_index] < fitness[peer_index]:
                candidate = population[individual_index, :] + numpy_rng.random_sample(
                    dimension
                ) * (
                    population[individual_index, :] - population[peer_index, :]
                )
            else:
                candidate = population[individual_index, :] - numpy_rng.random_sample(
                    dimension
                ) * (
                    population[individual_index, :] - population[peer_index, :]
                )
            for dimension_index in range(dimension):
                if candidate[dimension_index] > upper[dimension_index]:
                    candidate[dimension_index] = upper[dimension_index]
                if candidate[dimension_index] < lower[dimension_index]:
                    candidate[dimension_index] = lower[dimension_index]
            candidate_fitness = evaluated_objective(candidate)
            if candidate_fitness < fitness[individual_index]:
                population[individual_index, :] = copy.copy(candidate)
                fitness[individual_index] = candidate_fitness

        fitness = _calculate_fitness(population, evaluated_objective, trace)
        best_index = np.argmin(fitness)
        if fitness[best_index] <= best_score:
            best_score = copy.copy(fitness[best_index])
            best_position[0, :] = copy.copy(population[best_index, :])
        curve[iteration] = best_score

    return TLBOCompatibilityResult(
        best_score=best_score,
        best_position=best_position,
        curve=curve,
        evaluation_count=evaluation_count,
        trace=tuple(() if trace is None else trace.events),
        numpy_rng_state_sha256=_numpy_rng_state_sha256(numpy_rng),
        python_rng_state_sha256=_python_rng_state_sha256(python_rng),
    )


@dataclass(frozen=True)
class _TLBOAdapterConfig:
    run_seed: int
    max_iterations: int
    population_size: int
    constraint_penalty: float


def _strict_int(value: Any, *, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, np.integer)):
        raise ValueError(f"{name} must be an integer")
    return int(value)


def _parse_adapter_config(config: dict[str, Any]) -> _TLBOAdapterConfig:
    """Reject settings that would silently change archive compatibility."""

    if not isinstance(config, dict):
        raise TypeError("config must be a mapping")
    if str(config.get("solver_id", TLBO_SOLVER_ID)) != TLBO_SOLVER_ID:
        raise ValueError(f"solver_id must be {TLBO_SOLVER_ID!r}")
    if "run_seed" not in config:
        raise ValueError("run_seed is required for TLBO")
    run_seed = _strict_int(config["run_seed"], name="run_seed")
    if not 0 <= run_seed <= 0xFFFF_FFFF:
        raise ValueError("run_seed must fit in an unsigned 32-bit integer")

    stop_condition = config.get("stop_condition")
    if not isinstance(stop_condition, dict) or stop_condition.get("type") != "max_iterations":
        raise ValueError("TLBO requires stop_condition.type=max_iterations")
    max_iterations = _strict_int(
        stop_condition.get("max_iterations"),
        name="stop_condition.max_iterations",
    )
    if max_iterations <= 0:
        raise ValueError("stop_condition.max_iterations must be > 0")

    params = config.get("params")
    if not isinstance(params, dict):
        raise ValueError("params must be a mapping")
    required_params = {
        "compatibility_profile",
        "population_size",
        "constraint_penalty",
    }
    unknown = sorted(set(params) - required_params)
    if unknown:
        raise ValueError(f"unsupported TLBO params: {unknown}")
    missing = sorted(required_params - set(params))
    if missing:
        raise ValueError(f"missing TLBO params: {missing}")
    if params["compatibility_profile"] != TLBO_COMPATIBILITY_PROFILE:
        raise ValueError(
            "params.compatibility_profile must be "
            f"{TLBO_COMPATIBILITY_PROFILE!r}"
        )
    population_size = _strict_int(params["population_size"], name="params.population_size")
    if population_size <= 1:
        raise ValueError("params.population_size must be > 1")
    penalty_value = params["constraint_penalty"]
    if isinstance(penalty_value, bool) or not isinstance(
        penalty_value,
        (int, float, np.integer, np.floating),
    ):
        raise ValueError("params.constraint_penalty must be numeric")
    constraint_penalty = float(penalty_value)
    if not np.isfinite(constraint_penalty) or constraint_penalty <= 0.0:
        raise ValueError("params.constraint_penalty must be finite and > 0")
    return _TLBOAdapterConfig(
        run_seed=run_seed,
        max_iterations=max_iterations,
        population_size=population_size,
        constraint_penalty=constraint_penalty,
    )


@dataclass(frozen=True)
class TLBOSolver:
    """Convert Engine inputs and outputs around the compatible TLBO core."""

    solver_id: ClassVar[str] = TLBO_SOLVER_ID
    execution_backend: ClassVar[str] = "python"

    def solve(
        self,
        problem: Problem,
        config: dict[str, Any],
        rng: np.random.Generator,
    ) -> SolveResult:
        # 原書同時使用 RandomState 與 random.Random；不可改用 Engine Generator。
        del rng
        if not isinstance(problem, ContinuousProblem):
            raise TypeError("TLBOSolver only supports ContinuousProblem")
        if problem.dimension <= 1:
            raise ValueError(
                "TLBOSolver requires dimension > 1 because the archive learner loop hangs in one dimension"
            )
        adapter = _parse_adapter_config(config)

        def archive_objective(candidate: np.ndarray) -> float:
            if problem.violates_constraints(candidate):
                return adapter.constraint_penalty
            return problem.fitness(candidate)

        started = time.perf_counter()
        raw = run_tlbo_compatibility(
            compatibility_profile=TLBO_COMPATIBILITY_PROFILE,
            population_size=adapter.population_size,
            dimension=problem.dimension,
            lower_bounds=problem.lower_bounds,
            upper_bounds=problem.upper_bounds,
            max_iterations=adapter.max_iterations,
            objective=archive_objective,
            seed=adapter.run_seed,
            process_trace=False,
        )
        runtime = time.perf_counter() - started

        best_solution = np.ascontiguousarray(
            raw.best_position[0, :],
            dtype=np.float64,
        ).copy()
        best_objective = float(np.asarray(raw.best_score).reshape(-1)[0])
        feasible = not problem.violates_constraints(best_solution)
        raw_objective = float(problem.fitness(best_solution))
        if feasible and best_objective != raw_objective:
            raise RuntimeError(
                "TLBO compatibility score differs from the problem objective for a feasible solution"
            )

        curve_bytes = np.ascontiguousarray(raw.curve).tobytes(order="C")
        return SolveResult(
            problem_id=problem.problem_id,
            solver_id=TLBO_SOLVER_ID,
            run_seed=adapter.run_seed,
            best_solution=best_solution,
            best_objective=best_objective,
            feasible=feasible,
            evaluation_count=raw.evaluation_count,
            stop_reason="max_iterations_reached",
            runtime=runtime,
            linprog_runtime=0.0,
            error=None,
            metadata={
                "compatibility_profile": TLBO_COMPATIBILITY_PROFILE,
                "execution_backend": self.execution_backend,
                "population_size": adapter.population_size,
                "iteration_count": adapter.max_iterations,
                "constraint_penalty_hex": adapter.constraint_penalty.hex(),
                "raw_objective": raw_objective,
                "curve_sha256": hashlib.sha256(curve_bytes).hexdigest(),
                "numpy_rng_algorithm": "RandomState-MT19937",
                "numpy_rng_state_sha256": raw.numpy_rng_state_sha256,
                "python_rng_algorithm": "random.Random-MT19937",
                "python_rng_state_sha256": raw.python_rng_state_sha256,
            },
        )
