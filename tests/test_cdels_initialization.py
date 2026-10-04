from __future__ import annotations

from pathlib import Path
import re

import numpy as np
import pytest

from mkp.problem.scvrp import load_legacy_scvrp_problem
from mkp.solver.CDELS import CDELS, CDELSGeneration


FIXTURES = Path(__file__).parent / "fixtures" / "scvrp"


def _problem():
    return load_legacy_scvrp_problem(
        FIXTURES / "p_n16_k8.vrp",
        FIXTURES / "p_n16_k8_routecap2_transfer1.txt",
        dataset="P",
        problem_id="P-n16-k8-routecap2-transfer1",
        best_known=350,
    )


def test_distance_memoryview_shares_read_only_problem_buffer() -> None:
    problem = _problem()
    core = CDELS(problem, seed=1)

    assert core._distances.obj is problem.distance_matrix
    assert core._distances.readonly is True
    assert core._distances.shape == problem.distance_matrix.shape
    assert core._distances.nbytes == problem.distance_matrix.nbytes
    assert core._distances[3, 11] == int(problem.distance_matrix[3, 11])
    with pytest.raises(TypeError):
        core._distances[3, 11] = 0


def test_seed_one_initial_population_matches_archived_generation_one() -> None:
    report = (FIXTURES / "p_n16_k8_seed1_initial_report.txt").read_text(encoding="ascii")
    expected_best = int(re.search(r"Best solution:\s*(\d+)", report).group(1))
    expected_feasible = int(re.search(r"Number of feasible solutions:\s*(\d+)", report).group(1))
    core = CDELS(_problem(), seed=1)

    generation = core.initialize_population()
    trace = core.trace_generation(generation, stage="initial_population")

    assert trace.generation_id == 1
    assert trace.population_size == 48
    assert trace.best_cost == expected_best == 493
    assert trace.feasible_solutions == expected_feasible == 32
    assert trace.best_index == 27
    assert trace.rng_draw_count == 14_456
    assert trace.rng_state == 0x999C_D719
    assert trace.population_sha256 == "b243a9a36d4401ac75618a42b6a4cfe4dea849d95be66dcc13f9b8c522f08bc9"


def test_seed_one_initial_population_trace_is_repeatable() -> None:
    core_a = CDELS(_problem(), seed=1)
    core_b = CDELS(_problem(), seed=1)

    trace_a = core_a.trace_generation(core_a.initialize_population(), stage="initial_population")
    trace_b = core_b.trace_generation(core_b.initialize_population(), stage="initial_population")

    assert trace_a == trace_b


def test_generation_can_retain_a_best_solution_outside_its_population() -> None:
    core = CDELS(_problem(), seed=1)
    generation = core.initialize_population()
    retained_best = generation.best
    cloned_population = [core._make_hard_clone(value) for value in generation.individuals]

    next_generation = CDELSGeneration(
        individuals=cloned_population,
        best_solution=retained_best,
        feasible_solutions=generation.feasible_solutions,
        generation_id=2,
    )

    assert next_generation.best is retained_best
    assert next_generation.best_index == -1


def test_hard_clone_and_customer_operations_match_legacy_array_semantics() -> None:
    problem = _problem()
    core = CDELS(problem, seed=1)
    generation = core.initialize_population()
    rng_draw_count = core.rng.draw_count
    original = generation.individuals[0]
    individual = core._make_hard_clone(original)

    assert individual.canonical_dict() == original.canonical_dict()
    assert individual is not original
    assert individual.routes is not original.routes
    assert all(left is not right for left, right in zip(individual.routes, original.routes))
    assert not np.shares_memory(individual.positions, original.positions)
    assert not np.shares_memory(individual.transfer_mask, original.transfer_mask)

    customer = 3
    source_route = 0
    destination_route = 1
    load = int(problem.demands[customer])
    source_capacity = individual.route_capacities_free[source_route]
    destination_capacity = individual.route_capacities_free[destination_route]
    core._remove_customer(individual, customer, load)
    assert individual.routes[source_route] == [5, 11]
    assert individual.route_capacities_free[source_route] == source_capacity + load
    core._insert_customer(individual, customer, load, 1, destination_route)
    assert individual.routes[destination_route] == [6, 3]
    assert individual.route_capacities_free[destination_route] == destination_capacity - load

    customer1 = 3
    customer2 = 7
    load1 = int(problem.demands[customer1])
    load2 = int(problem.demands[customer2])
    route1 = int(individual.positions[0, customer1])
    route2 = int(individual.positions[0, customer2])
    capacity1 = individual.route_capacities_free[route1]
    capacity2 = individual.route_capacities_free[route2]
    core._swap_customers(individual, customer1, load1, customer2, load2)
    assert individual.route_capacities_free[route1] == capacity1 + load1 - load2
    assert individual.route_capacities_free[route2] == capacity2 - load1 + load2

    routes_before_noop = [list(route) for route in individual.routes]
    core._reinsert_customer_in_route(
        individual,
        10,
        int(individual.positions[1, 10]),
    )
    assert individual.routes == routes_before_noop

    core._reinsert_customer_in_route(individual, 1, 3)
    assert individual.routes[2] == [10, 13, 1]
    assert sorted(customer for route in individual.routes for customer in route) == list(range(1, 16))
    for route_index, route in enumerate(individual.routes):
        for position, routed_customer in enumerate(route):
            assert tuple(individual.positions[:, routed_customer]) == (route_index, position)
    assert core.rng.draw_count == rng_draw_count


def test_seed_one_target_zero_mutation_matches_native_stage_fingerprint() -> None:
    core = CDELS(_problem(), seed=1)
    generation = core.initialize_population()

    mutant = core._mutation(generation, 0)

    assert core.rng.draw_count == 14_464
    assert core.rng.state == 1_128_404_609
    assert mutant.routes == [
        [8],
        [15, 10, 5],
        [4],
        [2],
        [7, 14],
        [3, 12, 9],
        [11, 13, 1],
        [6],
    ]
    assert mutant.positions.tolist() == [
        [0, 6, 3, 5, 2, 1, 7, 4, 0, 5, 1, 6, 5, 6, 4, 1],
        [0, 2, 0, 0, 0, 2, 0, 0, 0, 2, 1, 0, 1, 1, 1, 0],
    ]
    assert mutant.transfer_mask.tolist() == [0] * 16


def test_seed_one_target_zero_exp_crossover_matches_native_stage_fingerprint() -> None:
    core = CDELS(_problem(), seed=1)
    generation = core.initialize_population()
    mutant = core._mutation(generation, 0)

    trial = core._crossover(generation.individuals[0], mutant)

    assert core.rng.draw_count == 14_467
    assert core.rng.state == 1_889_806_266
    assert trial.routes == [
        [3, 5, 11],
        [6],
        [1, 10, 13],
        [4, 15],
        [7],
        [8, 12],
        [2],
        [9, 14],
    ]
    assert trial.positions.tolist() == [
        [0, 2, 6, 0, 3, 0, 1, 4, 5, 7, 2, 0, 5, 2, 7, 3],
        [0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 2, 1, 2, 1, 1],
    ]
    assert trial.transfer_mask.tolist() == [0] * 16
