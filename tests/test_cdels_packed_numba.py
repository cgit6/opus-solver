from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pytest

from mkp.problem.scvrp import load_legacy_scvrp_problem
from mkp.solver.CDELS_numba import CDELSNumba
from mkp.solver.CDELS_packed_numba import (
    CDELSPackedNumba,
    _packed_generation_numba,
    _packed_generations_numba,
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


def test_packed_population_round_trip_preserves_initial_process_state() -> None:
    problem = _problem()
    reference = CDELSNumba(problem, seed=1)
    packed = CDELSPackedNumba(problem, seed=1)

    reference_generation = reference.initialize_population()
    packed_generation = packed.initialize_population()
    packed._pack_generation(packed_generation)
    restored = packed._unpack_generation()

    assert packed.process_trace_generation(restored) == (
        reference.process_trace_generation(reference_generation)
    )
    assert packed.rng.state == reference.rng.state
    assert packed.rng.draw_count == reference.rng.draw_count


def test_packed_population_uses_compressed_storage_types() -> None:
    packed = CDELSPackedNumba(_problem(), seed=1)

    assert packed._packed_current.route_customers.dtype == np.uint16
    assert packed._packed_current.route_offsets.dtype == np.uint16
    assert packed._packed_current.positions.dtype == np.uint16
    assert packed._packed_current.transfer_mask.dtype == np.uint8
    assert packed._packed_current.costs.dtype == np.int64
    assert packed.packed_population_nbytes > 0


def test_packed_whole_generation_matches_numba_process_state() -> None:
    problem = _problem()
    reference = CDELSNumba(problem, seed=1)
    packed = CDELSPackedNumba(problem, seed=1)

    reference_generation = reference.initialize_population()
    packed_initial = packed.initialize_population()
    packed._pack_generation(packed_initial)

    reference_next = reference._new_generation(reference_generation, 1.0)
    packed._advance_packed_generation(1.0)
    packed_next = packed._unpack_generation()

    assert packed.process_trace_generation(packed_next) == (
        reference.process_trace_generation(reference_next)
    )
    assert packed.rng.state == reference.rng.state
    assert packed.rng.draw_count == reference.rng.draw_count
    assert _packed_generation_numba.nopython_signatures


def test_packed_solve_matches_numba_for_111_transitions_with_full_trace() -> None:
    problem = _problem()
    reference = CDELSNumba(problem, seed=1).solve(
        termination_mode="fixed_iterations",
        limit=111,
        start_temperature=1.0,
        cooling_rate=0.95,
        iterations_per_temperature=110,
        max_transitions=111,
        trace=True,
        process_trace=True,
    )
    packed = CDELSPackedNumba(problem, seed=1).solve(
        termination_mode="fixed_iterations",
        limit=111,
        start_temperature=1.0,
        cooling_rate=0.95,
        iterations_per_temperature=110,
        max_transitions=111,
        trace=True,
        process_trace=True,
    )

    assert packed.result == reference.result
    assert packed.trace == reference.trace
    assert packed.process_trace == reference.process_trace
    assert packed.process_trace_sha256 == reference.process_trace_sha256
    assert packed.generation_count == reference.generation_count
    assert packed.transition_count == reference.transition_count
    assert packed.temperature_stagnation == reference.temperature_stagnation
    assert packed.final_temperature.hex() == reference.final_temperature.hex()
    assert packed.rng_state == reference.rng_state
    assert packed.rng_draw_count == reference.rng_draw_count


@pytest.mark.parametrize("transition_count", (7, 111, 221))
def test_packed_solve_without_trace_has_same_final_population(
    transition_count: int,
) -> None:
    problem = _problem()
    reference_core = CDELSNumba(problem, seed=30)
    packed_core = CDELSPackedNumba(problem, seed=30)
    reference = reference_core.solve(
        termination_mode="fixed_iterations",
        limit=transition_count,
        max_transitions=transition_count,
    )
    packed = packed_core.solve(
        termination_mode="fixed_iterations",
        limit=transition_count,
        max_transitions=transition_count,
    )

    assert packed_core.process_trace_generation(packed.generation) == (
        reference_core.process_trace_generation(reference.generation)
    )
    assert packed.result == reference.result
    assert packed.rng_state == reference.rng_state
    assert packed.rng_draw_count == reference.rng_draw_count


def test_packed_batched_solve_preserves_legacy_safety_stop() -> None:
    problem = _problem()
    reference_core = CDELSNumba(problem, seed=1)
    packed_core = CDELSPackedNumba(problem, seed=1)
    solve_args = {
        "termination_mode": "legacy_temperature_stagnation",
        "limit": 100,
        "iterations_per_temperature": 110,
        "max_transitions": 111,
    }
    reference = reference_core.solve(**solve_args)
    packed = packed_core.solve(**solve_args)

    assert packed.stop_cause == reference.stop_cause == "max_transitions"
    assert packed_core.process_trace_generation(packed.generation) == (
        reference_core.process_trace_generation(reference.generation)
    )
    assert packed.final_temperature.hex() == reference.final_temperature.hex()
    assert packed.rng_state == reference.rng_state
    assert packed.rng_draw_count == reference.rng_draw_count


@pytest.mark.parametrize("transition_count", (1, 2, 7, 110))
def test_packed_batch_matches_repeated_single_generations(
    transition_count: int,
) -> None:
    problem = _problem()
    repeated = CDELSPackedNumba(problem, seed=1)
    batched = CDELSPackedNumba(problem, seed=1)
    repeated_initial = repeated.initialize_population()
    batched_initial = batched.initialize_population()
    repeated._pack_generation(repeated_initial)
    batched._pack_generation(batched_initial)

    for _ in range(transition_count):
        repeated._advance_packed_generation(1.0)
    batched._advance_packed_generations(1.0, transition_count)

    assert batched.process_trace_generation(batched._unpack_generation()) == (
        repeated.process_trace_generation(repeated._unpack_generation())
    )
    assert batched.rng.state == repeated.rng.state
    assert batched.rng.draw_count == repeated.rng.draw_count
    assert batched._next_generation_id == repeated._next_generation_id
    assert _packed_generations_numba.nopython_signatures


@pytest.mark.slow
@pytest.mark.skipif(
    os.environ.get("SCVRP_FULL_REPLAY") != "1",
    reason="set SCVRP_FULL_REPLAY=1 to run the exact 11220-transition replay",
)
def test_packed_full_seed_one_trace_matches_cpp_derived_fingerprint() -> None:
    result = CDELSPackedNumba(_problem(), seed=1).solve(
        termination_mode="fixed_iterations",
        limit=11_220,
        max_transitions=11_220,
        trace=True,
        process_trace=True,
    )

    assert len(result.process_trace) == 11_221
    assert result.process_trace_sha256 == (
        "2a6adf93d6f20b37fc18fbef1831dffa83a8c8b9d97b6edcf30cb44d6f07aa1e"
    )
    assert result.generation_count == 11_221
    assert result.transition_count == 11_220
    assert result.rng_state == 3_106_006_966
    assert result.rng_draw_count == 9_603_103
    assert result.final_temperature.hex() == "0x1.5e2d52a31c76bp-8"
    assert result.result.objective == 350
    assert result.result.feasible is True
    assert result.result.feasible_solutions == 48
    assert result.result.transfer_vehicle_count == 3
    assert result.result.routes == (
        (13, 8, 10, 9),
        (5,),
        (15, 4, 2),
        (6,),
        (3, 12),
        (),
        (1,),
        (14, 7, 11),
    )
    assert result.result.transferred_customers == (1, 2, 5, 9, 10, 11, 13, 15)
