"""Constraint sets for bounded continuous engineering problems."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np


ContinuousConstraintFn = Callable[[np.ndarray], bool]


@dataclass(frozen=True)
class ContinuousConstraintDefinition:
    """Describe one named feasibility check and its required vector dimension."""

    violates: ContinuousConstraintFn
    required_dimension: int


def pressure_vessel_book_constraints(solution: np.ndarray) -> bool:
    """Preserve the archive formula, including its volume term without length."""

    thickness_shell, thickness_head, radius, length = solution
    constraints = (
        -thickness_shell + 0.0193 * radius,
        -thickness_head + 0.00954 * radius,
        -np.pi * radius**2 - 4.0 * np.pi * radius**3 / 3.0 + 1_296_000.0,
        length - 240.0,
    )
    return any(value > 0.0 for value in constraints)


def three_bar_truss_constraints(solution: np.ndarray) -> bool:
    x1, x2 = solution
    load = 2.0
    stress_limit = 2.0
    denominator = np.sqrt(2.0) * x1**2 + 2.0 * x1 * x2
    constraints = (
        (np.sqrt(2.0) * x1 + x2) * load / denominator - stress_limit,
        x2 * load / denominator - stress_limit,
        load / (np.sqrt(2.0) * x2 + x1) - stress_limit,
    )
    return any(value > 0.0 for value in constraints)


def tension_compression_spring_constraints(solution: np.ndarray) -> bool:
    wire_diameter, mean_coil_diameter, active_coils = solution
    constraints = (
        1.0 - mean_coil_diameter**3 * active_coils / (71_785.0 * wire_diameter**4),
        (4.0 * mean_coil_diameter**2 - wire_diameter * mean_coil_diameter)
        / (12_566.0 * (mean_coil_diameter * wire_diameter**3 - wire_diameter**4))
        + 1.0 / (5_108.0 * wire_diameter**2)
        - 1.0,
        1.0 - 140.45 * wire_diameter / (mean_coil_diameter**2 * active_coils),
        (wire_diameter + mean_coil_diameter) / 1.5 - 1.0,
    )
    return any(value > 0.0 for value in constraints)


CONTINUOUS_CONSTRAINTS: dict[str, ContinuousConstraintDefinition] = {
    "pressure_vessel_book_constraints": ContinuousConstraintDefinition(
        pressure_vessel_book_constraints,
        required_dimension=4,
    ),
    "three_bar_truss_constraints": ContinuousConstraintDefinition(
        three_bar_truss_constraints,
        required_dimension=2,
    ),
    "tension_compression_spring_constraints": ContinuousConstraintDefinition(
        tension_compression_spring_constraints,
        required_dimension=3,
    ),
}


def get_continuous_constraint(constraint_id: str) -> ContinuousConstraintDefinition:
    """Return a registered constraint set or fail with a useful configuration error."""

    try:
        return CONTINUOUS_CONSTRAINTS[constraint_id]
    except KeyError as exc:
        known = ", ".join(sorted(CONTINUOUS_CONSTRAINTS))
        raise ValueError(f"Unknown continuous constraint_id {constraint_id!r}; known values: {known}") from exc
