from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import numpy as np

from mkp.problem.scvrp import load_legacy_scvrp_problem
from mkp.solver.CDELS_2 import CDELS2, _build_positions
from mkp.solver.CDELS_2_numba import (
    CDELS2Numba,
    _accept_trial_by_sa_numba,
    _crossover_numba,
    _generate_new_mutant_numba,
    _local_search_numba,
    _reevaluate_workspace_numba,
    _select_mutation_indices_numba,
    _select_workspace_trial_by_sa_numba,
    _strong_drop_numba,
    _two_swap_numba,
)


FIXTURES = Path(__file__).parent / "fixtures" / "scvrp"


def _problem():
    return load_legacy_scvrp_problem(
        FIXTURES / "p_n16_k8.vrp",
        FIXTURES / "p_n16_k8_routecap2_transfer1.txt",
        dataset="P",
        problem_id="P-n16-k8-routecap2-transfer1",
        best_known=350,
    )


def _solve(core, *, transitions: int):
    return core.solve(
        termination_mode="fixed_iterations",
        limit=transitions,
        start_temperature=1.0,
        cooling_rate=0.95,
        iterations_per_temperature=110,
        max_transitions=max(1, transitions),
        trace=True,
        process_trace=True,
    )


def _trial(core, target_index):
    generation = core.initialize_population()
    mutant = core._mutation(generation, target_index)
    trial = core._crossover(
        generation.individuals[target_index],
        mutant,
        destination=core.workspace.free_population[target_index],
    )
    core._reevaluate(trial)
    return trial


def test_cdels_2_numba_initial_population_matches_workspace_baseline() -> None:
    problem = _problem()
    baseline = CDELS2(problem, seed=1)
    numba_core = CDELS2Numba(problem, seed=1)

    baseline_generation = baseline.initialize_population()
    numba_generation = numba_core.initialize_population()

    assert numba_core.process_trace_generation(numba_generation) == (
        baseline.process_trace_generation(baseline_generation)
    )
    assert _reevaluate_workspace_numba.nopython_signatures


def test_cdels_2_numba_reevaluate_matches_all_state_and_reuses_lists() -> None:
    problem = _problem()
    baseline = CDELS2(problem, seed=1)
    numba_core = CDELS2Numba(problem, seed=1)
    generation = baseline.initialize_population()
    cases = [deepcopy(value) for value in generation.individuals[:6]]

    transferred = deepcopy(generation.individuals[0])
    transferred.transfer_mask[1] = 1
    transferred.transfer_mask[2] = 1
    cases.append(transferred)

    infeasible = deepcopy(generation.individuals[0])
    infeasible.routes = [
        list(range(1, problem.n_customers)),
        *[[] for _ in range(problem.vehicle_count - 1)],
    ]
    infeasible.positions = _build_positions(
        infeasible.routes,
        n_customers=problem.n_customers,
    )
    cases.append(infeasible)

    for source in cases:
        baseline_individual = deepcopy(source)
        numba_individual = deepcopy(source)
        route_capacities = numba_individual.route_capacities_free
        transfer_capacities = numba_individual.transfer_capacities_free

        baseline_evaluation = baseline._reevaluate(baseline_individual)
        numba_evaluation = numba_core._reevaluate(numba_individual)

        assert numba_evaluation == baseline_evaluation
        assert numba_individual.canonical_dict() == (
            baseline_individual.canonical_dict()
        )

        assert numba_individual.route_capacities_free is route_capacities
        assert (
            numba_individual.transfer_capacities_free
            is transfer_capacities
        )


def test_cdels_2_numba_two_transitions_match_workspace_baseline() -> None:
    problem = _problem()
    baseline = _solve(CDELS2(problem, seed=1), transitions=2)
    numba_result = _solve(CDELS2Numba(problem, seed=1), transitions=2)

    assert numba_result.process_trace == baseline.process_trace
    assert numba_result.process_trace_sha256 == baseline.process_trace_sha256
    assert numba_result.result == baseline.result
    assert numba_result.rng_state == baseline.rng_state
    assert numba_result.rng_draw_count == baseline.rng_draw_count
    assert numba_result.final_temperature.hex() == (
        baseline.final_temperature.hex()
    )


def test_cdels_2_numba_mutation_crossover_are_exact_and_in_place() -> None:
    problem = _problem()
    for seed, target_index in ((1, 0), (1, 13), (30, 11), (36, 1), (9, 3)):
        baseline = CDELS2(problem, seed=seed)
        numba_core = CDELS2Numba(problem, seed=seed)
        baseline_generation = baseline.initialize_population()
        numba_generation = numba_core.initialize_population()
        mutant_buffer = numba_core.workspace.mutant
        mutant_state_ids = (
            id(mutant_buffer.positions),
            id(mutant_buffer.transfer_mask),
            tuple(id(route) for route in mutant_buffer.routes),
        )

        baseline_mutant = baseline._mutation(baseline_generation, target_index)
        numba_mutant = numba_core._mutation(numba_generation, target_index)
        assert numba_mutant is mutant_buffer
        assert numba_mutant.canonical_dict() == baseline_mutant.canonical_dict()
        assert (numba_core.rng.state, numba_core.rng.draw_count) == (
            baseline.rng.state,
            baseline.rng.draw_count,
        )
        assert mutant_state_ids == (
            id(mutant_buffer.positions),
            id(mutant_buffer.transfer_mask),
            tuple(id(route) for route in mutant_buffer.routes),
        )

        baseline_destination = baseline.workspace.free_population[target_index]
        numba_destination = numba_core.workspace.free_population[target_index]
        destination_state_ids = (
            id(numba_destination.positions),
            id(numba_destination.transfer_mask),
            tuple(id(route) for route in numba_destination.routes),
        )
        baseline_trial = baseline._crossover(
            baseline_generation.individuals[target_index],
            baseline_mutant,
            destination=baseline_destination,
        )
        numba_trial = numba_core._crossover(
            numba_generation.individuals[target_index],
            numba_mutant,
            destination=numba_destination,
        )
        assert numba_trial is numba_destination
        assert numba_trial.canonical_dict() == baseline_trial.canonical_dict()
        assert (numba_core.rng.state, numba_core.rng.draw_count) == (
            baseline.rng.state,
            baseline.rng.draw_count,
        )
        assert destination_state_ids == (
            id(numba_destination.positions),
            id(numba_destination.transfer_mask),
            tuple(id(route) for route in numba_destination.routes),
        )

    assert _select_mutation_indices_numba.nopython_signatures
    assert _generate_new_mutant_numba.nopython_signatures
    assert _crossover_numba.nopython_signatures


def test_cdels_2_numba_sa_matches_fixed_vectors() -> None:
    problem = _problem()
    cases = (
        (30_091, 100, 90, 1.0),
        (1, 100, 100, 1.0),
        (30_091, 100, 100, 1.0),
        (1, 100, 101, 10.0),
        (30_091, 100, 101, 10.0),
        (1, 0, 1_000, 1.0),
        (1, 0x7FFF_FFFF, 0, 1.0),
        (1, 100, 90, 0.0),
        (1, 100, 110, 0.0),
        (1, 100, 100, 0.0),
    )
    for seed, target_cost, trial_cost, temperature in cases:
        baseline = CDELS2(problem, seed=seed)
        numba_core = CDELS2Numba(problem, seed=seed)
        expected = baseline._accept_trial_by_sa(
            target_cost, trial_cost, temperature
        )
        actual = numba_core._accept_trial_by_sa(
            target_cost, trial_cost, temperature
        )
        assert actual is expected
        assert (numba_core.rng.state, numba_core.rng.draw_count) == (
            baseline.rng.state,
            baseline.rng.draw_count,
        )
    assert _accept_trial_by_sa_numba.nopython_signatures


def test_cdels_2_numba_selection_rotates_same_pool_and_external_elite() -> None:
    problem = _problem()
    baseline = CDELS2(problem, seed=1)
    numba_core = CDELS2Numba(problem, seed=1)
    baseline_generation = baseline.initialize_population()
    numba_generation = numba_core.initialize_population()
    workspace = numba_core.workspace
    candidate_ids = {
        id(value)
        for value in (
            list(numba_generation.individuals)
            + list(workspace.free_population)
        )
    }
    list_ids = {
        id(workspace.active_population),
        id(workspace.free_population),
        id(workspace.spare_population_refs),
    }
    saw_external_elite = False

    for _ in range(6):
        baseline_generation = baseline._new_generation(
            baseline_generation, 1.0
        )
        numba_generation = numba_core._new_generation(
            numba_generation, 1.0
        )
        assert numba_core.process_trace_generation(numba_generation) == (
            baseline.process_trace_generation(baseline_generation)
        )
        active_ids = {id(value) for value in numba_generation.individuals}
        free_ids = {id(value) for value in workspace.free_population}
        assert active_ids.isdisjoint(free_ids)
        assert active_ids | free_ids == candidate_ids
        assert {
            id(workspace.active_population),
            id(workspace.free_population),
            id(workspace.spare_population_refs),
        } == list_ids
        if numba_generation.best_index == -1:
            saw_external_elite = True
            assert numba_generation.best_solution is workspace.elite

    assert saw_external_elite
    assert _select_workspace_trial_by_sa_numba.nopython_signatures


def test_cdels_2_numba_two_swap_matches_state_and_workspace_identity() -> None:
    problem = _problem()
    baseline = CDELS2(problem, seed=1)
    numba_core = CDELS2Numba(problem, seed=1)
    generation = baseline.initialize_population()

    cases = [deepcopy(value) for value in generation.individuals[:6]]
    mixed_transfer = deepcopy(generation.individuals[0])
    for customer in (1, 3, 7):
        mixed_transfer.transfer_mask[customer] = 1
    cases.append(mixed_transfer)

    for source in cases:
        baseline_individual = deepcopy(source)
        numba_individual = deepcopy(source)
        baseline._reevaluate(baseline_individual)
        numba_core._reevaluate(numba_individual)
        routes = numba_individual.routes
        route_ids = tuple(id(route) for route in routes)
        capacities = numba_individual.route_capacities_free

        baseline._two_swap(baseline_individual)
        numba_core._two_swap(numba_individual)

        assert numba_individual.canonical_dict() == (
            baseline_individual.canonical_dict()
        )
        assert numba_individual.routes is routes
        assert tuple(id(route) for route in routes) == route_ids
        assert numba_individual.route_capacities_free is capacities

    assert _two_swap_numba.nopython_signatures


def test_cdels_2_numba_strong_drop_matches_reinsertion_and_identity() -> None:
    problem = _problem()
    baseline = CDELS2(problem, seed=1)
    numba_core = CDELS2Numba(problem, seed=1)
    generation = baseline.initialize_population()

    cases = [deepcopy(value) for value in generation.individuals[:6]]
    mixed_transfer = deepcopy(generation.individuals[0])
    for customer in (1, 3, 7):
        mixed_transfer.transfer_mask[customer] = 1
    cases.append(mixed_transfer)

    for source in cases:
        baseline_individual = deepcopy(source)
        numba_individual = deepcopy(source)
        baseline._reevaluate(baseline_individual)
        numba_core._reevaluate(numba_individual)
        routes = numba_individual.routes
        route_ids = tuple(id(route) for route in routes)
        positions = numba_individual.positions
        capacities = numba_individual.route_capacities_free

        baseline._strong_drop(baseline_individual)
        numba_core._strong_drop(numba_individual)

        assert numba_individual.canonical_dict() == (
            baseline_individual.canonical_dict()
        )
        assert numba_individual.routes is routes
        assert tuple(id(route) for route in routes) == route_ids
        assert numba_individual.positions is positions
        assert numba_individual.route_capacities_free is capacities

    assert _strong_drop_numba.nopython_signatures


def test_cdels_2_numba_move_kernels_match_randomized_states() -> None:
    """固定產生 route、transfer 與 overload 分支，不只測初始群體。"""
    problem = _problem()
    baseline = CDELS2(problem, seed=1)
    numba_core = CDELS2Numba(problem, seed=1)
    template = baseline.initialize_population().individuals[0]
    generator = np.random.default_rng(20261005)

    for _ in range(32):
        customers = generator.permutation(
            np.arange(1, problem.n_customers, dtype=np.int64)
        )
        route_choices = generator.integers(
            0,
            problem.vehicle_count,
            size=problem.n_customers - 1,
        )
        routes = [[] for _ in range(problem.vehicle_count)]
        for customer, route_index in zip(
            customers.tolist(),
            route_choices.tolist(),
            strict=True,
        ):
            routes[route_index].append(int(customer))

        source = deepcopy(template)
        source.routes = routes
        source.positions = _build_positions(
            routes,
            n_customers=problem.n_customers,
        )
        source.transfer_mask[:] = 0
        for customer in range(1, problem.n_customers):
            source.transfer_mask[customer] = int(generator.random() < 0.25)

        baseline_individual = deepcopy(source)
        numba_individual = deepcopy(source)
        baseline._reevaluate(baseline_individual)
        numba_core._reevaluate(numba_individual)
        baseline._two_swap(baseline_individual)
        numba_core._two_swap(numba_individual)
        assert numba_individual.canonical_dict() == (
            baseline_individual.canonical_dict()
        )

        baseline._strong_drop(baseline_individual)
        numba_core._strong_drop(numba_individual)
        assert numba_individual.canonical_dict() == (
            baseline_individual.canonical_dict()
        )


def test_cdels_2_numba_full_local_search_matches_state_rng_and_buffers() -> None:
    problem = _problem()
    for seed, target_index in ((1, 0), (1, 2), (2, 0), (7, 5)):
        baseline = CDELS2(problem, seed=seed)
        numba_core = CDELS2Numba(problem, seed=seed)
        baseline_trial = _trial(baseline, target_index)
        numba_trial = _trial(numba_core, target_index)
        routes = numba_trial.routes
        route_ids = tuple(id(route) for route in routes)
        positions = numba_trial.positions
        transfer_mask = numba_trial.transfer_mask
        route_capacities = numba_trial.route_capacities_free
        transfer_capacities = numba_trial.transfer_capacities_free

        baseline._local_search(baseline_trial)
        numba_core._local_search(numba_trial)

        assert numba_trial.canonical_dict() == baseline_trial.canonical_dict()
        assert (numba_core.rng.state, numba_core.rng.draw_count) == (
            baseline.rng.state,
            baseline.rng.draw_count,
        )
        assert numba_trial.routes is routes
        assert tuple(id(route) for route in routes) == route_ids
        assert numba_trial.positions is positions
        assert numba_trial.transfer_mask is transfer_mask
        assert numba_trial.route_capacities_free is route_capacities
        assert numba_trial.transfer_capacities_free is transfer_capacities

    assert _local_search_numba.nopython_signatures
