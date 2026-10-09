"""Continuous real-vector problem model and YAML/shared-memory adapters."""

from __future__ import annotations

from dataclasses import dataclass
from multiprocessing.shared_memory import SharedMemory
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, cast

import numpy as np

from .continuous_constraints import get_continuous_constraint
from .continuous_objectives import get_continuous_objective
from .interface import Direction, Problem
from .registry import ProblemShmPack, ProblemTypeSpec
from .validation import ValidationReport, build_validation_report, normalize_scalar_objective
from .yaml import require_fields, validate_identity

if TYPE_CHECKING:
    from ..engine.models import SolveResult


def _as_bound_array(name: str, value: Any, dimension: int) -> np.ndarray:
    """Expand a scalar bound or validate a per-dimension bound vector."""

    array = np.asarray(value, dtype=np.float64)
    if array.ndim == 0:
        array = np.full(dimension, float(array), dtype=np.float64)
    elif array.shape == (dimension,):
        array = np.ascontiguousarray(array, dtype=np.float64)
    else:
        raise ValueError(f"{name} must be a scalar or a vector with length dimension.")
    if not np.all(np.isfinite(array)):
        raise ValueError(f"{name} must contain only finite numbers.")
    return array


def _normalize_continuous_best_known(value: Any) -> int | float | None:
    """Continuous minima may legitimately be zero or negative."""

    if value is None:
        return None
    normalized = normalize_scalar_objective(value, name="best_known")
    if not np.isfinite(float(normalized)):
        raise ValueError("best_known must be finite when present.")
    return normalized


@dataclass(frozen=True, kw_only=True)
class ContinuousProblem(Problem):
    """A bounded real vector evaluated by a named deterministic objective."""

    dimension: int
    lower_bounds: np.ndarray
    upper_bounds: np.ndarray
    objective_id: str
    constraint_id: str | None = None
    problem_type: str = "continuous"
    encoding: str = "real_vector"
    direction: Direction = "min"

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.dimension <= 0:
            raise ValueError("dimension must be > 0.")
        if not self.objective_id.strip():
            raise ValueError("objective_id cannot be empty.")
        objective = get_continuous_objective(self.objective_id)
        if objective.required_dimension is not None and self.dimension != objective.required_dimension:
            raise ValueError(
                f"objective_id={self.objective_id!r} requires dimension={objective.required_dimension}, "
                f"got {self.dimension}."
            )
        if self.dimension < objective.minimum_dimension:
            raise ValueError(
                f"objective_id={self.objective_id!r} requires dimension >= {objective.minimum_dimension}, "
                f"got {self.dimension}."
            )
        if self.constraint_id is not None:
            constraint = get_continuous_constraint(self.constraint_id)
            if self.dimension != constraint.required_dimension:
                raise ValueError(
                    f"constraint_id={self.constraint_id!r} requires dimension={constraint.required_dimension}, "
                    f"got {self.dimension}."
                )

        lower = _as_bound_array("lower_bounds", self.lower_bounds, self.dimension)
        upper = _as_bound_array("upper_bounds", self.upper_bounds, self.dimension)
        if np.any(lower >= upper):
            raise ValueError("lower_bounds must be strictly smaller than upper_bounds.")
        lower.setflags(write=False)
        upper.setflags(write=False)
        object.__setattr__(self, "lower_bounds", lower)
        object.__setattr__(self, "upper_bounds", upper)
        object.__setattr__(self, "best_known", _normalize_continuous_best_known(self.best_known))

    def _solution_array(self, solution: np.ndarray) -> np.ndarray:
        candidate = np.asarray(solution, dtype=np.float64)
        if candidate.shape != (self.dimension,):
            raise ValueError(f"solution shape must be ({self.dimension},).")
        if not np.all(np.isfinite(candidate)):
            raise ValueError("solution must contain only finite numbers.")
        return candidate

    def fitness(self, solution: np.ndarray) -> float:
        candidate = self._solution_array(solution)
        value = float(get_continuous_objective(self.objective_id).evaluate(candidate))
        if not np.isfinite(value):
            raise ValueError(f"objective_id={self.objective_id!r} returned a non-finite value.")
        return value

    def violates_constraints(self, solution: np.ndarray) -> bool:
        try:
            candidate = self._solution_array(solution)
        except ValueError:
            return True
        if np.any(candidate < self.lower_bounds) or np.any(candidate > self.upper_bounds):
            return True
        if self.constraint_id is None:
            return False
        return bool(get_continuous_constraint(self.constraint_id).violates(candidate))

    def validate(self, solve_result: "SolveResult") -> ValidationReport:
        solution = np.asarray(solve_result.best_solution, dtype=np.float64)
        return build_validation_report(self, solve_result, solution=solution)


@dataclass(frozen=True)
class ContinuousProblemShmPack:
    kind: Literal["continuous"]
    problem_type: str
    dataset: str
    problem_id: str
    shm_name_lower_bounds: str
    shm_name_upper_bounds: str
    shape_bounds: tuple[int, ...]
    dimension: int
    objective_id: str
    constraint_id: str | None
    best_known: int | float | None


def load_continuous_problem(
    data: dict[str, Any],
    dataset: str,
    problem_id: str,
    file_path: Path,
) -> ContinuousProblem:
    required = (
        "problem_id",
        "dataset",
        "problem_type",
        "dimension",
        "objective_id",
        "lower_bounds",
        "upper_bounds",
        "best_known",
    )
    require_fields(data, required, file_path)
    validate_identity(data, problem_type="continuous", dataset=dataset, problem_id=problem_id, file_path=file_path)
    try:
        return ContinuousProblem(
            problem_id=str(data["problem_id"]),
            dataset=str(data["dataset"]),
            best_known=data["best_known"],
            dimension=int(data["dimension"]),
            lower_bounds=np.asarray(data["lower_bounds"], dtype=np.float64),
            upper_bounds=np.asarray(data["upper_bounds"], dtype=np.float64),
            objective_id=str(data["objective_id"]),
            constraint_id=None if data.get("constraint_id") is None else str(data["constraint_id"]),
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid continuous problem data in {file_path}: {exc}") from exc


def make_continuous_shm_pack(
    model: Problem,
    shm_blocks: list[SharedMemory],
) -> ContinuousProblemShmPack:
    if not isinstance(model, ContinuousProblem):
        raise TypeError(f"make_continuous_shm_pack expected ContinuousProblem, got {type(model).__name__}")
    lower = np.ascontiguousarray(model.lower_bounds, dtype=np.float64)
    upper = np.ascontiguousarray(model.upper_bounds, dtype=np.float64)
    lower_shm = SharedMemory(create=True, size=int(lower.nbytes))
    upper_shm = SharedMemory(create=True, size=int(upper.nbytes))
    shm_blocks.extend((lower_shm, upper_shm))
    np.ndarray(lower.shape, dtype=np.float64, buffer=lower_shm.buf)[:] = lower
    np.ndarray(upper.shape, dtype=np.float64, buffer=upper_shm.buf)[:] = upper
    return ContinuousProblemShmPack(
        kind="continuous",
        problem_type=model.problem_type,
        dataset=model.dataset,
        problem_id=model.problem_id,
        shm_name_lower_bounds=lower_shm.name,
        shm_name_upper_bounds=upper_shm.name,
        shape_bounds=(model.dimension,),
        dimension=model.dimension,
        objective_id=model.objective_id,
        constraint_id=model.constraint_id,
        best_known=model.best_known,
    )


def attach_continuous_shm_pack(
    pack: ProblemShmPack,
    shm_blocks: list[SharedMemory],
) -> ContinuousProblem:
    pack = cast(ContinuousProblemShmPack, pack)
    lower_shm = SharedMemory(name=pack.shm_name_lower_bounds)
    upper_shm = SharedMemory(name=pack.shm_name_upper_bounds)
    shm_blocks.extend((lower_shm, upper_shm))
    lower = np.ndarray(pack.shape_bounds, dtype=np.float64, buffer=lower_shm.buf)
    upper = np.ndarray(pack.shape_bounds, dtype=np.float64, buffer=upper_shm.buf)
    lower.setflags(write=False)
    upper.setflags(write=False)
    return ContinuousProblem(
        problem_id=pack.problem_id,
        dataset=pack.dataset,
        best_known=pack.best_known,
        dimension=pack.dimension,
        lower_bounds=lower,
        upper_bounds=upper,
        objective_id=pack.objective_id,
        constraint_id=pack.constraint_id,
    )


def continuousProblemSpec() -> ProblemTypeSpec:
    return ProblemTypeSpec(
        problem_type="continuous",
        encoding="real_vector",
        direction="min",
        model_type=ContinuousProblem,
        loader=load_continuous_problem,
        yaml_required_fields=(
            "problem_id",
            "dataset",
            "problem_type",
            "dimension",
            "objective_id",
            "lower_bounds",
            "upper_bounds",
            "best_known",
        ),
        make_shm_pack=make_continuous_shm_pack,
        attach_shm_pack=attach_continuous_shm_pack,
    )
