"""Capacitated Vehicle Routing Problem model and canonical route encoding."""

from __future__ import annotations

from dataclasses import dataclass
from multiprocessing.shared_memory import SharedMemory
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterable, Literal, cast

import numpy as np

from .interface import Direction, Problem, normalize_best_known
from .registry import ProblemShmPack, ProblemTypeSpec
from .scvrp import legacy_euc_2d_distance_matrix, parse_legacy_cvrp_instance
from .validation import ValidationReport, build_validation_report
from .yaml import require_fields, validate_identity

if TYPE_CHECKING:
    from ..engine.models import SolveResult


ROUTE_SEPARATOR = -1


@dataclass(frozen=True)
class CVRPEvaluation:
    """Objective and constraint state recomputed from a complete route set."""

    objective: int
    route_loads: tuple[int, ...]
    route_capacities_free: tuple[int, ...]
    feasible: bool
    violations: tuple[str, ...]


@dataclass(frozen=True, kw_only=True)
class CVRPProblem(Problem):
    """Classical CVRP: visit every customer once without exceeding capacity."""

    n_customers: int
    vehicle_count: int
    capacity: int
    coords: np.ndarray
    demands: np.ndarray
    problem_type: str = "cvrp"
    encoding: str = "cvrp_routes"
    direction: Direction = "min"
    distance_matrix: np.ndarray | None = None

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.n_customers <= 1:
            raise ValueError("n_customers must be > 1.")
        if self.vehicle_count <= 0:
            raise ValueError("vehicle_count must be > 0.")
        if self.capacity <= 0:
            raise ValueError("capacity must be > 0.")

        coords = np.ascontiguousarray(np.asarray(self.coords, dtype=np.float64))
        demands = np.ascontiguousarray(np.asarray(self.demands, dtype=np.int64))
        if coords.shape != (self.n_customers, 2):
            raise ValueError("coords shape must be (n_customers, 2).")
        if demands.shape != (self.n_customers,):
            raise ValueError("demands shape must be (n_customers,).")
        if int(demands[0]) != 0 or np.any(demands < 0):
            raise ValueError("demands must be non-negative and depot demand must be 0.")
        if np.any(demands[1:] > self.capacity):
            raise ValueError("each customer demand must fit in one vehicle.")

        if self.distance_matrix is None:
            distances = legacy_euc_2d_distance_matrix(coords)
        else:
            distances = np.ascontiguousarray(
                np.asarray(self.distance_matrix, dtype=np.int64)
            )
            if distances.shape != (self.n_customers, self.n_customers):
                raise ValueError(
                    "distance_matrix shape must be (n_customers, n_customers)."
                )
            if not np.all(np.diag(distances) == 0):
                raise ValueError("distance_matrix diagonal must be 0.")
            if not np.array_equal(distances, distances.T):
                raise ValueError("distance_matrix must be symmetric.")

        coords.setflags(write=False)
        demands.setflags(write=False)
        distances.setflags(write=False)
        object.__setattr__(self, "coords", coords)
        object.__setattr__(self, "demands", demands)
        object.__setattr__(self, "distance_matrix", distances)
        object.__setattr__(
            self,
            "best_known",
            normalize_best_known(self.best_known, allow_none=True),
        )

    def evaluate(self, routes: Iterable[Iterable[int]]) -> CVRPEvaluation:
        """Recompute route cost and every CVRP feasibility condition."""

        normalized = tuple(
            tuple(int(customer) for customer in route) for route in routes
        )
        violations: list[str] = []
        if len(normalized) != self.vehicle_count:
            violations.append(f"route_count:{len(normalized)}!={self.vehicle_count}")

        flattened = [customer for route in normalized for customer in route]
        invalid = sorted(
            {customer for customer in flattened if not 0 < customer < self.n_customers}
        )
        if invalid:
            violations.append(f"invalid_customers:{invalid}")
        valid = [customer for customer in flattened if 0 < customer < self.n_customers]
        if len(valid) != len(set(valid)):
            violations.append("duplicate_customers")
        missing = sorted(set(range(1, self.n_customers)) - set(valid))
        if missing:
            violations.append(f"missing_customers:{missing}")

        objective = 0
        route_loads: list[int] = []
        capacities_free: list[int] = []
        distances = cast(np.ndarray, self.distance_matrix)
        for route_index, route in enumerate(normalized):
            route_load = sum(
                int(self.demands[customer])
                for customer in route
                if 0 < customer < self.n_customers
            )
            route_loads.append(route_load)
            capacities_free.append(self.capacity - route_load)
            if route_load > self.capacity:
                violations.append(f"route_capacity:{route_index}")

            previous = 0
            for customer in route:
                if not 0 < customer < self.n_customers:
                    continue
                objective += int(distances[previous, customer])
                previous = customer
            objective += int(distances[previous, 0])

        return CVRPEvaluation(
            objective=objective,
            route_loads=tuple(route_loads),
            route_capacities_free=tuple(capacities_free),
            feasible=not violations,
            violations=tuple(violations),
        )

    def fitness(self, solution: np.ndarray) -> int:
        routes = decode_cvrp_solution(
            solution,
            vehicle_count=self.vehicle_count,
            n_customers=self.n_customers,
        )
        evaluation = self.evaluate(routes)
        if not evaluation.feasible:
            raise ValueError("solution violates CVRP constraints")
        return evaluation.objective

    def violates_constraints(self, solution: np.ndarray) -> bool:
        try:
            routes = decode_cvrp_solution(
                solution,
                vehicle_count=self.vehicle_count,
                n_customers=self.n_customers,
            )
        except ValueError:
            return True
        return not self.evaluate(routes).feasible

    def validate(self, solve_result: "SolveResult") -> ValidationReport:
        solution = np.asarray(solve_result.best_solution)
        try:
            routes = decode_cvrp_solution(
                solution,
                vehicle_count=self.vehicle_count,
                n_customers=self.n_customers,
            )
            evaluation = self.evaluate(routes)
            metadata: dict[str, Any] = {
                "cvrp_state": {
                    "routes": [list(route) for route in routes],
                    "route_loads": list(evaluation.route_loads),
                    "route_capacities_free": list(
                        evaluation.route_capacities_free
                    ),
                    "objective": evaluation.objective,
                    "violations": list(evaluation.violations),
                }
            }
        except ValueError as exc:
            metadata = {"cvrp_state": {"decode_error": str(exc)}}
        return build_validation_report(
            self,
            solve_result,
            solution=solution,
            metadata=metadata,
        )


@dataclass(frozen=True)
class CVRPProblemShmPack:
    kind: Literal["cvrp"]
    problem_type: str
    dataset: str
    problem_id: str
    shm_name_coords: str
    shm_name_demands: str
    shm_name_distance_matrix: str
    shape_coords: tuple[int, int]
    shape_demands: tuple[int, ...]
    shape_distance_matrix: tuple[int, int]
    n_customers: int
    vehicle_count: int
    capacity: int
    best_known: int | None


def load_cvrp_problem(
    data: dict[str, Any],
    dataset: str,
    problem_id: str,
    file_path: Path,
) -> CVRPProblem:
    """Load one canonical CVRP YAML instance."""

    required = (
        "problem_id",
        "dataset",
        "problem_type",
        "n_customers",
        "vehicle_count",
        "capacity",
        "best_known",
        "coords",
        "demands",
    )
    require_fields(data, required, file_path)
    validate_identity(
        data,
        problem_type="cvrp",
        dataset=dataset,
        problem_id=problem_id,
        file_path=file_path,
    )
    try:
        return CVRPProblem(
            problem_id=str(data["problem_id"]),
            dataset=str(data["dataset"]),
            best_known=data["best_known"],
            n_customers=int(data["n_customers"]),
            vehicle_count=int(data["vehicle_count"]),
            capacity=int(data["capacity"]),
            coords=np.asarray(data["coords"], dtype=np.float64),
            demands=np.asarray(data["demands"], dtype=np.int64),
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid CVRP problem data in {file_path}: {exc}") from exc


def load_legacy_cvrp_problem(
    instance_path: Path | str,
    *,
    dataset: str,
) -> CVRPProblem:
    """Load the CVRPLIB subset already used by the archived CDELS sources."""

    instance = parse_legacy_cvrp_instance(instance_path)
    return CVRPProblem(
        problem_id=instance.name,
        dataset=dataset,
        best_known=instance.cvrp_best_known,
        n_customers=instance.n_customers,
        vehicle_count=instance.vehicle_count,
        capacity=instance.capacity,
        coords=instance.coords,
        demands=instance.demands,
    )


def _copy_to_shared_memory(
    array: np.ndarray,
    shm_blocks: list[SharedMemory],
) -> SharedMemory:
    shared = SharedMemory(create=True, size=int(array.nbytes))
    shm_blocks.append(shared)
    np.ndarray(array.shape, dtype=array.dtype, buffer=shared.buf)[:] = array
    return shared


def make_cvrp_shm_pack(
    model: Problem,
    shm_blocks: list[SharedMemory],
) -> CVRPProblemShmPack:
    if not isinstance(model, CVRPProblem):
        raise TypeError(
            f"make_cvrp_shm_pack expected CVRPProblem, got {type(model).__name__}"
        )
    coords = np.ascontiguousarray(model.coords, dtype=np.float64)
    demands = np.ascontiguousarray(model.demands, dtype=np.int64)
    distances = np.ascontiguousarray(model.distance_matrix, dtype=np.int64)
    coords_shm = _copy_to_shared_memory(coords, shm_blocks)
    demands_shm = _copy_to_shared_memory(demands, shm_blocks)
    distances_shm = _copy_to_shared_memory(distances, shm_blocks)
    return CVRPProblemShmPack(
        kind="cvrp",
        problem_type=model.problem_type,
        dataset=model.dataset,
        problem_id=model.problem_id,
        shm_name_coords=coords_shm.name,
        shm_name_demands=demands_shm.name,
        shm_name_distance_matrix=distances_shm.name,
        shape_coords=(int(coords.shape[0]), int(coords.shape[1])),
        shape_demands=(int(demands.shape[0]),),
        shape_distance_matrix=(int(distances.shape[0]), int(distances.shape[1])),
        n_customers=model.n_customers,
        vehicle_count=model.vehicle_count,
        capacity=model.capacity,
        best_known=cast(int | None, model.best_known),
    )


def attach_cvrp_shm_pack(
    pack: ProblemShmPack,
    shm_blocks: list[SharedMemory],
) -> CVRPProblem:
    pack = cast(CVRPProblemShmPack, pack)
    coords_shm = SharedMemory(name=pack.shm_name_coords)
    demands_shm = SharedMemory(name=pack.shm_name_demands)
    distances_shm = SharedMemory(name=pack.shm_name_distance_matrix)
    shm_blocks.extend((coords_shm, demands_shm, distances_shm))
    coords = np.ndarray(pack.shape_coords, dtype=np.float64, buffer=coords_shm.buf)
    demands = np.ndarray(
        pack.shape_demands,
        dtype=np.int64,
        buffer=demands_shm.buf,
    )
    distances = np.ndarray(
        pack.shape_distance_matrix,
        dtype=np.int64,
        buffer=distances_shm.buf,
    )
    return CVRPProblem(
        problem_id=pack.problem_id,
        dataset=pack.dataset,
        best_known=pack.best_known,
        n_customers=pack.n_customers,
        vehicle_count=pack.vehicle_count,
        capacity=pack.capacity,
        coords=coords,
        demands=demands,
        distance_matrix=distances,
    )


def cvrpProblemSpec() -> ProblemTypeSpec:
    return ProblemTypeSpec(
        problem_type="cvrp",
        encoding="cvrp_routes",
        direction="min",
        model_type=CVRPProblem,
        loader=load_cvrp_problem,
        yaml_required_fields=(
            "problem_id",
            "dataset",
            "problem_type",
            "n_customers",
            "vehicle_count",
            "capacity",
            "best_known",
            "coords",
            "demands",
        ),
        make_shm_pack=make_cvrp_shm_pack,
        attach_shm_pack=attach_cvrp_shm_pack,
    )


def encode_cvrp_solution(routes: Iterable[Iterable[int]]) -> np.ndarray:
    """Encode ordered routes, including empty routes, into one integer array."""

    tokens: list[int] = []
    for route in routes:
        tokens.extend(int(customer) for customer in route)
        tokens.append(ROUTE_SEPARATOR)
    if not tokens:
        raise ValueError("routes cannot be empty")
    return np.asarray(tokens, dtype=np.int64)


def decode_cvrp_solution(
    solution: np.ndarray,
    *,
    vehicle_count: int,
    n_customers: int,
) -> tuple[tuple[int, ...], ...]:
    """Decode the canonical route stream without losing empty routes."""

    raw = np.asarray(solution)
    if raw.ndim != 1:
        raise ValueError("CVRP solution must be a 1D array")
    try:
        encoded = raw.astype(np.int64)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("CVRP solution must contain integers") from exc
    if not np.array_equal(raw, encoded):
        raise ValueError("CVRP solution must contain integers")
    if encoded.size == 0 or int(encoded[-1]) != ROUTE_SEPARATOR:
        raise ValueError("CVRP route stream must end with a route separator")

    routes: list[tuple[int, ...]] = []
    route: list[int] = []
    for raw_token in encoded.tolist():
        token = int(raw_token)
        if token == ROUTE_SEPARATOR:
            routes.append(tuple(route))
            route = []
        elif token <= 0 or token >= n_customers:
            raise ValueError("CVRP route stream contains an invalid customer")
        else:
            route.append(token)
    if len(routes) != vehicle_count:
        raise ValueError(
            f"CVRP solution has {len(routes)} routes; expected {vehicle_count}"
        )
    return tuple(routes)
