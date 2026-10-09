"""Artificial Bee Colony (ABC) compatibility implementation.

The first implementation intentionally preserves the book archive's loop
order, array shapes, boundary handling, and legacy NumPy RNG stream.  Do not
optimize these loops until the archive trace tests remain bit-identical.
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
ABC_SOLVER_ID = "abc"
ABC_COMPATIBILITY_PROFILE = "book_archive_abc_v1"


def _array_record(value: Any) -> dict[str, Any]:
    """Convert an intermediate value into the same bit fingerprint as the oracle."""

    array = np.ascontiguousarray(np.asarray(value))
    raw = array.tobytes(order="C")
    record: dict[str, Any] = {
        "shape": list(array.shape),
        "dtype": array.dtype.str,
        "sha256": hashlib.sha256(raw).hexdigest(),
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
class _ABCTrace:
    """Test-only detailed trace; production calls leave it disabled."""

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
class ABCCompatibilityResult:
    """Raw archive-shaped result plus optional process trace."""

    best_score: np.ndarray
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
    trace: _ABCTrace | None,
) -> np.ndarray:
    population = np.zeros([population_size, dimension])
    # 來源程式逐點抽亂數；整批產生會改變後續 RNG 序列，所以保留雙層迴圈。
    for individual_index in range(population_size):
        for dimension_index in range(dimension):
            population[individual_index, dimension_index] = (
                (upper_bounds[dimension_index] - lower_bounds[dimension_index]) * rng.random_sample()
                + lower_bounds[dimension_index]
            )
    if trace is not None:
        trace.record("initialization", result=population)
    return population


def _border_check(
    population: np.ndarray,
    upper_bounds: np.ndarray,
    lower_bounds: np.ndarray,
    population_size: int,
    dimension: int,
    trace: _ABCTrace | None,
) -> np.ndarray:
    for individual_index in range(population_size):
        for dimension_index in range(dimension):
            if population[individual_index, dimension_index] > upper_bounds[dimension_index]:
                population[individual_index, dimension_index] = upper_bounds[dimension_index]
            elif population[individual_index, dimension_index] < lower_bounds[dimension_index]:
                population[individual_index, dimension_index] = lower_bounds[dimension_index]
    if trace is not None:
        trace.record("BorderCheck", result=population)
    return population


def _calculate_fitness(
    population: np.ndarray,
    objective: ObjectiveFn,
    trace: _ABCTrace | None,
) -> np.ndarray:
    population_size = population.shape[0]
    fitness = np.zeros([population_size, 1])
    for individual_index in range(population_size):
        fitness[individual_index] = objective(population[individual_index, :])
    if trace is not None:
        trace.record("CaculateFitness", result=fitness)
    return fitness


def _sort_fitness(fitness: np.ndarray, trace: _ABCTrace | None) -> tuple[np.ndarray, np.ndarray]:
    sorted_fitness = np.sort(fitness, axis=0)
    sorted_indices = np.argsort(fitness, axis=0)
    if trace is not None:
        trace.record("SortFitness", result_0=sorted_fitness, result_1=sorted_indices)
    return sorted_fitness, sorted_indices


def _sort_position(population: np.ndarray, indices: np.ndarray, trace: _ABCTrace | None) -> np.ndarray:
    sorted_population = np.zeros(population.shape)
    for individual_index in range(population.shape[0]):
        sorted_population[individual_index, :] = population[indices[individual_index], :]
    if trace is not None:
        trace.record("SortPosition", result=sorted_population)
    return sorted_population


def _roulette_wheel_selection(
    probabilities: np.ndarray,
    rng: np.random.RandomState,
    trace: _ABCTrace | None,
) -> int:
    cumulative = np.cumsum(probabilities)
    threshold = rng.random_sample() * cumulative[-1]
    selected = 0
    for individual_index in range(probabilities.shape[0]):
        if threshold < cumulative[individual_index]:
            selected = individual_index
            break
    if trace is not None:
        trace.record("RouletteWheelSelection", result=selected)
    return selected


def run_abc_compatibility(
    *,
    population_size: int,
    dimension: int,
    lower_bounds: np.ndarray,
    upper_bounds: np.ndarray,
    max_iterations: int,
    objective: ObjectiveFn,
    seed: int,
    process_trace: bool = False,
) -> ABCCompatibilityResult:
    """Run ABC with the archive's exact control flow and RNG behavior."""

    if population_size <= 1:
        raise ValueError("population_size must be > 1.")
    if dimension <= 0:
        raise ValueError("dimension must be > 0.")
    if max_iterations <= 0:
        raise ValueError("max_iterations must be > 0.")
    lower = np.ascontiguousarray(np.asarray(lower_bounds, dtype=np.float64))
    upper = np.ascontiguousarray(np.asarray(upper_bounds, dtype=np.float64))
    if lower.shape != (dimension,) or upper.shape != (dimension,):
        raise ValueError("lower_bounds and upper_bounds must have shape (dimension,).")
    if np.any(lower >= upper):
        raise ValueError("lower_bounds must be strictly smaller than upper_bounds.")

    # RandomState reproduces np.random.seed/random from the archive.  A local
    # Python RNG is also created now so every solver uses the same dual-RNG contract.
    numpy_rng = np.random.RandomState(int(seed))
    python_rng = random.Random(int(seed))
    trace = _ABCTrace(numpy_rng, python_rng, []) if process_trace else None

    limit = round(0.6 * dimension * population_size)
    counters = np.zeros([population_size, 1])
    onlooker_count = population_size

    population = _initialization(population_size, upper, lower, dimension, numpy_rng, trace)
    fitness = _calculate_fitness(population, objective, trace)
    evaluation_count = population_size
    fitness, sort_indices = _sort_fitness(fitness, trace)
    population = _sort_position(population, sort_indices, trace)
    best_score = copy.copy(fitness[0])
    best_position = np.zeros([1, dimension])
    best_position[0, :] = copy.copy(population[0, :])
    curve = np.zeros([max_iterations, 1])
    new_population = np.zeros([population_size, dimension])
    new_fitness = copy.copy(fitness)

    for iteration in range(max_iterations):
        # Employed-bee phase.
        for individual_index in range(population_size):
            peer_index = numpy_rng.randint(population_size)
            while peer_index == individual_index:
                peer_index = numpy_rng.randint(population_size)
            phi = 2.0 * numpy_rng.random_sample([1, dimension]) - 1.0
            new_population[individual_index, :] = population[individual_index, :] + phi * (
                population[individual_index, :] - population[peer_index, :]
            )
        new_population = _border_check(
            new_population,
            upper,
            lower,
            population_size,
            dimension,
            trace,
        )
        new_fitness = _calculate_fitness(new_population, objective, trace)
        evaluation_count += population_size
        for individual_index in range(population_size):
            if new_fitness[individual_index] < fitness[individual_index]:
                population[individual_index, :] = copy.copy(new_population[individual_index, :])
                fitness[individual_index] = copy.copy(new_fitness[individual_index])
            else:
                counters[individual_index] = counters[individual_index] + 1

        selection_fitness = np.zeros([population_size, 1])
        mean_cost = np.mean(fitness)
        for individual_index in range(population_size):
            selection_fitness[individual_index] = np.exp(-fitness[individual_index] / mean_cost)
        probabilities = selection_fitness / sum(selection_fitness)

        # Onlooker-bee phase.  Preserve the archive behavior where repeated
        # selections overwrite the same row and untouched rows retain old scratch data.
        for _ in range(onlooker_count):
            individual_index = _roulette_wheel_selection(probabilities, numpy_rng, trace)
            peer_index = numpy_rng.randint(population_size)
            while peer_index == individual_index:
                peer_index = numpy_rng.randint(population_size)
            phi = 2.0 * numpy_rng.random_sample([1, dimension]) - 1.0
            new_population[individual_index, :] = population[individual_index, :] + phi * (
                population[individual_index, :] - population[peer_index, :]
            )
        new_population = _border_check(
            new_population,
            upper,
            lower,
            population_size,
            dimension,
            trace,
        )
        new_fitness = _calculate_fitness(new_population, objective, trace)
        evaluation_count += population_size
        for individual_index in range(population_size):
            if new_fitness[individual_index] < fitness[individual_index]:
                population[individual_index, :] = copy.copy(new_population[individual_index, :])
                fitness[individual_index] = copy.copy(new_fitness[individual_index])
            else:
                counters[individual_index] = counters[individual_index] + 1

        # Scout-bee reset.  The source resets C inside the dimension loop; keep it.
        for individual_index in range(population_size):
            if counters[individual_index] >= limit:
                for dimension_index in range(dimension):
                    population[individual_index, dimension_index] = (
                        numpy_rng.random_sample() * (upper[dimension_index] - lower[dimension_index])
                        + lower[dimension_index]
                    )
                    counters[individual_index] = 0

        fitness = _calculate_fitness(population, objective, trace)
        evaluation_count += population_size
        fitness, sort_indices = _sort_fitness(fitness, trace)
        population = _sort_position(population, sort_indices, trace)
        if fitness[0] <= best_score:
            best_score = copy.copy(fitness[0])
            best_position[0, :] = copy.copy(population[0, :])
        curve[iteration] = best_score

    return ABCCompatibilityResult(
        best_score=best_score,
        best_position=best_position,
        curve=curve,
        evaluation_count=evaluation_count,
        trace=tuple(() if trace is None else trace.events),
        numpy_rng_state_sha256=_numpy_rng_state_sha256(numpy_rng),
        python_rng_state_sha256=_python_rng_state_sha256(python_rng),
    )


@dataclass(frozen=True)
class _ABCAdapterConfig:
    """Engine 設定經過嚴格檢查後，ABC 核心真正會用到的參數。"""

    run_seed: int
    max_iterations: int
    population_size: int
    constraint_penalty: float


def _strict_int(value: Any, *, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, np.integer)):
        raise ValueError(f"{name} must be an integer")
    return int(value)


def _parse_adapter_config(config: dict[str, Any]) -> _ABCAdapterConfig:
    """Reject silent defaults because they would break archive reproducibility."""

    if not isinstance(config, dict):
        raise TypeError("config must be a mapping")
    if str(config.get("solver_id", ABC_SOLVER_ID)) != ABC_SOLVER_ID:
        raise ValueError(f"solver_id must be {ABC_SOLVER_ID!r}")
    if "run_seed" not in config:
        raise ValueError("run_seed is required for ABC")
    run_seed = _strict_int(config["run_seed"], name="run_seed")
    if not 0 <= run_seed <= 0xFFFF_FFFF:
        raise ValueError("run_seed must fit in an unsigned 32-bit integer")

    stop_condition = config.get("stop_condition")
    if not isinstance(stop_condition, dict) or stop_condition.get("type") != "max_iterations":
        raise ValueError("ABC requires stop_condition.type=max_iterations")
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
        raise ValueError(f"unsupported ABC params: {unknown}")
    missing = sorted(required_params - set(params))
    if missing:
        raise ValueError(f"missing ABC params: {missing}")
    if params["compatibility_profile"] != ABC_COMPATIBILITY_PROFILE:
        raise ValueError(
            "params.compatibility_profile must be "
            f"{ABC_COMPATIBILITY_PROFILE!r}"
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
    return _ABCAdapterConfig(
        run_seed=run_seed,
        max_iterations=max_iterations,
        population_size=population_size,
        constraint_penalty=constraint_penalty,
    )


@dataclass(frozen=True)
class ABCSolver:
    """Expose the archive-compatible ABC core through the standard Engine API."""

    solver_id: ClassVar[str] = ABC_SOLVER_ID
    execution_backend: ClassVar[str] = "python"

    def solve(
        self,
        problem: Problem,
        config: dict[str, Any],
        rng: np.random.Generator,
    ) -> SolveResult:
        # 壓縮包使用 np.random.seed 所建立的 legacy RandomState 序列；
        # 若改用 Engine 傳入的 default_rng，第一個初始解就會不同。
        del rng
        if not isinstance(problem, ContinuousProblem):
            raise TypeError("ABCSolver only supports ContinuousProblem")
        adapter = _parse_adapter_config(config)

        def archive_objective(candidate: np.ndarray) -> float:
            # 工程題原始 main.py 對不可行解直接回傳 10E32。
            # 無約束 benchmark 在邊界內會直接走下面的原始 objective。
            if problem.violates_constraints(candidate):
                return adapter.constraint_penalty
            return problem.fitness(candidate)

        started = time.perf_counter()
        raw = run_abc_compatibility(
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

        best_solution = np.ascontiguousarray(raw.best_position[0, :], dtype=np.float64).copy()
        best_objective = float(raw.best_score[0])
        feasible = not problem.violates_constraints(best_solution)
        raw_objective = float(problem.fitness(best_solution))
        if feasible and best_objective != raw_objective:
            raise RuntimeError(
                "ABC compatibility score differs from the problem objective for a feasible solution"
            )

        curve_bytes = np.ascontiguousarray(raw.curve).tobytes(order="C")
        return SolveResult(
            problem_id=problem.problem_id,
            solver_id=ABC_SOLVER_ID,
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
                "compatibility_profile": ABC_COMPATIBILITY_PROFILE,
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
