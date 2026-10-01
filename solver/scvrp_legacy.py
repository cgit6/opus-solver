"""Incremental compatibility port of the archived SCVRP CDELS-SA solver."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json

import numpy as np

from ..problem.scvrp import SCVRPEvaluation, SCVRPProblem
from ..rng.msvc_legacy import MsvcLegacyRand


LEGACY_F = 0.7
LEGACY_CR = 0.7
LEGACY_PENALTY = 100


@dataclass
class LegacySCVRPIndividual:
    """Mutable Python representation of the legacy ``Individual`` struct."""

    routes: list[list[int]]
    positions: np.ndarray
    transfer_mask: np.ndarray
    cost: int = 0
    feasible: bool = False
    route_capacities_free: tuple[int, ...] = ()
    transfer_capacities_free: tuple[int, ...] = ()
    transfer_vehicle_count: int = 0
    transfer_total_capacity_free: int = 0

    def canonical_dict(self) -> dict[str, object]:
        return {
            "routes": [list(route) for route in self.routes],
            "transfer_mask": [int(value) for value in self.transfer_mask.tolist()],
            "cost": self.cost,
            "feasible": self.feasible,
            "route_capacities_free": list(self.route_capacities_free),
            "transfer_capacities_free": list(self.transfer_capacities_free),
            "transfer_vehicle_count": self.transfer_vehicle_count,
            "transfer_total_capacity_free": self.transfer_total_capacity_free,
        }


@dataclass
class LegacySCVRPGeneration:
    individuals: list[LegacySCVRPIndividual]
    best_index: int
    feasible_solutions: int
    generation_id: int

    @property
    def best(self) -> LegacySCVRPIndividual:
        return self.individuals[self.best_index]


@dataclass(frozen=True)
class LegacySCVRPTrace:
    stage: str
    generation_id: int
    population_sha256: str
    population_size: int
    best_index: int
    best_cost: int
    feasible_solutions: int
    rng_state: int
    rng_draw_count: int


class LegacySCVRPCore:
    """Compatibility core built in independently testable legacy stages."""

    def __init__(self, problem: SCVRPProblem, *, seed: int) -> None:
        self.problem = problem
        self.seed = int(seed)
        self.rng = MsvcLegacyRand(self.seed)
        self.population_size = 3 * problem.n_customers
        self._next_generation_id = 1

    def initialize_population(self) -> LegacySCVRPGeneration:
        """Port ``initial_population`` and its two legacy route constructors."""
        individuals: list[LegacySCVRPIndividual] = []
        best_index = 0
        feasible_solutions = 0
        for population_index in range(self.population_size):
            top_to_down = self.rng.rand_mod(2) == 1
            individual = self._generate_individual(top_to_down=top_to_down)
            individuals.append(individual)
            if individual.feasible:
                feasible_solutions += 1
                if population_index > 0 and individual.cost < individuals[best_index].cost:
                    best_index = population_index

        generation = LegacySCVRPGeneration(
            individuals=individuals,
            best_index=best_index,
            feasible_solutions=feasible_solutions,
            generation_id=self._take_generation_id(),
        )
        return generation

    def trace_generation(self, generation: LegacySCVRPGeneration, *, stage: str) -> LegacySCVRPTrace:
        payload = json.dumps(
            [individual.canonical_dict() for individual in generation.individuals],
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("ascii")
        return LegacySCVRPTrace(
            stage=stage,
            generation_id=generation.generation_id,
            population_sha256=sha256(payload).hexdigest(),
            population_size=len(generation.individuals),
            best_index=generation.best_index,
            best_cost=generation.best.cost,
            feasible_solutions=generation.feasible_solutions,
            rng_state=self.rng.state,
            rng_draw_count=self.rng.draw_count,
        )

    def _take_generation_id(self) -> int:
        generation_id = self._next_generation_id
        self._next_generation_id += 1
        return generation_id

    def _generate_individual(self, *, top_to_down: bool) -> LegacySCVRPIndividual:
        n_customers = self.problem.n_customers
        checked = np.zeros(n_customers, dtype=np.bool_)
        routed = np.zeros(n_customers, dtype=np.bool_)
        checked[0] = True
        routed[0] = True
        routes: list[list[int]] = [[] for _ in range(self.problem.vehicle_count)]
        checked_count = 1
        routed_count = 1
        route_order = (
            range(self.problem.vehicle_count)
            if top_to_down
            else range(self.problem.vehicle_count - 1, -1, -1)
        )
        last_route_index = 0

        for route_index in route_order:
            last_route_index = route_index
            route_load = 0
            while checked_count < n_customers:
                while True:
                    customer = self.rng.rand_mod(n_customers - 1) + 1
                    if not checked[customer]:
                        break
                load = int(self.problem.demands[customer])
                route_load += load
                if route_load < self.problem.capacity:
                    routes[route_index].append(customer)
                    routed[customer] = True
                    routed_count += 1
                else:
                    route_load -= load
                checked[customer] = True
                checked_count += 1

            checked_count = 1
            for customer in range(1, n_customers):
                if routed[customer]:
                    checked[customer] = True
                    checked_count += 1
                else:
                    checked[customer] = False

            if routed_count == n_customers:
                break

        if routed_count != n_customers:
            for customer in range(1, n_customers):
                if not routed[customer]:
                    routes[last_route_index].append(customer)

        transfer_mask = np.zeros(n_customers, dtype=np.int64)
        positions = _build_positions(routes, n_customers=n_customers)
        individual = LegacySCVRPIndividual(
            routes=routes,
            positions=positions,
            transfer_mask=transfer_mask,
        )
        self._reevaluate(individual)
        return individual

    def _reevaluate(self, individual: LegacySCVRPIndividual) -> SCVRPEvaluation:
        transferred = tuple(int(customer) for customer in np.flatnonzero(individual.transfer_mask))
        evaluation = self.problem.evaluate(individual.routes, transferred)
        individual.cost = evaluation.objective + (0 if evaluation.legacy_feasible else LEGACY_PENALTY)
        individual.feasible = evaluation.legacy_feasible
        individual.route_capacities_free = evaluation.route_capacities_free
        individual.transfer_capacities_free = evaluation.transfer_capacities_free
        individual.transfer_vehicle_count = evaluation.transfer_vehicle_count
        individual.transfer_total_capacity_free = (
            evaluation.transfer_vehicle_count * self.problem.capacity - evaluation.transferred_demand
        )
        return evaluation


def _build_positions(routes: list[list[int]], *, n_customers: int) -> np.ndarray:
    positions = np.zeros((2, n_customers), dtype=np.int64)
    for route_index, route in enumerate(routes):
        for position, customer in enumerate(route):
            positions[0, customer] = route_index
            positions[1, customer] = position
    return positions
