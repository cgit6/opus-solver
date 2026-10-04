"""SCVRP compatibility model and parsers for the archived CDELS format."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from math import pow, sqrt
from multiprocessing.shared_memory import SharedMemory
from pathlib import Path
import re
from typing import TYPE_CHECKING, Any, Iterable, Literal, cast

import numpy as np

from .interface import Direction, Problem, normalize_best_known
from .registry import ProblemShmPack, ProblemTypeSpec
from .validation import ValidationReport, build_validation_report, objective_values_equal
from .yaml import require_fields, validate_identity

if TYPE_CHECKING:
    from ..engine.models import SolveResult


ROUTE_SEPARATOR = -1
STATE_SEPARATOR = -2
LEGACY_INFEASIBILITY_PENALTY = 100


@dataclass(frozen=True)
class LegacyCVRPInstance:
    """The CVRPLIB fields consumed by the legacy SCVRP executable."""

    name: str
    vehicle_count: int
    cvrp_best_known: int
    capacity: int
    coords: np.ndarray
    demands: np.ndarray

    @property
    def n_customers(self) -> int:
        """Return the depot plus customer count used by the legacy arrays."""
        return int(self.demands.shape[0])


@dataclass(frozen=True)
class LegacyFixedRoutePlan:
    """Fixed transfer routes and their declared free capacities."""

    routes: tuple[tuple[int, ...], ...]
    capacities_free: tuple[int, ...]


@dataclass(frozen=True)
class LegacySCVRPSolution:
    """One deterministic result block emitted by the legacy executable."""

    seed: int
    routes: tuple[tuple[int, ...], ...]
    transferred_customers: tuple[int, ...]
    transfer_vehicle_count: int
    objective: int
    feasible: bool


@dataclass(frozen=True)
class SCVRPEvaluation:
    """Recomputed legacy objective and all state needed for comparison."""

    objective: int
    legacy_penalty: int
    legacy_search_score: int
    route_cost: int
    transfer_cost: int
    transferred_demand: int
    transfer_vehicle_count: int
    route_capacities_free: tuple[int, ...]
    transfer_capacities_free: tuple[int, ...]
    legacy_feasible: bool
    strict_feasible: bool
    violations: tuple[str, ...]


@dataclass(frozen=True, kw_only=True)
class SCVRPProblem(Problem):
    """Legacy SCVRP problem with a complete route-and-transfer encoding."""

    n_customers: int
    vehicle_count: int
    capacity: int
    coords: np.ndarray
    demands: np.ndarray
    fixed_routes: tuple[tuple[int, ...], ...]
    fixed_route_capacities: np.ndarray
    problem_type: str = "scvrp"
    encoding: str = "scvrp_route_transfer"
    direction: Direction = "min"
    distance_matrix: np.ndarray = field(init=False, repr=False)
    fixed_route_for_customer: np.ndarray = field(init=False, repr=False)
    transfer_cost_once: int = field(init=False)

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
        fixed_capacities = np.ascontiguousarray(np.asarray(self.fixed_route_capacities, dtype=np.int64))
        if coords.shape != (self.n_customers, 2):
            raise ValueError("coords shape must be (n_customers, 2).")
        if demands.shape != (self.n_customers,):
            raise ValueError("demands shape must be (n_customers,).")
        if int(demands[0]) != 0 or np.any(demands < 0):
            raise ValueError("demands must be non-negative and depot demand must be 0.")

        fixed_routes = tuple(tuple(int(customer) for customer in route) for route in self.fixed_routes)
        if not fixed_routes:
            raise ValueError("fixed_routes cannot be empty.")
        if fixed_capacities.shape != (len(fixed_routes),):
            raise ValueError("fixed_route_capacities length must equal len(fixed_routes).")
        if np.any(fixed_capacities < 0):
            raise ValueError("fixed_route_capacities must be non-negative.")

        fixed_owner = np.full(self.n_customers, -1, dtype=np.int64)
        for route_index, route in enumerate(fixed_routes):
            for customer in route:
                if customer <= 0 or customer >= self.n_customers:
                    raise ValueError("fixed_routes contain an invalid customer.")
                if fixed_owner[customer] != -1:
                    raise ValueError("fixed_routes must contain every customer exactly once.")
                fixed_owner[customer] = route_index
        if np.any(fixed_owner[1:] == -1):
            raise ValueError("fixed_routes must contain every customer exactly once.")

        distance_matrix = legacy_euc_2d_distance_matrix(coords)
        max_distance = int(np.max(distance_matrix))
        transfer_cost_once = int(max_distance / 2.0 + 0.5)

        coords.setflags(write=False)
        demands.setflags(write=False)
        fixed_capacities.setflags(write=False)
        fixed_owner.setflags(write=False)
        distance_matrix.setflags(write=False)
        object.__setattr__(self, "coords", coords)
        object.__setattr__(self, "demands", demands)
        object.__setattr__(self, "fixed_routes", fixed_routes)
        object.__setattr__(self, "fixed_route_capacities", fixed_capacities)
        object.__setattr__(self, "fixed_route_for_customer", fixed_owner)
        object.__setattr__(self, "distance_matrix", distance_matrix)
        object.__setattr__(self, "transfer_cost_once", transfer_cost_once)
        object.__setattr__(self, "best_known", normalize_best_known(self.best_known, allow_none=True))

    def evaluate(
        self,
        routes: Iterable[Iterable[int]],
        transferred_customers: Iterable[int],
    ) -> SCVRPEvaluation:
        """Recompute the archived C++ objective without running the optimizer."""
        normalized_routes = tuple(tuple(int(customer) for customer in route) for route in routes)
        transferred_sequence = tuple(int(customer) for customer in transferred_customers)
        transferred = set(transferred_sequence)
        structural_violations: list[str] = []
        capacity_violations: list[str] = []

        if len(normalized_routes) != self.vehicle_count:
            structural_violations.append(
                f"route_count:{len(normalized_routes)}!={self.vehicle_count}"
            )
        flattened = [customer for route in normalized_routes for customer in route]
        invalid_customers = sorted(
            {customer for customer in flattened if customer <= 0 or customer >= self.n_customers}
        )
        if invalid_customers:
            structural_violations.append(f"invalid_customers:{invalid_customers}")
        valid_flattened = [customer for customer in flattened if 0 < customer < self.n_customers]
        expected_customers = set(range(1, self.n_customers))
        if len(valid_flattened) != len(set(valid_flattened)):
            structural_violations.append("duplicate_customers")
        missing_customers = sorted(expected_customers - set(valid_flattened))
        if missing_customers:
            structural_violations.append(f"missing_customers:{missing_customers}")
        if len(transferred_sequence) != len(transferred):
            structural_violations.append("duplicate_transferred_customers")
        invalid_transfers = sorted(
            customer for customer in transferred if customer <= 0 or customer >= self.n_customers
        )
        if invalid_transfers:
            structural_violations.append(f"invalid_transferred_customers:{invalid_transfers}")

        route_cost = 0
        route_capacities_free: list[int] = []
        for route_index, route in enumerate(normalized_routes):
            route_load = sum(
                int(self.demands[customer])
                for customer in route
                if 0 < customer < self.n_customers and customer not in transferred
            )
            capacity_free = self.capacity - route_load
            route_capacities_free.append(capacity_free)
            if capacity_free < 0:
                capacity_violations.append(f"route_capacity:{route_index}")

            customer_before = 0
            for customer in route:
                if customer in transferred or customer <= 0 or customer >= self.n_customers:
                    continue
                route_cost += int(self.distance_matrix[customer_before, customer])
                customer_before = customer
            route_cost += int(self.distance_matrix[customer_before, 0])

        valid_transfers = sorted(
            customer for customer in transferred if 0 < customer < self.n_customers
        )
        transfer_capacities_free = self.fixed_route_capacities.astype(np.int64, copy=True)
        for customer in valid_transfers:
            fixed_route = int(self.fixed_route_for_customer[customer])
            transfer_capacities_free[fixed_route] -= int(self.demands[customer])
        fixed_capacity_violations = [
            f"fixed_route_capacity:{index}"
            for index, free in enumerate(transfer_capacities_free.tolist())
            if free < 0
        ]

        transferred_demand = sum(int(self.demands[customer]) for customer in valid_transfers)
        transfer_vehicle_count = (
            (transferred_demand + self.capacity - 1) // self.capacity if transferred_demand else 0
        )
        transfer_cost = transfer_vehicle_count * self.transfer_cost_once
        violations = tuple(structural_violations + capacity_violations + fixed_capacity_violations)
        legacy_feasible = not structural_violations and not capacity_violations
        objective = route_cost + transfer_cost
        legacy_penalty = 0 if legacy_feasible else LEGACY_INFEASIBILITY_PENALTY
        return SCVRPEvaluation(
            objective=objective,
            legacy_penalty=legacy_penalty,
            legacy_search_score=objective + legacy_penalty,
            route_cost=route_cost,
            transfer_cost=transfer_cost,
            transferred_demand=transferred_demand,
            transfer_vehicle_count=transfer_vehicle_count,
            route_capacities_free=tuple(route_capacities_free),
            transfer_capacities_free=tuple(int(value) for value in transfer_capacities_free.tolist()),
            legacy_feasible=legacy_feasible,
            strict_feasible=legacy_feasible and not fixed_capacity_violations,
            violations=violations,
        )

    def fitness(self, solution: np.ndarray) -> int:
        routes, transferred = decode_scvrp_solution(
            solution,
            vehicle_count=self.vehicle_count,
            n_customers=self.n_customers,
        )
        evaluation = self.evaluate(routes, transferred)
        if not evaluation.legacy_feasible:
            raise ValueError("solution violates SCVRP constraints")
        return evaluation.objective

    def violates_constraints(self, solution: np.ndarray) -> bool:
        try:
            routes, transferred = decode_scvrp_solution(
                solution,
                vehicle_count=self.vehicle_count,
                n_customers=self.n_customers,
            )
        except ValueError:
            return True
        return not self.evaluate(routes, transferred).legacy_feasible

    def validate(self, solve_result: "SolveResult") -> ValidationReport:
        solution = np.asarray(solve_result.best_solution)
        try:
            routes, transferred = decode_scvrp_solution(
                solution,
                vehicle_count=self.vehicle_count,
                n_customers=self.n_customers,
            )
            evaluation = self.evaluate(routes, transferred)
            metadata = {
                "scvrp_state": {
                    "routes": [list(route) for route in routes],
                    "transferred_customers": list(transferred),
                    "raw_objective": evaluation.objective,
                    "legacy_penalty": evaluation.legacy_penalty,
                    "legacy_search_score": evaluation.legacy_search_score,
                    "route_cost": evaluation.route_cost,
                    "transfer_cost": evaluation.transfer_cost,
                    "transferred_demand": evaluation.transferred_demand,
                    "transfer_vehicle_count": evaluation.transfer_vehicle_count,
                    "route_capacities_free": list(evaluation.route_capacities_free),
                    "transfer_capacities_free": list(evaluation.transfer_capacities_free),
                    "strict_feasible": evaluation.strict_feasible,
                    "violations": list(evaluation.violations),
                }
            }
        except ValueError as exc:
            metadata = {"scvrp_state": {"decode_error": str(exc)}}
            evaluation = None
        report = build_validation_report(
            self,
            solve_result,
            solution=solution,
            metadata=metadata,
        )
        if evaluation is None:
            return report
        objective_valid = objective_values_equal(
            evaluation.legacy_search_score,
            solve_result.best_objective,
        )
        return replace(
            report,
            objective_valid=objective_valid,
            recomputed_objective=evaluation.legacy_search_score,
            objective_mismatch=not objective_valid,
        )


@dataclass(frozen=True)
class SCVRPProblemShmPack:
    kind: Literal["scvrp"]
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
    fixed_routes: tuple[tuple[int, ...], ...]
    fixed_route_capacities: tuple[int, ...]
    best_known: int | None


def load_scvrp_problem(
    data: dict[str, Any],
    dataset: str,
    problem_id: str,
    file_path: Path,
) -> SCVRPProblem:
    """Load the canonical YAML representation used by the current system."""
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
        "fixed_routes",
        "fixed_route_capacities",
    )
    require_fields(data, required, file_path)
    validate_identity(data, problem_type="scvrp", dataset=dataset, problem_id=problem_id, file_path=file_path)
    try:
        return SCVRPProblem(
            problem_id=str(data["problem_id"]),
            dataset=str(data["dataset"]),
            best_known=data["best_known"],
            n_customers=int(data["n_customers"]),
            vehicle_count=int(data["vehicle_count"]),
            capacity=int(data["capacity"]),
            coords=np.asarray(data["coords"], dtype=np.float64),
            demands=np.asarray(data["demands"], dtype=np.int64),
            fixed_routes=tuple(tuple(int(customer) for customer in route) for route in data["fixed_routes"]),
            fixed_route_capacities=np.asarray(data["fixed_route_capacities"], dtype=np.int64),
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid SCVRP problem data in {file_path}: {exc}") from exc


def load_legacy_scvrp_problem(
    instance_path: Path | str,
    fixed_route_path: Path | str,
    *,
    dataset: str,
    problem_id: str,
    best_known: int | None,
) -> SCVRPProblem:
    """Build a current-system model directly from the two legacy input files."""
    instance = parse_legacy_cvrp_instance(instance_path)
    fixed_plan = parse_legacy_fixed_route_plan(
        fixed_route_path,
        n_customers=instance.n_customers,
    )
    return SCVRPProblem(
        problem_id=problem_id,
        dataset=dataset,
        best_known=best_known,
        n_customers=instance.n_customers,
        vehicle_count=instance.vehicle_count,
        capacity=instance.capacity,
        coords=instance.coords,
        demands=instance.demands,
        fixed_routes=fixed_plan.routes,
        fixed_route_capacities=np.asarray(fixed_plan.capacities_free, dtype=np.int64),
    )


def make_scvrp_shm_pack(model: Problem, shm_blocks: list[SharedMemory]) -> SCVRPProblemShmPack:
    if not isinstance(model, SCVRPProblem):
        raise TypeError(f"make_scvrp_shm_pack expected SCVRPProblem, got {type(model).__name__}")
    coords = np.ascontiguousarray(model.coords, dtype=np.float64)
    demands = np.ascontiguousarray(model.demands, dtype=np.int64)
    distances = np.ascontiguousarray(model.distance_matrix, dtype=np.int64)
    coords_shm = SharedMemory(create=True, size=int(coords.nbytes))
    demands_shm = SharedMemory(create=True, size=int(demands.nbytes))
    distances_shm = SharedMemory(create=True, size=int(distances.nbytes))
    shm_blocks.extend((coords_shm, demands_shm, distances_shm))
    np.ndarray(coords.shape, dtype=np.float64, buffer=coords_shm.buf)[:] = coords
    np.ndarray(demands.shape, dtype=np.int64, buffer=demands_shm.buf)[:] = demands
    np.ndarray(distances.shape, dtype=np.int64, buffer=distances_shm.buf)[:] = distances
    return SCVRPProblemShmPack(
        kind="scvrp",
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
        fixed_routes=model.fixed_routes,
        fixed_route_capacities=tuple(int(value) for value in model.fixed_route_capacities.tolist()),
        best_known=None if model.best_known is None else int(model.best_known),
    )


def attach_scvrp_shm_pack(pack: ProblemShmPack, shm_blocks: list[SharedMemory]) -> SCVRPProblem:
    pack = cast(SCVRPProblemShmPack, pack)
    coords_shm = SharedMemory(name=pack.shm_name_coords)
    demands_shm = SharedMemory(name=pack.shm_name_demands)
    distances_shm = SharedMemory(name=pack.shm_name_distance_matrix)
    shm_blocks.extend((coords_shm, demands_shm, distances_shm))
    coords = np.ndarray(pack.shape_coords, dtype=np.float64, buffer=coords_shm.buf)
    demands = np.ndarray(pack.shape_demands, dtype=np.int64, buffer=demands_shm.buf)
    distances = np.ndarray(pack.shape_distance_matrix, dtype=np.int64, buffer=distances_shm.buf)
    coords.setflags(write=False)
    demands.setflags(write=False)
    distances.setflags(write=False)
    model = SCVRPProblem(
        problem_id=pack.problem_id,
        dataset=pack.dataset,
        best_known=pack.best_known,
        n_customers=pack.n_customers,
        vehicle_count=pack.vehicle_count,
        capacity=pack.capacity,
        coords=coords,
        demands=demands,
        fixed_routes=pack.fixed_routes,
        fixed_route_capacities=np.asarray(pack.fixed_route_capacities, dtype=np.int64),
    )
    object.__setattr__(model, "distance_matrix", distances)
    return model


def scvrpProblemSpec() -> ProblemTypeSpec:
    return ProblemTypeSpec(
        problem_type="scvrp",
        encoding="scvrp_route_transfer",
        direction="min",
        model_type=SCVRPProblem,
        loader=load_scvrp_problem,
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
            "fixed_routes",
            "fixed_route_capacities",
        ),
        make_shm_pack=make_scvrp_shm_pack,
        attach_shm_pack=attach_scvrp_shm_pack,
    )


def legacy_euc_2d_distance_matrix(coords: np.ndarray) -> np.ndarray:
    """Mirror ``int(sqrt(pow(dx, 2) + pow(dy, 2)) + 0.5)``."""
    points = np.asarray(coords, dtype=np.float64)
    if points.ndim != 2 or points.shape[1] != 2:
        raise ValueError("coords must have shape (n_customers, 2).")
    distances = np.zeros((len(points), len(points)), dtype=np.int64)
    for i in range(1, len(points)):
        for j in range(i - 1, -1, -1):
            dx = float(points[i, 0] - points[j, 0])
            dy = float(points[i, 1] - points[j, 1])
            cost = int(sqrt(pow(dx, 2) + pow(dy, 2)) + 0.5)
            distances[i, j] = distances[j, i] = cost
    return distances


def encode_scvrp_solution(
    routes: Iterable[Iterable[int]],
    transferred_customers: Iterable[int],
    *,
    n_customers: int,
) -> np.ndarray:
    """Encode routes, empty routes, and the transfer mask in one int64 array."""
    if n_customers <= 1:
        raise ValueError("n_customers must be > 1")
    tokens: list[int] = []
    for route in routes:
        tokens.extend(int(customer) for customer in route)
        tokens.append(ROUTE_SEPARATOR)
    transferred = {int(customer) for customer in transferred_customers}
    if any(customer <= 0 or customer >= n_customers for customer in transferred):
        raise ValueError("transferred_customers contain an invalid customer")
    mask = [0] * n_customers
    for customer in transferred:
        mask[customer] = 1
    return np.asarray(tokens + [STATE_SEPARATOR] + mask, dtype=np.int64)


def decode_scvrp_solution(
    solution: np.ndarray,
    *,
    vehicle_count: int,
    n_customers: int,
) -> tuple[tuple[tuple[int, ...], ...], tuple[int, ...]]:
    """Decode the canonical array without dropping empty routes or route order."""
    raw = np.asarray(solution)
    if raw.ndim != 1:
        raise ValueError("SCVRP solution must be a 1D array")
    try:
        encoded = raw.astype(np.int64)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("SCVRP solution must contain integers") from exc
    if not np.array_equal(raw, encoded):
        raise ValueError("SCVRP solution must contain integers")
    state_positions = np.flatnonzero(encoded == STATE_SEPARATOR)
    if state_positions.tolist() == [] or len(state_positions) != 1:
        raise ValueError("SCVRP solution must contain exactly one state separator")
    state_position = int(state_positions[0])
    route_tokens = encoded[:state_position].tolist()
    mask = encoded[state_position + 1 :]
    if len(mask) != n_customers or not np.all((mask == 0) | (mask == 1)) or int(mask[0]) != 0:
        raise ValueError("SCVRP solution has an invalid transfer mask")
    if not route_tokens or route_tokens[-1] != ROUTE_SEPARATOR:
        raise ValueError("SCVRP route stream must end with a route separator")

    routes: list[tuple[int, ...]] = []
    route: list[int] = []
    for token in route_tokens:
        if token == ROUTE_SEPARATOR:
            routes.append(tuple(route))
            route = []
        elif token < 0:
            raise ValueError("SCVRP route stream contains an invalid sentinel")
        else:
            route.append(int(token))
    if len(routes) != vehicle_count:
        raise ValueError(f"SCVRP solution has {len(routes)} routes; expected {vehicle_count}")
    transferred = tuple(int(customer) for customer in np.flatnonzero(mask))
    return tuple(routes), transferred


def parse_legacy_cvrp_instance(path: Path | str) -> LegacyCVRPInstance:
    """Parse the strict CVRPLIB subset read by the archived SCVRP source."""
    file_path = Path(path)
    # The archived Augerat files contain harmless trailing spaces on section
    # markers such as ``NODE_COORD_SECTION ``.  Normalize only surrounding
    # whitespace so the parser accepts the original bytes without changing
    # any token or section semantics.
    lines = [line.strip() for line in file_path.read_text(encoding="ascii").splitlines()]
    try:
        coord_start = lines.index("NODE_COORD_SECTION")
        demand_start = lines.index("DEMAND_SECTION")
        depot_start = lines.index("DEPOT_SECTION")
    except ValueError as exc:
        raise ValueError(f"Invalid legacy CVRP instance in {file_path}: missing section") from exc

    header: dict[str, str] = {}
    for line in lines[:coord_start]:
        if ":" in line:
            key, value = line.split(":", 1)
            header[key.strip()] = value.strip()

    required = ("NAME", "COMMENT", "TYPE", "DIMENSION", "EDGE_WEIGHT_TYPE", "CAPACITY")
    missing = [key for key in required if key not in header]
    if missing:
        raise ValueError(f"Invalid legacy CVRP instance in {file_path}: missing {', '.join(missing)}")
    if header["TYPE"] != "CVRP":
        raise ValueError(f"Invalid legacy CVRP instance in {file_path}: TYPE must be CVRP")
    if header["EDGE_WEIGHT_TYPE"] != "EUC_2D":
        raise ValueError(f"Invalid legacy CVRP instance in {file_path}: EDGE_WEIGHT_TYPE must be EUC_2D")

    comment_match = re.search(
        r"No of trucks:\s*(?P<vehicles>\d+)\s*,\s*Optimal value:\s*(?P<best>\d+)",
        header["COMMENT"],
    )
    if comment_match is None:
        raise ValueError(f"Invalid legacy CVRP instance in {file_path}: unsupported COMMENT")

    n_customers = int(header["DIMENSION"])
    coords = _parse_indexed_rows(
        lines[coord_start + 1 : demand_start],
        expected_rows=n_customers,
        value_count=2,
        cast=float,
        section="NODE_COORD_SECTION",
        file_path=file_path,
    )
    demands = _parse_indexed_rows(
        lines[demand_start + 1 : depot_start],
        expected_rows=n_customers,
        value_count=1,
        cast=int,
        section="DEMAND_SECTION",
        file_path=file_path,
    ).reshape(n_customers)

    depot_values = [int(line.strip()) for line in lines[depot_start + 1 :] if line.strip() not in {"", "EOF"}]
    if depot_values != [1, -1]:
        raise ValueError(f"Invalid legacy CVRP instance in {file_path}: only depot 1 is supported")
    if int(demands[0]) != 0:
        raise ValueError(f"Invalid legacy CVRP instance in {file_path}: depot demand must be 0")

    coords = np.ascontiguousarray(coords, dtype=np.float64)
    demands = np.ascontiguousarray(demands, dtype=np.int64)
    coords.setflags(write=False)
    demands.setflags(write=False)
    return LegacyCVRPInstance(
        name=header["NAME"],
        vehicle_count=int(comment_match.group("vehicles")),
        cvrp_best_known=int(comment_match.group("best")),
        capacity=int(header["CAPACITY"]),
        coords=coords,
        demands=demands,
    )


def parse_legacy_fixed_route_plan(
    path: Path | str,
    *,
    n_customers: int,
) -> LegacyFixedRoutePlan:
    """Parse the fixed-route format used by ``fixedroutefile_read``."""
    file_path = Path(path)
    lines = [line.strip() for line in file_path.read_text(encoding="ascii").splitlines() if line.strip()]
    if not lines:
        raise ValueError(f"Invalid legacy fixed-route file in {file_path}: file is empty")

    route_count = int(lines[0])
    if route_count <= 0 or len(lines) != 1 + route_count * 2:
        raise ValueError(f"Invalid legacy fixed-route file in {file_path}: unexpected line count")

    routes: list[tuple[int, ...]] = []
    for route_index, line in enumerate(lines[1 : route_count + 1], start=1):
        values = tuple(int(token) for token in line.split())
        if len(values) < 2 or values[0] != 0 or values[-1] != 0:
            raise ValueError(
                f"Invalid legacy fixed-route file in {file_path}: route {route_index} must start and end at 0"
            )
        route = values[1:-1]
        if any(customer <= 0 or customer >= n_customers for customer in route):
            raise ValueError(
                f"Invalid legacy fixed-route file in {file_path}: route {route_index} has invalid customer"
            )
        routes.append(route)

    flattened = [customer for route in routes for customer in route]
    expected = list(range(1, n_customers))
    if sorted(flattened) != expected:
        raise ValueError(
            f"Invalid legacy fixed-route file in {file_path}: customers must appear exactly once"
        )

    capacities = tuple(int(line) for line in lines[route_count + 1 :])
    if any(capacity < 0 for capacity in capacities):
        raise ValueError(f"Invalid legacy fixed-route file in {file_path}: free capacity must be >= 0")
    return LegacyFixedRoutePlan(routes=tuple(routes), capacities_free=capacities)


def parse_legacy_scvrp_solutions(path: Path | str) -> tuple[LegacySCVRPSolution, ...]:
    """Parse complete solution blocks while deliberately ignoring runtime text."""
    file_path = Path(path)
    text = file_path.read_text(encoding="ascii")
    starts = list(re.finditer(r"(?m)^filename:.*?random seed=,\s*(\d+),\s*$", text))
    if not starts:
        raise ValueError(f"Invalid legacy SCVRP solution file in {file_path}: no result blocks")

    solutions: list[LegacySCVRPSolution] = []
    for index, start in enumerate(starts):
        end = starts[index + 1].start() if index + 1 < len(starts) else len(text)
        block = text[start.start() : end]
        status_match = re.search(r"(?m)^(Feasible|Infeasible) solution\s*$", block)
        objective_match = re.search(r"(?m)^Cost:\s*(-?\d+)\s*$", block)
        transfer_match = re.search(r"(?m)^Transfer Customers:[ \t]*(.*?)[ \t]*$", block)
        transfer_vehicle_match = re.search(r"(?m)^Transfer_Car_Number:\s*(\d+)\s*$", block)
        vehicle_matches = list(re.finditer(r"(?m)^Vehicle #(\d+):[ \t]*([^\r\n]*)$", block))
        if None in (status_match, objective_match, transfer_match, transfer_vehicle_match) or not vehicle_matches:
            raise ValueError(
                f"Invalid legacy SCVRP solution file in {file_path}: incomplete seed {start.group(1)} block"
            )

        vehicle_numbers = [int(match.group(1)) for match in vehicle_matches]
        if vehicle_numbers != list(range(1, len(vehicle_matches) + 1)):
            raise ValueError(
                f"Invalid legacy SCVRP solution file in {file_path}: vehicle numbering is not contiguous"
            )
        routes = tuple(
            tuple(int(token) for token in match.group(2).split())
            for match in vehicle_matches
        )
        transferred_customers = tuple(int(token) for token in transfer_match.group(1).split())
        solutions.append(
            LegacySCVRPSolution(
                seed=int(start.group(1)),
                routes=routes,
                transferred_customers=transferred_customers,
                transfer_vehicle_count=int(transfer_vehicle_match.group(1)),
                objective=int(objective_match.group(1)),
                feasible=status_match.group(1) == "Feasible",
            )
        )
    return tuple(solutions)


def _parse_indexed_rows(
    lines: list[str],
    *,
    expected_rows: int,
    value_count: int,
    cast: type[float] | type[int],
    section: str,
    file_path: Path,
) -> np.ndarray:
    rows: list[list[float | int] | None] = [None] * expected_rows
    for line in lines:
        tokens = line.split()
        if len(tokens) != value_count + 1:
            raise ValueError(f"Invalid {section} in {file_path}: malformed row {line!r}")
        external_id = int(tokens[0])
        internal_id = external_id - 1
        if internal_id < 0 or internal_id >= expected_rows or rows[internal_id] is not None:
            raise ValueError(f"Invalid {section} in {file_path}: invalid or duplicate id {external_id}")
        rows[internal_id] = [cast(token) for token in tokens[1:]]
    if any(row is None for row in rows):
        raise ValueError(f"Invalid {section} in {file_path}: expected {expected_rows} indexed rows")
    return np.asarray(rows)
