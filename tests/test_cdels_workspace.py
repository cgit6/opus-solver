from __future__ import annotations

from pathlib import Path

import numpy as np

from mkp.problem.scvrp import load_legacy_scvrp_problem
from mkp.solver.CDELS import CDELS
from mkp.solver.CDELS_workspace import CDELSWorkspace


FIXTURES = Path(__file__).parent / "fixtures" / "scvrp"


def _problem():
    return load_legacy_scvrp_problem(
        FIXTURES / "p_n16_k8.vrp",
        FIXTURES / "p_n16_k8_routecap2_transfer1.txt",
        dataset="P",
        problem_id="P-n16-k8-routecap2-transfer1",
        best_known=350,
    )


def _solve(core):
    return core.solve(
        termination_mode="fixed_iterations",
        limit=2,
        start_temperature=1.0,
        cooling_rate=0.95,
        iterations_per_temperature=110,
        max_transitions=2,
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
