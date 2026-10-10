"""Grasshopper Optimization Algorithm (GOA) archive-compatible core.

This implementation preserves the book source's nested interaction order,
paired-dimension update, boundary handling, and legacy NumPy RNG stream.  It
is kept separate from the Engine adapter until its detailed trace matches the
read-only source oracle.
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
GOA_SOLVER_ID = "goa"
GOA_COMPATIBILITY_PROFILE = "book_archive_goa_v1"


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
class _GOATrace:
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
class GOACompatibilityResult:
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
    trace: _GOATrace | None,
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


def _border_check(
    population: np.ndarray,
    upper_bounds: np.ndarray,
    lower_bounds: np.ndarray,
    population_size: int,
    dimension: int,
    trace: _GOATrace | None,
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
    trace: _GOATrace | None,
) -> np.ndarray:
    population_size = population.shape[0]
    fitness = np.zeros([population_size, 1])
    for individual_index in range(population_size):
        fitness[individual_index] = objective(population[individual_index, :])
    if trace is not None:
        trace.record("CaculateFitness", result=fitness)
    return fitness


def _sort_fitness(
    fitness: np.ndarray,
    trace: _GOATrace | None,
) -> tuple[np.ndarray, np.ndarray]:
    sorted_fitness = np.sort(fitness, axis=0)
    sorted_indices = np.argsort(fitness, axis=0)
    if trace is not None:
        trace.record("SortFitness", result_0=sorted_fitness, result_1=sorted_indices)
    return sorted_fitness, sorted_indices


def _sort_position(
    population: np.ndarray,
    indices: np.ndarray,
    trace: _GOATrace | None,
) -> np.ndarray:
    sorted_population = np.zeros(population.shape)
    for individual_index in range(population.shape[0]):
        sorted_population[individual_index, :] = population[indices[individual_index], :]
    if trace is not None:
        trace.record("SortPosition", result=sorted_population)
    return sorted_population


def _distance(first: np.ndarray, second: np.ndarray, trace: _GOATrace | None) -> np.floating[Any]:
    result = np.sqrt((first[0] - second[0]) ** 2 + (first[1] - second[1]) ** 2)
    if trace is not None:
        trace.record("distance", result=result)
    return result


def _social_force(distance: np.floating[Any], trace: _GOATrace | None) -> np.floating[Any]:
    attraction = 0.5
    length_scale = 1.5
    result = attraction * np.exp(-distance / length_scale) - np.exp(-distance)
    if trace is not None:
        trace.record("S_func", result=result)
    return result


def run_goa_compatibility(
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
) -> GOACompatibilityResult:
    """Run GOA with the archive's exact numerical flow."""

    if compatibility_profile != GOA_COMPATIBILITY_PROFILE:
        raise ValueError(f"unknown GOA compatibility profile: {compatibility_profile!r}")
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
    trace = _GOATrace(numpy_rng, python_rng, []) if process_trace else None
    evaluation_count = 0

    def evaluated_objective(candidate: np.ndarray) -> float:
        nonlocal evaluation_count
        value = objective(candidate)
        evaluation_count += 1
        if trace is not None:
            trace.record("objective", candidate=candidate, result=value)
        return value

    c_max = 1.0
    c_min = 0.00004
    population = _initialization(
        population_size,
        upper,
        lower,
        dimension,
        numpy_rng,
        trace,
    )
    fitness = _calculate_fitness(population, evaluated_objective, trace)
    fitness, sort_indices = _sort_fitness(fitness, trace)
    population = _sort_position(population, sort_indices, trace)
    best_score = copy.copy(fitness[0])
    best_position = copy.copy(population[0, :])
    curve = np.zeros([max_iterations, 1])
    temporary_positions = np.zeros([population_size, dimension])

    for iteration in range(max_iterations):
        coefficient = c_max - iteration * ((c_max - c_min) / max_iterations)
        for individual_index in range(population_size):
            transposed_population = population.T
            total_social_force = np.zeros([dimension, 1])
            # 原始 GOA 一次只處理兩個維度；奇數維最後一維保持 0。
            for dimension_index in range(0, dimension - 1, 2):
                pair_social_force = np.zeros([2, 1])
                for peer_index in range(population_size):
                    if individual_index != peer_index:
                        pair_distance = _distance(
                            transposed_population[
                                dimension_index : dimension_index + 2,
                                peer_index,
                            ],
                            transposed_population[
                                dimension_index : dimension_index + 2,
                                individual_index,
                            ],
                            trace,
                        )
                        direction_vector = (
                            transposed_population[
                                dimension_index : dimension_index + 2,
                                peer_index,
                            ]
                            - transposed_population[
                                dimension_index : dimension_index + 2,
                                individual_index,
                            ]
                        ) / (pair_distance + 2**-52)
                        normalized_distance = 2 + pair_distance % 2
                        first_force = (
                            (upper[dimension_index] - lower[dimension_index])
                            * coefficient
                            / 2
                        ) * _social_force(normalized_distance, trace) * direction_vector[0]
                        second_force = (
                            (upper[dimension_index + 1] - lower[dimension_index + 1])
                            * coefficient
                            / 2
                        ) * _social_force(normalized_distance, trace) * direction_vector[1]
                        pair_social_force[0, :] = pair_social_force[0, :] + first_force
                        pair_social_force[1, :] = pair_social_force[1, :] + second_force
                total_social_force[
                    dimension_index : dimension_index + 2,
                    :,
                ] = pair_social_force
            new_position = coefficient * total_social_force.T + best_position
            temporary_positions[individual_index, :] = copy.copy(new_position)

        population = _border_check(
            temporary_positions,
            upper,
            lower,
            population_size,
            dimension,
            trace,
        )
        fitness = _calculate_fitness(population, evaluated_objective, trace)
        fitness, sort_indices = _sort_fitness(fitness, trace)
        population = _sort_position(population, sort_indices, trace)
        if fitness[0] <= best_score:
            best_score = copy.copy(fitness[0])
            best_position = copy.copy(population[0, :])
        curve[iteration] = best_score

    return GOACompatibilityResult(
        best_score=best_score,
        best_position=best_position,
        curve=curve,
        evaluation_count=evaluation_count,
        trace=tuple(() if trace is None else trace.events),
        numpy_rng_state_sha256=_numpy_rng_state_sha256(numpy_rng),
        python_rng_state_sha256=_python_rng_state_sha256(python_rng),
    )


@dataclass(frozen=True)
class _GOAAdapterConfig:
    run_seed: int
    max_iterations: int
    population_size: int
    constraint_penalty: float


def _strict_int(value: Any, *, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, np.integer)):
        raise ValueError(f"{name} must be an integer")
    return int(value)


def _parse_adapter_config(config: dict[str, Any]) -> _GOAAdapterConfig:
    """Reject implicit settings that would change the archive execution."""

    if not isinstance(config, dict):
        raise TypeError("config must be a mapping")
    if str(config.get("solver_id", GOA_SOLVER_ID)) != GOA_SOLVER_ID:
        raise ValueError(f"solver_id must be {GOA_SOLVER_ID!r}")
    if "run_seed" not in config:
        raise ValueError("run_seed is required for GOA")
    run_seed = _strict_int(config["run_seed"], name="run_seed")
    if not 0 <= run_seed <= 0xFFFF_FFFF:
        raise ValueError("run_seed must fit in an unsigned 32-bit integer")

    stop_condition = config.get("stop_condition")
    if not isinstance(stop_condition, dict) or stop_condition.get("type") != "max_iterations":
        raise ValueError("GOA requires stop_condition.type=max_iterations")
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
        raise ValueError(f"unsupported GOA params: {unknown}")
    missing = sorted(required_params - set(params))
    if missing:
        raise ValueError(f"missing GOA params: {missing}")
    if params["compatibility_profile"] != GOA_COMPATIBILITY_PROFILE:
        raise ValueError(
            "params.compatibility_profile must be "
            f"{GOA_COMPATIBILITY_PROFILE!r}"
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
    return _GOAAdapterConfig(
        run_seed=run_seed,
        max_iterations=max_iterations,
        population_size=population_size,
        constraint_penalty=constraint_penalty,
    )


@dataclass(frozen=True)
class GOASolver:
    """Expose the archive-compatible GOA core through the Engine API."""

    solver_id: ClassVar[str] = GOA_SOLVER_ID
    execution_backend: ClassVar[str] = "python"

    def solve(
        self,
        problem: Problem,
        config: dict[str, Any],
        rng: np.random.Generator,
    ) -> SolveResult:
        # The archive uses np.random.seed/random (RandomState), not Generator.
        del rng
        if not isinstance(problem, ContinuousProblem):
            raise TypeError("GOASolver only supports ContinuousProblem")
        adapter = _parse_adapter_config(config)

        def archive_objective(candidate: np.ndarray) -> float:
            if problem.violates_constraints(candidate):
                return adapter.constraint_penalty
            return problem.fitness(candidate)

        started = time.perf_counter()
        raw = run_goa_compatibility(
            compatibility_profile=GOA_COMPATIBILITY_PROFILE,
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

        best_solution = np.ascontiguousarray(raw.best_position, dtype=np.float64).copy()
        best_objective = float(raw.best_score[0])
        feasible = not problem.violates_constraints(best_solution)
        raw_objective = float(problem.fitness(best_solution))
        if feasible and best_objective != raw_objective:
            raise RuntimeError(
                "GOA compatibility score differs from the problem objective for a feasible solution"
            )

        curve_bytes = np.ascontiguousarray(raw.curve).tobytes(order="C")
        return SolveResult(
            problem_id=problem.problem_id,
            solver_id=GOA_SOLVER_ID,
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
                "compatibility_profile": GOA_COMPATIBILITY_PROFILE,
                "execution_backend": self.execution_backend,
                "population_size": adapter.population_size,
                "iteration_count": adapter.max_iterations,
                "c_max_hex": float(1.0).hex(),
                "c_min_hex": float(0.00004).hex(),
                "constraint_penalty_hex": adapter.constraint_penalty.hex(),
                "raw_objective": raw_objective,
                "curve_sha256": hashlib.sha256(curve_bytes).hexdigest(),
                "numpy_rng_algorithm": "RandomState-MT19937",
                "numpy_rng_state_sha256": raw.numpy_rng_state_sha256,
                "python_rng_algorithm": "random.Random-MT19937",
                "python_rng_state_sha256": raw.python_rng_state_sha256,
            },
        )
