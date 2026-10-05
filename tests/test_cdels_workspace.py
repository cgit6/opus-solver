from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from mkp.problem.scvrp import load_legacy_scvrp_problem
from mkp.solver.CDELS import CDELS
from mkp.solver.CDELS_workspace import (
    CDELSWorkspace,
    _CDELSFlatListRoutesPrototype,
    _CDELSFixedRoutesPrototype,
)


FIXTURES = Path(__file__).parent / "fixtures" / "scvrp"


def test_fixed_routes_prototype_preserves_route_order_and_empty_routes() -> None:
    routes = [[], [4, 7], [], [2, 1, 3, 5, 6]]

    packed = _CDELSFixedRoutesPrototype.from_routes(
        routes,
        n_customers=8,
    )

    assert packed.customers.dtype == np.uint16
    assert packed.starts.dtype == np.uint16
    assert packed.lengths.dtype == np.uint16
    assert packed.customers.tolist() == [4, 7, 2, 1, 3, 5, 6]
    assert packed.starts.tolist() == [0, 0, 2, 2]
    assert packed.lengths.tolist() == [0, 2, 0, 5]
    assert packed.routes_tuple() == tuple(tuple(route) for route in routes)
    assert packed.route_length(0) == 0
    assert packed.route_length(1) == 2
    assert packed.customer_at(1, 0) == 4
    assert packed.customer_at(3, 4) == 6
    assert packed.customer_capacity == 7
    assert packed.owned_nbytes == (7 + 4 + 4) * 2


def test_fixed_routes_copy_reuses_destination_backing_arrays() -> None:
    source = _CDELSFixedRoutesPrototype.from_routes(
        [[1, 2], [], [3, 4, 5]],
        n_customers=6,
    )
    destination = _CDELSFixedRoutesPrototype.from_routes(
        [[5], [4, 3], [2, 1]],
        n_customers=6,
    )
    backing_ids = (
        id(destination.customers),
        id(destination.starts),
        id(destination.lengths),
    )

    copied = source.copy_into(destination)

    assert copied is destination
    assert copied.routes_tuple() == source.routes_tuple()
    assert (
        id(destination.customers),
        id(destination.starts),
        id(destination.lengths),
    ) == backing_ids
    assert not np.shares_memory(source.customers, destination.customers)
    assert not np.shares_memory(source.starts, destination.starts)
    assert not np.shares_memory(source.lengths, destination.lengths)

    # clone 後兩邊必須能各自修改，不能因為共用 backing storage 互相污染。
    source.swap(0, 0, 2, 2)
    assert source.routes_tuple() != destination.routes_tuple()


def test_fixed_routes_swap_matches_list_routes_after_each_operation() -> None:
    routes = [[1, 5, 7], [2], [], [3, 4, 6]]
    reference = [list(route) for route in routes]
    packed = _CDELSFixedRoutesPrototype.from_routes(
        routes,
        n_customers=8,
    )
    operations = (
        (0, 0, 0, 2),
        (0, 1, 1, 0),
        (1, 0, 3, 2),
        (3, 0, 3, 1),
    )

    for route1, position1, route2, position2 in operations:
        reference[route1][position1], reference[route2][position2] = (
            reference[route2][position2],
            reference[route1][position1],
        )
        packed.swap(route1, position1, route2, position2)
        assert packed.routes_tuple() == tuple(
            tuple(route) for route in reference
        )


def test_fixed_routes_supports_2000_points_with_uint16() -> None:
    packed = _CDELSFixedRoutesPrototype.from_routes(
        [list(range(1, 1001)), [], list(range(1001, 2001))],
        n_customers=2001,
    )

    assert packed.customer_at(0, 999) == 1000
    assert packed.customer_at(2, 999) == 2000
    assert packed.starts.tolist() == [0, 1000, 1000]
    assert packed.lengths.tolist() == [1000, 0, 1000]
    assert packed.customer_capacity == 2000


@pytest.mark.parametrize(
    ("routes", "n_customers", "message"),
    (
        ([[1, 1], [2]], 4, "duplicate"),
        ([[1], [2]], 4, "every non-depot"),
        ([[0], [1, 2]], 4, "outside"),
        ([[1, 2, 4]], 4, "outside"),
        ([[]], 65_537, "1..65,536"),
    ),
)
def test_fixed_routes_rejects_invalid_permutations(
    routes,
    n_customers: int,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        _CDELSFixedRoutesPrototype.from_routes(
            routes,
            n_customers=n_customers,
        )


def test_fixed_routes_rejects_invalid_read_and_swap_positions() -> None:
    packed = _CDELSFixedRoutesPrototype.from_routes(
        [[1, 2], [], [3]],
        n_customers=4,
    )

    with pytest.raises(IndexError, match="route index"):
        packed.route_length(3)
    with pytest.raises(IndexError, match="route position"):
        packed.customer_at(1, 0)
    with pytest.raises(IndexError, match="first"):
        packed.swap(0, 2, 2, 0)
    with pytest.raises(IndexError, match="second"):
        packed.swap(0, 0, 1, 0)


def test_flat_list_routes_preserves_order_and_fixed_container_lengths() -> None:
    routes = [[], [4, 7], [], [2, 1, 3, 5, 6]]
    flat = _CDELSFlatListRoutesPrototype.from_routes(
        routes,
        n_customers=8,
    )
    container_ids = (
        id(flat.customers),
        id(flat.starts),
        id(flat.lengths),
    )
    container_lengths = (
        len(flat.customers),
        len(flat.starts),
        len(flat.lengths),
    )

    flat.swap(1, 0, 3, 4)
    flat.swap(1, 0, 3, 4)

    assert flat.customers == [4, 7, 2, 1, 3, 5, 6]
    assert flat.starts == [0, 0, 2, 2]
    assert flat.lengths == [0, 2, 0, 5]
    assert flat.routes_tuple() == tuple(tuple(route) for route in routes)
    assert flat.customer_at(1, 0) == 4
    assert flat.customer_at(3, 4) == 6
    assert flat.customer_capacity == 7
    assert (
        id(flat.customers),
        id(flat.starts),
        id(flat.lengths),
    ) == container_ids
    assert (
        len(flat.customers),
        len(flat.starts),
        len(flat.lengths),
    ) == container_lengths


def test_flat_list_routes_copy_reuses_destination_lists() -> None:
    source = _CDELSFlatListRoutesPrototype.from_routes(
        [[1, 2], [], [3, 4, 5]],
        n_customers=6,
    )
    destination = _CDELSFlatListRoutesPrototype.from_routes(
        [[5], [4, 3], [2, 1]],
        n_customers=6,
    )
    backing_ids = (
        id(destination.customers),
        id(destination.starts),
        id(destination.lengths),
    )

    copied = source.copy_into(destination)

    assert copied is destination
    assert destination.routes_tuple() == source.routes_tuple()
    assert (
        id(destination.customers),
        id(destination.starts),
        id(destination.lengths),
    ) == backing_ids
    assert destination.customers is not source.customers
    assert destination.starts is not source.starts
    assert destination.lengths is not source.lengths

    source.swap(0, 0, 2, 2)
    assert source.routes_tuple() != destination.routes_tuple()


def test_flat_list_routes_swap_matches_nested_lists() -> None:
    routes = [[1, 5, 7], [2], [], [3, 4, 6]]
    reference = [list(route) for route in routes]
    flat = _CDELSFlatListRoutesPrototype.from_routes(
        routes,
        n_customers=8,
    )
    operations = (
        (0, 0, 0, 2),
        (0, 1, 1, 0),
        (1, 0, 3, 2),
        (3, 0, 3, 1),
    )

    for route1, position1, route2, position2 in operations:
        reference[route1][position1], reference[route2][position2] = (
            reference[route2][position2],
            reference[route1][position1],
        )
        flat.swap(route1, position1, route2, position2)
        assert flat.routes_tuple() == tuple(
            tuple(route) for route in reference
        )


def test_flat_list_routes_supports_2000_points_and_validates_input() -> None:
    flat = _CDELSFlatListRoutesPrototype.from_routes(
        [list(range(1, 1001)), [], list(range(1001, 2001))],
        n_customers=2001,
    )

    assert flat.customer_at(0, 999) == 1000
    assert flat.customer_at(2, 999) == 2000
    assert flat.starts == [0, 1000, 1000]
    assert flat.lengths == [1000, 0, 1000]

    with pytest.raises(ValueError, match="duplicate"):
        _CDELSFlatListRoutesPrototype.from_routes(
            [[1, 1], [2]],
            n_customers=4,
        )
    with pytest.raises(IndexError, match="route position"):
        flat.customer_at(1, 0)


def _problem():
    return load_legacy_scvrp_problem(
        FIXTURES / "p_n16_k8.vrp",
        FIXTURES / "p_n16_k8_routecap2_transfer1.txt",
        dataset="P",
        problem_id="P-n16-k8-routecap2-transfer1",
        best_known=350,
    )


def _solve(core, *, transitions: int = 2):
    return core.solve(
        termination_mode="fixed_iterations",
        limit=transitions,
        start_temperature=1.0,
        cooling_rate=0.95,
        iterations_per_temperature=110,
        max_transitions=transitions,
        trace=True,
        process_trace=True,
    )


def test_workspace_is_initialized_before_population_and_reuses_buffers() -> None:
    core = CDELSWorkspace(_problem(), seed=1)

    mutation_buffer = core.workspace.mutation_customers
    crossover_buffer = core.workspace.crossover_closed
    mutant_buffer = core.workspace.mutant
    mutation_id = id(mutation_buffer)
    crossover_id = id(crossover_buffer)
    mutant_id = id(mutant_buffer)
    mutant_positions_id = id(mutant_buffer.positions)
    mutant_transfer_mask_id = id(mutant_buffer.transfer_mask)
    mutant_route_ids = tuple(id(route) for route in mutant_buffer.routes)
    assert mutation_buffer == list(range(core.problem.n_customers))
    assert crossover_buffer == bytearray(core.problem.n_customers)

    # 跑完整兩次世代轉換後，Workspace 應仍是原本那兩個容器，而不是每個
    # target 重新建立一份。內容可以被演算法改寫，但容器 identity 不可改變。
    _solve(core)

    assert core.workspace.mutation_customers is mutation_buffer
    assert core.workspace.crossover_closed is crossover_buffer
    assert id(core.workspace.mutation_customers) == mutation_id
    assert id(core.workspace.crossover_closed) == crossover_id
    assert id(core.workspace.mutant) == mutant_id
    assert id(core.workspace.mutant.positions) == mutant_positions_id
    assert id(core.workspace.mutant.transfer_mask) == mutant_transfer_mask_id
    assert tuple(
        id(route) for route in core.workspace.mutant.routes
    ) == mutant_route_ids


def test_workspace_population_uses_compact_state_dtypes() -> None:
    core = CDELSWorkspace(_problem(), seed=1)
    generation = core.initialize_population()
    all_buffers = (
        list(generation.individuals)
        + list(core.workspace.free_population)
        + [core.workspace.mutant, core.workspace.elite]
    )

    assert all(value.positions.dtype == np.uint16 for value in all_buffers)
    assert all(
        value.transfer_mask.dtype == np.uint8 for value in all_buffers
    )
    assert all(
        value.positions.shape == (2, core.problem.n_customers)
        for value in all_buffers
    )
    assert all(
        value.transfer_mask.shape == (core.problem.n_customers,)
        for value in all_buffers
    )


def test_population_numeric_state_uses_two_contiguous_backing_arrays() -> None:
    core = CDELSWorkspace(_problem(), seed=1)
    generation = core.initialize_population()
    workspace = core.workspace
    all_buffers = (
        list(generation.individuals)
        + list(workspace.free_population)
        + [workspace.mutant, workspace.elite]
    )

    assert workspace.positions_storage.flags.c_contiguous
    assert workspace.positions_storage.flags.owndata
    assert workspace.transfer_mask_storage.flags.c_contiguous
    assert workspace.transfer_mask_storage.flags.owndata
    assert workspace.positions_storage.shape == (
        2 * core.population_size + 2,
        2,
        core.problem.n_customers,
    )
    assert workspace.transfer_mask_storage.shape == (
        2 * core.population_size + 2,
        core.problem.n_customers,
    )
    assert all(
        np.shares_memory(value.positions, workspace.positions_storage)
        for value in all_buffers
    )
    assert all(
        np.shares_memory(
            value.transfer_mask,
            workspace.transfer_mask_storage,
        )
        for value in all_buffers
    )
    assert not any(value.positions.flags.owndata for value in all_buffers)
    assert not any(
        value.transfer_mask.flags.owndata for value in all_buffers
    )
    assert len(
        {
            int(value.positions.__array_interface__["data"][0])
            for value in all_buffers
        }
    ) == len(all_buffers)
    assert len(
        {
            int(value.transfer_mask.__array_interface__["data"][0])
            for value in all_buffers
        }
    ) == len(all_buffers)


def test_copy_individual_into_reuses_all_mutant_state_containers() -> None:
    core = CDELSWorkspace(_problem(), seed=1)
    source = core.initialize_population().individuals[0]
    destination = core.workspace.mutant
    destination_id = id(destination)
    positions_id = id(destination.positions)
    transfer_mask_id = id(destination.transfer_mask)
    route_ids = tuple(id(route) for route in destination.routes)

    copied = core._copy_individual_into(destination, source)

    assert copied is destination
    assert copied.canonical_dict() == source.canonical_dict()
    assert id(copied) == destination_id
    assert id(copied.positions) == positions_id
    assert id(copied.transfer_mask) == transfer_mask_id
    assert tuple(id(route) for route in copied.routes) == route_ids
    assert not np.shares_memory(copied.positions, source.positions)
    assert not np.shares_memory(copied.transfer_mask, source.transfer_mask)
    assert all(
        copied_route is not source_route
        for copied_route, source_route in zip(
            copied.routes,
            source.routes,
            strict=True,
        )
    )


def test_workspace_two_transitions_match_cdels_bit_for_bit() -> None:
    baseline = _solve(CDELS(_problem(), seed=1))
    workspace = _solve(CDELSWorkspace(_problem(), seed=1))

    assert workspace.process_trace_sha256 == baseline.process_trace_sha256
    assert [
        (item.generation, item.canonical_digest, item.rng_state, item.rng_draw_count)
        for item in workspace.process_trace
    ] == [
        (item.generation, item.canonical_digest, item.rng_state, item.rng_draw_count)
        for item in baseline.process_trace
    ]
    assert [
        (
            item.generation,
            item.objective,
            item.feasible_solutions,
            item.feasible,
            item.transfer_vehicle_count,
            item.routes,
            item.transferred_customers,
        )
        for item in workspace.trace
    ] == [
        (
            item.generation,
            item.objective,
            item.feasible_solutions,
            item.feasible,
            item.transfer_vehicle_count,
            item.routes,
            item.transferred_customers,
        )
        for item in baseline.trace
    ]
    assert workspace.rng_state == baseline.rng_state
    assert workspace.rng_draw_count == baseline.rng_draw_count
    assert workspace.final_temperature.hex() == baseline.final_temperature.hex()


def test_population_pool_rotates_references_without_new_individuals() -> None:
    core = CDELSWorkspace(_problem(), seed=1)
    generation = core.initialize_population()
    workspace = core.workspace

    initial_candidates = (
        list(generation.individuals) + list(workspace.free_population)
    )
    candidate_ids = {id(individual) for individual in initial_candidates}
    assert len(candidate_ids) == 2 * core.population_size
    state_container_ids = {
        id(individual): (
            id(individual.positions),
            id(individual.transfer_mask),
            tuple(id(route) for route in individual.routes),
        )
        for individual in initial_candidates
    }
    reference_list_ids = {
        id(generation.individuals),
        id(workspace.free_population),
        id(workspace.spare_population_refs),
    }
    assert len(reference_list_ids) == 3

    saw_external_elite = False
    for _ in range(6):
        generation = core._new_generation(generation, 1.0)
        active_ids = {id(value) for value in generation.individuals}
        free_ids = {id(value) for value in workspace.free_population}

        assert workspace.active_population is generation.individuals
        assert len(active_ids) == core.population_size
        assert len(free_ids) == core.population_size
        assert active_ids.isdisjoint(free_ids)
        assert active_ids | free_ids == candidate_ids
        assert {
            id(workspace.active_population),
            id(workspace.free_population),
            id(workspace.spare_population_refs),
        } == reference_list_ids
        if generation.best_index == -1:
            saw_external_elite = True
            assert generation.best_solution is workspace.elite

    assert saw_external_elite
    for individual in (
        list(workspace.active_population) + list(workspace.free_population)
    ):
        assert state_container_ids[id(individual)] == (
            id(individual.positions),
            id(individual.transfer_mask),
            tuple(id(route) for route in individual.routes),
        )


def test_population_pool_six_transitions_match_cdels_bit_for_bit() -> None:
    baseline = _solve(CDELS(_problem(), seed=1), transitions=6)
    workspace = _solve(CDELSWorkspace(_problem(), seed=1), transitions=6)

    assert workspace.process_trace_sha256 == baseline.process_trace_sha256
    assert [item.canonical_digest for item in workspace.process_trace] == [
        item.canonical_digest for item in baseline.process_trace
    ]
    assert workspace.rng_state == baseline.rng_state
    assert workspace.rng_draw_count == baseline.rng_draw_count


@pytest.mark.slow
def test_population_pool_matches_through_first_cooling_boundary() -> None:
    baseline = _solve(CDELS(_problem(), seed=1), transitions=111)
    workspace = _solve(CDELSWorkspace(_problem(), seed=1), transitions=111)

    assert workspace.process_trace_sha256 == baseline.process_trace_sha256
    assert workspace.final_temperature.hex() == baseline.final_temperature.hex()
    assert workspace.result.objective == baseline.result.objective
    assert workspace.result.routes == baseline.result.routes
    assert workspace.result.transferred_customers == (
        baseline.result.transferred_customers
    )
    assert workspace.rng_state == baseline.rng_state
    assert workspace.rng_draw_count == baseline.rng_draw_count
