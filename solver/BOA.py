"""Butterfly Optimization Algorithm (BOA) archive-compatible core.

The book archive contains two numerically different BOA variants.  This file
keeps both behind explicit compatibility profiles and preserves their original
loop order and dual-RNG behavior.  Engine registration is intentionally added
only after the process trace matches the source oracle.
"""

from __future__ import annotations

import copy
import hashlib
import random
import time
import warnings
from dataclasses import dataclass
from typing import Any, Callable, ClassVar

import numpy as np

from ..engine.models import SolveResult
from ..problem.continuous import ContinuousProblem
from ..problem.interface import Problem


ObjectiveFn = Callable[[np.ndarray], float]
BOA_SOLVER_ID = "boa"


@dataclass(frozen=True)
class BOAProfile:
    switching_probability: float
    power_exponent: float
    sensory_modality: float


BOA_PROFILES: dict[str, BOAProfile] = {
    "book_archive_boa_base_v1": BOAProfile(
        switching_probability=0.8,
        power_exponent=0.1,
        sensory_modality=0.1,
    ),
    "book_archive_boa_spring_v1": BOAProfile(
        switching_probability=0.8,
        power_exponent=0.5,
        sensory_modality=0.001,
    ),
}


def _array_record(value: Any) -> dict[str, Any]:
    """Build the same bit-oriented value record as the source oracle."""

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
class _BOATrace:
    """Detailed compatibility trace used only by tests."""

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
class BOACompatibilityResult:
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
    trace: _BOATrace | None,
) -> np.ndarray:
    population = np.zeros([population_size, dimension])
    # 保留原始雙層迴圈；整批抽樣會改變 RNG 序列。
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


def _border_check(
    population: np.ndarray,
    upper_bounds: np.ndarray,
    lower_bounds: np.ndarray,
    population_size: int,
    dimension: int,
    trace: _BOATrace | None,
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
    trace: _BOATrace | None,
) -> np.ndarray:
    population_size = population.shape[0]
    fitness = np.zeros([population_size, 1])
    for individual_index in range(population_size):
        fitness[individual_index] = objective(population[individual_index, :])
    if trace is not None:
        trace.record("CaculateFitness", result=fitness)
    return fitness


def _legacy_matrix(value: np.ndarray) -> np.matrix:
    """Keep the source's matrix row semantics without emitting modern warnings."""

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", PendingDeprecationWarning)
        return np.matrix(value)


def run_boa_compatibility(
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
) -> BOACompatibilityResult:
    """Run one BOA source profile with the archive's exact control flow."""

    try:
        profile = BOA_PROFILES[compatibility_profile]
    except KeyError as exc:
        raise ValueError(f"unknown BOA compatibility profile: {compatibility_profile!r}") from exc
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

    numpy_rng = np.random.RandomState(int(seed))
    python_rng = random.Random(int(seed))
    trace = _BOATrace(numpy_rng, python_rng, []) if process_trace else None
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
    best_index = np.argmin(fitness)
    # 原始程式沒有 copy；第一代中這會暫時引用 fitness 的那一列。
    best_score = fitness[best_index]
    best_position = np.zeros([1, dimension])
    best_position[0, :] = population[best_index, :]
    new_population = copy.copy(population)
    curve = np.zeros([max_iterations, 1])

    for iteration in range(max_iterations):
        for individual_index in range(population_size):
            fragrance = profile.sensory_modality * (
                fitness[individual_index] ** profile.power_exponent
            )
            if python_rng.random() < profile.switching_probability:
                distance = (
                    python_rng.random()
                    * python_rng.random()
                    * best_position
                    - population[individual_index, :]
                )
                temporary = _legacy_matrix(distance * fragrance)
                new_population[individual_index, :] = (
                    population[individual_index, :] + temporary[0, :]
                )
            else:
                candidates = range(population_size)
                sampled_indices = python_rng.sample(candidates, population_size)
                distance = (
                    python_rng.random()
                    * python_rng.random()
                    * population[sampled_indices[0], :]
                    - population[sampled_indices[1], :]
                )
                temporary = _legacy_matrix(distance * fragrance)
                new_population[individual_index, :] = (
                    population[individual_index, :] + temporary[0, :]
                )

            for dimension_index in range(dimension):
                if new_population[individual_index, dimension_index] > upper[dimension_index]:
                    new_population[individual_index, dimension_index] = upper[dimension_index]
                if new_population[individual_index, dimension_index] < lower[dimension_index]:
                    new_population[individual_index, dimension_index] = lower[dimension_index]

            # 原始程式在改善時會對同一新解再計算一次 objective。
            if evaluated_objective(new_population[individual_index, :]) < fitness[individual_index]:
                population[individual_index, :] = copy.copy(new_population[individual_index, :])
                fitness[individual_index] = copy.copy(
                    evaluated_objective(new_population[individual_index, :])
                )

        population = _border_check(
            population,
            upper,
            lower,
            population_size,
            dimension,
            trace,
        )
        fitness = _calculate_fitness(population, evaluated_objective, trace)
        best_index = np.argmin(fitness)
        if fitness[best_index] <= best_score:
            best_score = copy.copy(fitness[best_index])
            best_position[0, :] = copy.copy(population[best_index, :])
        curve[iteration] = best_score

    return BOACompatibilityResult(
        best_score=best_score,
        best_position=best_position,
        curve=curve,
        evaluation_count=evaluation_count,
        trace=tuple(() if trace is None else trace.events),
        numpy_rng_state_sha256=_numpy_rng_state_sha256(numpy_rng),
        python_rng_state_sha256=_python_rng_state_sha256(python_rng),
    )


@dataclass(frozen=True)
class _BOAAdapterConfig:
    run_seed: int
    max_iterations: int
    compatibility_profile: str
    population_size: int
    constraint_penalty: float


def _strict_int(value: Any, *, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, np.integer)):
        raise ValueError(f"{name} must be an integer")
    return int(value)


def _parse_adapter_config(config: dict[str, Any]) -> _BOAAdapterConfig:
    """Parse every compatibility-sensitive setting without silent defaults."""

    if not isinstance(config, dict):
        raise TypeError("config must be a mapping")
    if str(config.get("solver_id", BOA_SOLVER_ID)) != BOA_SOLVER_ID:
        raise ValueError(f"solver_id must be {BOA_SOLVER_ID!r}")
    if "run_seed" not in config:
        raise ValueError("run_seed is required for BOA")
    run_seed = _strict_int(config["run_seed"], name="run_seed")
    if not 0 <= run_seed <= 0xFFFF_FFFF:
        raise ValueError("run_seed must fit in an unsigned 32-bit integer")

    stop_condition = config.get("stop_condition")
    if not isinstance(stop_condition, dict) or stop_condition.get("type") != "max_iterations":
        raise ValueError("BOA requires stop_condition.type=max_iterations")
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
        raise ValueError(f"unsupported BOA params: {unknown}")
    missing = sorted(required_params - set(params))
    if missing:
        raise ValueError(f"missing BOA params: {missing}")

    compatibility_profile = str(params["compatibility_profile"])
    if compatibility_profile not in BOA_PROFILES:
        raise ValueError(
            "params.compatibility_profile must be one of "
            f"{sorted(BOA_PROFILES)!r}"
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
    return _BOAAdapterConfig(
        run_seed=run_seed,
        max_iterations=max_iterations,
        compatibility_profile=compatibility_profile,
        population_size=population_size,
        constraint_penalty=constraint_penalty,
    )


@dataclass(frozen=True)
class BOASolver:
    """Expose an explicit archive BOA profile through the Engine API."""

    solver_id: ClassVar[str] = BOA_SOLVER_ID
    execution_backend: ClassVar[str] = "python"

    def solve(
        self,
        problem: Problem,
        config: dict[str, Any],
        rng: np.random.Generator,
    ) -> SolveResult:
        # BOA simultaneously uses legacy NumPy RandomState and Python random.
        # Engine's Generator cannot replace either stream without changing results.
        del rng
        if not isinstance(problem, ContinuousProblem):
            raise TypeError("BOASolver only supports ContinuousProblem")
        adapter = _parse_adapter_config(config)

        def archive_objective(candidate: np.ndarray) -> float:
            if problem.violates_constraints(candidate):
                return adapter.constraint_penalty
            return problem.fitness(candidate)

        started = time.perf_counter()
        raw = run_boa_compatibility(
            compatibility_profile=adapter.compatibility_profile,
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
                "BOA compatibility score differs from the problem objective for a feasible solution"
            )

        profile = BOA_PROFILES[adapter.compatibility_profile]
        curve_bytes = np.ascontiguousarray(raw.curve).tobytes(order="C")
        return SolveResult(
            problem_id=problem.problem_id,
            solver_id=BOA_SOLVER_ID,
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
                "compatibility_profile": adapter.compatibility_profile,
                "execution_backend": self.execution_backend,
                "population_size": adapter.population_size,
                "iteration_count": adapter.max_iterations,
                "switching_probability_hex": profile.switching_probability.hex(),
                "power_exponent_hex": profile.power_exponent.hex(),
                "sensory_modality_hex": profile.sensory_modality.hex(),
                "constraint_penalty_hex": adapter.constraint_penalty.hex(),
                "raw_objective": raw_objective,
                "curve_sha256": hashlib.sha256(curve_bytes).hexdigest(),
                "numpy_rng_algorithm": "RandomState-MT19937",
                "numpy_rng_state_sha256": raw.numpy_rng_state_sha256,
                "python_rng_algorithm": "random.Random-MT19937",
                "python_rng_state_sha256": raw.python_rng_state_sha256,
            },
        )
