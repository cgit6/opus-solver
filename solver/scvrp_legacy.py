"""Incremental compatibility port of the archived SCVRP CDELS-SA solver."""

from __future__ import annotations

from dataclasses import dataclass, field
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
    route_capacities_free: list[int] = field(default_factory=list)
    transfer_capacities_free: list[int] = field(default_factory=list)
    transfer_vehicle_count: int = 0
    transfer_total_capacity_free: int = 0

    def genome_dict(self) -> dict[str, object]:
        """Return only state that is defined before legacy reevaluation."""
        return {
            "routes": [list(route) for route in self.routes],
            "positions": [
                [int(value) for value in self.positions[axis].tolist()]
                for axis in range(2)
            ],
            "transfer_mask": [int(value) for value in self.transfer_mask.tolist()],
        }

    def canonical_dict(self) -> dict[str, object]:
        return {
            **self.genome_dict(),
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
    best_solution: LegacySCVRPIndividual
    feasible_solutions: int
    generation_id: int

    @property
    def best(self) -> LegacySCVRPIndividual:
        return self.best_solution

    @property
    def best_index(self) -> int:
        """Return the population slot holding best, or ``-1`` for retained elite.

        The legacy C++ generation stores a pointer to the best solution.  After
        simulated-annealing selection that pointer can intentionally refer to a
        retained individual from the previous generation which is not present
        in ``individuals``.  Identity comparison preserves that distinction.
        """
        for index, individual in enumerate(self.individuals):
            if individual is self.best_solution:
                return index
        return -1


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
            best_solution=individuals[best_index],
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

    def _make_hard_clone(
        self,
        individual: LegacySCVRPIndividual,
    ) -> LegacySCVRPIndividual:
        """Port ``individual_make_hard_clone`` without sharing mutable state."""
        return LegacySCVRPIndividual(
            routes=[list(route) for route in individual.routes],
            positions=individual.positions.copy(),
            transfer_mask=individual.transfer_mask.copy(),
            cost=individual.cost,
            feasible=individual.feasible,
            route_capacities_free=list(individual.route_capacities_free),
            transfer_capacities_free=list(individual.transfer_capacities_free),
            transfer_vehicle_count=individual.transfer_vehicle_count,
            transfer_total_capacity_free=individual.transfer_total_capacity_free,
        )

    def _mutation(
        self,
        generation: LegacySCVRPGeneration,
        target_index: int,
    ) -> LegacySCVRPIndividual:
        """Port the archived ``MUTATION_RAND`` selector and RNG order."""
        population_size = len(generation.individuals)
        r1 = self.rng.rand_mod(population_size)
        r2 = self.rng.rand_mod(population_size)
        r3 = self.rng.rand_mod(population_size)
        while r2 == target_index:
            r2 = self.rng.rand_mod(population_size)
        while r3 == target_index or r3 == r2:
            r3 = self.rng.rand_mod(population_size)
        while r1 == target_index or r1 == r2 or r1 == r3:
            r1 = self.rng.rand_mod(population_size)
        return self._generate_new_mutant(
            generation.individuals[r1],
            generation.individuals[r2],
            generation.individuals[r3],
        )

    def _generate_new_mutant(
        self,
        x1: LegacySCVRPIndividual,
        x2: LegacySCVRPIndividual,
        x3: LegacySCVRPIndividual,
    ) -> LegacySCVRPIndividual:
        """Port ``generate_new_mutant``, including its unused ``x2`` input."""
        del x2  # Selected and RNG-consuming in ``_mutation``, but unused by the archive.
        n_customers = self.problem.n_customers
        customers_possible = list(range(n_customers))
        customers_possible_num = n_customers - 1
        mutant = self._make_hard_clone(x1)
        perturbed_components = 0
        perturbed_components_max = int((n_customers / 2.0) * LEGACY_F)

        while True:
            random_index = self.rng.rand_mod(customers_possible_num) + 1
            customer_chosen = customers_possible[random_index]
            mutant_route = int(x3.positions[0, customer_chosen])
            mutant_position = int(x3.positions[1, customer_chosen])

            if len(mutant.routes[mutant_route]) < mutant_position + 1:
                self._remove_customer(mutant, customer_chosen, 0)
                self._insert_customer(
                    mutant,
                    customer_chosen,
                    0,
                    len(mutant.routes[mutant_route]),
                    mutant_route,
                )
            else:
                customer_target = mutant.routes[mutant_route][mutant_position]
                self._swap_customers(
                    mutant,
                    customer_chosen,
                    0,
                    customer_target,
                    0,
                )

            # Preserve the source's off-by-one compaction exactly.  This is not
            # a normal sampling-without-replacement implementation.
            while random_index < customers_possible_num - 1:
                customers_possible[random_index] = customers_possible[random_index + 1]
                random_index += 1
            customers_possible_num -= 1
            perturbed_components += 1
            if perturbed_components >= perturbed_components_max:
                break
        return mutant

    def _crossover(
        self,
        target: LegacySCVRPIndividual,
        mutant: LegacySCVRPIndividual,
    ) -> LegacySCVRPIndividual:
        """Port the archived exponential crossover, including every RNG draw."""
        route_index = self.rng.rand_mod(self.problem.vehicle_count)
        while not mutant.routes[route_index]:
            route_index = (
                route_index + 1
                if route_index < self.problem.vehicle_count - 1
                else 0
            )
        component_index = self.rng.rand_mod(len(mutant.routes[route_index]))
        customers_closed = [False] * self.problem.n_customers
        customers_closed[0] = True
        trial = self._make_hard_clone(target)

        customer_chosen = mutant.routes[route_index][component_index]
        self._apply_crossover_component(
            trial,
            customer_chosen=customer_chosen,
            route_index=route_index,
            component_index=component_index,
            customers_closed=customers_closed,
        )

        for current_route, mutant_route in enumerate(mutant.routes):
            for current_component, customer_chosen in enumerate(mutant_route):
                random_value = self.rng.rand_unit()
                if random_value <= LEGACY_CR:
                    if not customers_closed[customer_chosen]:
                        self._apply_crossover_component(
                            trial,
                            customer_chosen=customer_chosen,
                            route_index=current_route,
                            component_index=current_component,
                            customers_closed=customers_closed,
                        )
                else:
                    return trial
        return trial

    def _apply_crossover_component(
        self,
        trial: LegacySCVRPIndividual,
        *,
        customer_chosen: int,
        route_index: int,
        component_index: int,
        customers_closed: list[bool],
    ) -> None:
        """Apply one crossover permutation without consuming RNG."""
        if component_index >= len(trial.routes[route_index]):
            self._remove_customer(trial, customer_chosen, 0)
            self._insert_customer(
                trial,
                customer_chosen,
                0,
                len(trial.routes[route_index]),
                route_index,
            )
            customers_closed[customer_chosen] = True
            return

        customer_target = trial.routes[route_index][component_index]
        if customer_chosen == customer_target:
            customers_closed[customer_chosen] = True
            return
        self._swap_customers(
            trial,
            customer_chosen,
            0,
            customer_target,
            0,
        )
        customers_closed[customer_chosen] = True
        customers_closed[customer_target] = True

    def _remove_customer(
        self,
        individual: LegacySCVRPIndividual,
        customer: int,
        load: int,
    ) -> None:
        """Port ``individual_remove_customer`` including incremental capacity."""
        route_index = int(individual.positions[0, customer])
        position = int(individual.positions[1, customer])
        route = individual.routes[route_index]
        if int(individual.transfer_mask[customer]) == 0:
            individual.route_capacities_free[route_index] += int(load)
        route.pop(position)
        for shifted_position in range(position, len(route)):
            shifted_customer = route[shifted_position]
            individual.positions[1, shifted_customer] = shifted_position

    def _insert_customer(
        self,
        individual: LegacySCVRPIndividual,
        customer: int,
        load: int,
        new_index: int,
        new_route: int,
    ) -> None:
        """Port ``individual_insert_customer``."""
        route = individual.routes[new_route]
        route.insert(new_index, customer)
        for shifted_position in range(new_index + 1, len(route)):
            shifted_customer = route[shifted_position]
            individual.positions[1, shifted_customer] = shifted_position
        individual.positions[0, customer] = new_route
        individual.positions[1, customer] = new_index
        if int(individual.transfer_mask[customer]) == 0:
            individual.route_capacities_free[new_route] -= int(load)

    def _reinsert_customer_in_route(
        self,
        individual: LegacySCVRPIndividual,
        customer: int,
        new_index: int,
    ) -> None:
        """Port the legacy in-route reinsert index convention exactly."""
        route_index = int(individual.positions[0, customer])
        old_index = int(individual.positions[1, customer])
        if new_index == old_index:
            return
        route = individual.routes[route_index]
        insertion_index = new_index if new_index < old_index else new_index - 1
        route.pop(old_index)
        route.insert(insertion_index, customer)
        for position, routed_customer in enumerate(route):
            individual.positions[1, routed_customer] = position

    def _swap_customers(
        self,
        individual: LegacySCVRPIndividual,
        customer1: int,
        load1: int,
        customer2: int,
        load2: int,
    ) -> None:
        """Port ``individual_swap_customers`` and its transfer-load rule."""
        route1 = int(individual.positions[0, customer1])
        position1 = int(individual.positions[1, customer1])
        route2 = int(individual.positions[0, customer2])
        position2 = int(individual.positions[1, customer2])
        effective_load1 = 0 if int(individual.transfer_mask[customer1]) == 1 else int(load1)
        effective_load2 = 0 if int(individual.transfer_mask[customer2]) == 1 else int(load2)

        individual.routes[route2][position2] = customer1
        individual.routes[route1][position1] = customer2
        individual.positions[0, customer2] = route1
        individual.positions[1, customer2] = position1
        individual.route_capacities_free[route1] += effective_load1 - effective_load2
        individual.positions[0, customer1] = route2
        individual.positions[1, customer1] = position2
        individual.route_capacities_free[route2] += effective_load2 - effective_load1

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
        individual.route_capacities_free = list(evaluation.route_capacities_free)
        individual.transfer_capacities_free = list(evaluation.transfer_capacities_free)
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
