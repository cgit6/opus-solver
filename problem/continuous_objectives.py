"""Deterministic objective functions for real-valued optimization problems."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np


ContinuousObjectiveFn = Callable[[np.ndarray], float]


@dataclass(frozen=True)
class ContinuousObjectiveDefinition:
    """Describe one objective and any fixed dimension required by its formula."""

    evaluate: ContinuousObjectiveFn
    required_dimension: int | None = None
    minimum_dimension: int = 1


def sphere(solution: np.ndarray) -> float:
    """Sphere objective: the sum of the squared decision variables."""

    return float(np.sum(solution * solution))


def schwefel_222(solution: np.ndarray) -> float:
    absolute = np.abs(solution)
    return float(np.sum(absolute) + np.prod(absolute))


def schwefel_12(solution: np.ndarray) -> float:
    # Preserve the archive's prefix-sum evaluation order for float-level parity.
    result = 0.0
    for index in range(solution.size):
        result += float(np.sum(solution[: index + 1]) ** 2)
    return result


def schwefel_221(solution: np.ndarray) -> float:
    return float(np.max(np.abs(solution)))


def rosenbrock(solution: np.ndarray) -> float:
    return float(np.sum(100.0 * (solution[1:] - solution[:-1] ** 2) ** 2 + (solution[:-1] - 1.0) ** 2))


def book_shifted_quadratic(solution: np.ndarray) -> float:
    """The archive's F6 formula; unlike the usual Step function it has no floor()."""

    return float(np.sum(np.abs(solution + 0.5) ** 2))


def weighted_quartic(solution: np.ndarray) -> float:
    """Deterministic part of archive F7; the original adds unseeded uniform noise."""

    weights = np.arange(1, solution.size + 1, dtype=np.float64)
    return float(np.sum(weights * solution**4))


def schwefel_226(solution: np.ndarray) -> float:
    return float(np.sum(-solution * np.sin(np.sqrt(np.abs(solution)))))


def rastrigin(solution: np.ndarray) -> float:
    return float(np.sum(solution**2 - 10.0 * np.cos(2.0 * np.pi * solution)) + 10.0 * solution.size)


def ackley(solution: np.ndarray) -> float:
    dimension = solution.size
    return float(
        -20.0 * np.exp(-0.2 * np.sqrt(np.sum(solution**2) / dimension))
        - np.exp(np.sum(np.cos(2.0 * np.pi * solution)) / dimension)
        + 20.0
        + np.e
    )


def griewank(solution: np.ndarray) -> float:
    """Corrected archive F11: every variable needs a matching 1-based divisor."""

    divisors = np.sqrt(np.arange(1, solution.size + 1, dtype=np.float64))
    return float(np.sum(solution**2) / 4000.0 - np.prod(np.cos(solution / divisors)) + 1.0)


def _penalty_u(solution: np.ndarray, a: float, k: float, m: int) -> np.ndarray:
    return k * np.maximum(solution - a, 0.0) ** m + k * np.maximum(-solution - a, 0.0) ** m


def penalized_1(solution: np.ndarray) -> float:
    """Corrected archive F12, summing paired terms instead of returning a vector."""

    y = 1.0 + (solution + 1.0) / 4.0
    middle = np.sum((y[:-1] - 1.0) ** 2 * (1.0 + 10.0 * np.sin(np.pi * y[1:]) ** 2))
    main = 10.0 * np.sin(np.pi * y[0]) ** 2 + middle + (y[-1] - 1.0) ** 2
    return float(np.pi / solution.size * main + np.sum(_penalty_u(solution, 10.0, 100.0, 4)))


def penalized_2(solution: np.ndarray) -> float:
    middle = np.sum(
        (solution[:-1] - 1.0) ** 2 * (1.0 + np.sin(3.0 * np.pi * solution[1:]) ** 2)
    )
    main = (
        np.sin(3.0 * np.pi * solution[0]) ** 2
        + middle
        + (solution[-1] - 1.0) ** 2 * (1.0 + np.sin(2.0 * np.pi * solution[-1]) ** 2)
    )
    return float(0.1 * main + np.sum(_penalty_u(solution, 5.0, 100.0, 4)))


_FOXHOLES_POINTS = np.array(
    [
        [-32, -16, 0, 16, 32, -32, -16, 0, 16, 32, -32, -16, 0, 16, 32, -32, -16, 0, 16, 32, -32, -16, 0, 16, 32],
        [-32, -32, -32, -32, -32, -16, -16, -16, -16, -16, 0, 0, 0, 0, 0, 16, 16, 16, 16, 16, 32, 32, 32, 32, 32],
    ],
    dtype=np.float64,
)


def shekel_foxholes(solution: np.ndarray) -> float:
    distances = np.sum((solution[:, None] - _FOXHOLES_POINTS) ** 6, axis=0)
    indices = np.arange(1, 26, dtype=np.float64)
    return float((1.0 / 500.0 + np.sum(1.0 / (indices + distances))) ** -1)


_KOWALIK_A = np.array(
    [0.1957, 0.1947, 0.1735, 0.16, 0.0844, 0.0627, 0.0456, 0.0342, 0.0323, 0.0235, 0.0246],
    dtype=np.float64,
)
_KOWALIK_B = 1.0 / np.array([0.25, 0.5, 1, 2, 4, 6, 8, 10, 12, 14, 16], dtype=np.float64)


def kowalik(solution: np.ndarray) -> float:
    numerator = solution[0] * (_KOWALIK_B**2 + solution[1] * _KOWALIK_B)
    denominator = _KOWALIK_B**2 + solution[2] * _KOWALIK_B + solution[3]
    return float(np.sum((_KOWALIK_A - numerator / denominator) ** 2))


def six_hump_camel(solution: np.ndarray) -> float:
    x1, x2 = solution
    return float(4.0 * x1**2 - 2.1 * x1**4 + x1**6 / 3.0 + x1 * x2 - 4.0 * x2**2 + 4.0 * x2**4)


def branin(solution: np.ndarray) -> float:
    x1, x2 = solution
    return float(
        (x2 - 5.1 * x1**2 / (4.0 * np.pi**2) + 5.0 * x1 / np.pi - 6.0) ** 2
        + 10.0 * (1.0 - 1.0 / (8.0 * np.pi)) * np.cos(x1)
        + 10.0
    )


def goldstein_price(solution: np.ndarray) -> float:
    x1, x2 = solution
    first = 1.0 + (x1 + x2 + 1.0) ** 2 * (
        19.0 - 14.0 * x1 + 3.0 * x1**2 - 14.0 * x2 + 6.0 * x1 * x2 + 3.0 * x2**2
    )
    second = 30.0 + (2.0 * x1 - 3.0 * x2) ** 2 * (
        18.0 - 32.0 * x1 + 12.0 * x1**2 + 48.0 * x2 - 36.0 * x1 * x2 + 27.0 * x2**2
    )
    return float(first * second)


_HARTMANN_3_A = np.array(
    [[3, 10, 30], [0.1, 10, 35], [3, 10, 30], [0.1, 10, 35]],
    dtype=np.float64,
)
_HARTMANN_3_P = np.array(
    [[0.3689, 0.117, 0.2673], [0.4699, 0.4387, 0.747], [0.1091, 0.8732, 0.5547], [0.03815, 0.5743, 0.8828]],
    dtype=np.float64,
)
_HARTMANN_C = np.array([1, 1.2, 3, 3.2], dtype=np.float64)


def hartmann_3(solution: np.ndarray) -> float:
    exponents = -np.sum(_HARTMANN_3_A * (solution[None, :] - _HARTMANN_3_P) ** 2, axis=1)
    return float(-np.sum(_HARTMANN_C * np.exp(exponents)))


_HARTMANN_6_A = np.array(
    [
        [10, 3, 17, 3.5, 1.7, 8],
        [0.05, 10, 17, 0.1, 8, 14],
        [3, 3.5, 1.7, 10, 17, 8],
        [17, 8, 0.05, 10, 0.1, 14],
    ],
    dtype=np.float64,
)
_HARTMANN_6_P = np.array(
    [
        [0.1312, 0.1696, 0.5569, 0.0124, 0.8283, 0.5886],
        [0.2329, 0.4135, 0.8307, 0.3736, 0.1004, 0.9991],
        # The archive has 0.1415 here; Hartmann-6 uses 0.1451.
        [0.2348, 0.1451, 0.3522, 0.2883, 0.3047, 0.665],
        [0.4047, 0.8828, 0.8732, 0.5743, 0.1091, 0.0381],
    ],
    dtype=np.float64,
)


def hartmann_6(solution: np.ndarray) -> float:
    exponents = -np.sum(_HARTMANN_6_A * (solution[None, :] - _HARTMANN_6_P) ** 2, axis=1)
    return float(-np.sum(_HARTMANN_C * np.exp(exponents)))


_SHEKEL_A = np.array(
    [
        [4, 4, 4, 4],
        [1, 1, 1, 1],
        [8, 8, 8, 8],
        [6, 6, 6, 6],
        [3, 7, 3, 7],
        [2, 9, 2, 9],
        [5, 5, 3, 3],
        [8, 1, 8, 1],
        [6, 2, 6, 2],
        [7, 3.6, 7, 3.6],
    ],
    dtype=np.float64,
)
_SHEKEL_C = np.array([0.1, 0.2, 0.2, 0.4, 0.4, 0.6, 0.3, 0.7, 0.5, 0.5], dtype=np.float64)


def _shekel(solution: np.ndarray, terms: int) -> float:
    # Preserve the archive's sequential subtraction order for float-level parity.
    result = 0.0
    for index in range(terms):
        squared_distance = np.dot(solution - _SHEKEL_A[index], solution - _SHEKEL_A[index])
        result -= float((squared_distance + _SHEKEL_C[index]) ** -1)
    return result


def shekel_5(solution: np.ndarray) -> float:
    return _shekel(solution, 5)


def shekel_7(solution: np.ndarray) -> float:
    return _shekel(solution, 7)


def shekel_10(solution: np.ndarray) -> float:
    return _shekel(solution, 10)


def pressure_vessel_cost(solution: np.ndarray) -> float:
    thickness_shell, thickness_head, radius, length = solution
    return float(
        0.6224 * thickness_shell * radius * length
        + 1.7781 * thickness_head * radius**2
        + 3.1661 * thickness_shell**2 * length
        + 19.84 * thickness_shell**2 * radius
    )


def three_bar_truss_weight(solution: np.ndarray) -> float:
    x1, x2 = solution
    return float((2.0 * np.sqrt(2.0) * x1 + x2) * 100.0)


def tension_compression_spring_weight(solution: np.ndarray) -> float:
    wire_diameter, mean_coil_diameter, active_coils = solution
    return float((active_coils + 2.0) * mean_coil_diameter * wire_diameter**2)


CONTINUOUS_OBJECTIVES: dict[str, ContinuousObjectiveDefinition] = {
    "sphere": ContinuousObjectiveDefinition(sphere),
    "f02_schwefel_222": ContinuousObjectiveDefinition(schwefel_222),
    "f03_schwefel_12": ContinuousObjectiveDefinition(schwefel_12),
    "f04_schwefel_221": ContinuousObjectiveDefinition(schwefel_221),
    "f05_rosenbrock": ContinuousObjectiveDefinition(rosenbrock, minimum_dimension=2),
    "f06_book_shifted_quadratic": ContinuousObjectiveDefinition(book_shifted_quadratic),
    "f07_weighted_quartic_deterministic": ContinuousObjectiveDefinition(weighted_quartic),
    "f08_schwefel_226": ContinuousObjectiveDefinition(schwefel_226),
    "f09_rastrigin": ContinuousObjectiveDefinition(rastrigin),
    "f10_ackley": ContinuousObjectiveDefinition(ackley),
    "f11_griewank_corrected": ContinuousObjectiveDefinition(griewank),
    "f12_penalized_1_corrected": ContinuousObjectiveDefinition(penalized_1),
    "f13_penalized_2": ContinuousObjectiveDefinition(penalized_2),
    "f14_shekel_foxholes": ContinuousObjectiveDefinition(shekel_foxholes, required_dimension=2),
    "f15_kowalik": ContinuousObjectiveDefinition(kowalik, required_dimension=4),
    "f16_six_hump_camel": ContinuousObjectiveDefinition(six_hump_camel, required_dimension=2),
    "f17_branin": ContinuousObjectiveDefinition(branin, required_dimension=2),
    "f18_goldstein_price": ContinuousObjectiveDefinition(goldstein_price, required_dimension=2),
    "f19_hartmann_3": ContinuousObjectiveDefinition(hartmann_3, required_dimension=3),
    "f20_hartmann_6_corrected": ContinuousObjectiveDefinition(hartmann_6, required_dimension=6),
    "f21_shekel_5": ContinuousObjectiveDefinition(shekel_5, required_dimension=4),
    "f22_shekel_7": ContinuousObjectiveDefinition(shekel_7, required_dimension=4),
    "f23_shekel_10": ContinuousObjectiveDefinition(shekel_10, required_dimension=4),
    "pressure_vessel_cost": ContinuousObjectiveDefinition(pressure_vessel_cost, required_dimension=4),
    "three_bar_truss_weight": ContinuousObjectiveDefinition(three_bar_truss_weight, required_dimension=2),
    "tension_compression_spring_weight": ContinuousObjectiveDefinition(
        tension_compression_spring_weight,
        required_dimension=3,
    ),
}


def get_continuous_objective(objective_id: str) -> ContinuousObjectiveDefinition:
    """Return a registered objective or fail with a useful configuration error."""

    try:
        return CONTINUOUS_OBJECTIVES[objective_id]
    except KeyError as exc:
        known = ", ".join(sorted(CONTINUOUS_OBJECTIVES))
        raise ValueError(f"Unknown continuous objective_id {objective_id!r}; known values: {known}") from exc
