from __future__ import annotations

import os
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
import struct

import pytest

from mkp.problem.scvrp import load_legacy_scvrp_problem
from mkp.solver.CDELS import (
    CDELS,
    CDELSGeneration,
    CDELSSnapshot,
)
from mkp.tools.scvrp_native_oracle import (
    SCVRPLegacyKernelRequest,
    build_scvrp_legacy_kernel,
    run_scvrp_legacy_generation_probe,
    run_scvrp_legacy_kernel,
)


FIXTURES = Path(__file__).parent / "fixtures" / "scvrp"


@pytest.fixture(scope="module")
def problem():
    return load_legacy_scvrp_problem(
        FIXTURES / "p_n16_k8.vrp",
        FIXTURES / "p_n16_k8_routecap2_transfer1.txt",
        dataset="P",
        problem_id="P-n16-k8-routecap2-transfer1",
        best_known=350,
    )


@pytest.fixture(scope="module")
def native_kernel() -> Path:
    return build_scvrp_legacy_kernel()


def _snapshot_dict(snapshot: CDELSSnapshot) -> dict[str, object]:
    return {
        "generation": snapshot.generation,
        "objective": snapshot.objective,
        "feasible_solutions": snapshot.feasible_solutions,
        "feasible": snapshot.feasible,
        "transfer_vehicle_count": snapshot.transfer_vehicle_count,
        "routes": [list(route) for route in snapshot.routes],
        "transferred_customers": list(snapshot.transferred_customers),
    }


def _assert_loop_result_matches_native(python_result, native: dict[str, object]) -> None:
    assert python_result.termination == native["termination"]
    assert python_result.stop_cause == native["stop_cause"]
    assert python_result.generation_count == native["generation_count"]
    assert python_result.transition_count == native["transition_count"]
    assert python_result.temperature_stagnation == native["temperature_stagnation"]
    assert python_result.final_temperature == float.fromhex(
        str(native["final_temperature_hex"])
    )
    assert python_result.rng_state == native["rng_state"]
    assert python_result.rng_draw_count == native["rng_draw_count"]
    assert _snapshot_dict(python_result.result) == native["result"]
    assert [_snapshot_dict(snapshot) for snapshot in python_result.trace] == native["trace"]


def _append_native_individual(payload: bytearray, individual: dict[str, object]) -> None:
    routes = individual["routes"]
    assert isinstance(routes, list)
    for route in routes:
        assert isinstance(route, list)
        payload.extend(struct.pack("<I", len(route)))
        if route:
            payload.extend(struct.pack(f"<{len(route)}i", *route))

    positions = individual["positions"]
    assert isinstance(positions, list) and len(positions) == 2
    flattened_positions = [value for axis in positions for value in axis]
    payload.extend(
        struct.pack(f"<{len(flattened_positions)}i", *flattened_positions)
    )
    transfer_mask = individual["transfer_mask"]
    assert isinstance(transfer_mask, list)
    payload.extend(struct.pack(f"<{len(transfer_mask)}i", *transfer_mask))
    payload.extend(
        struct.pack(
            "<iB",
            individual["cost"],
            int(individual["feasible"]),
        )
    )
    route_capacities = individual["route_capacities_free"]
    assert isinstance(route_capacities, list)
    payload.extend(
        struct.pack(f"<{len(route_capacities)}i", *route_capacities)
    )
    transfer_capacities = individual["transfer_capacities_free"]
    assert isinstance(transfer_capacities, list)
    payload.extend(
        struct.pack(f"<{len(transfer_capacities)}i", *transfer_capacities)
    )
    payload.extend(
        struct.pack(
            "<ii",
            individual["transfer_vehicle_count"],
            individual["transfer_total_capacity_free"],
        )
    )


def _digest_native_generation(generation: dict[str, object]) -> str:
    individuals = generation["individuals"]
    best = generation["best"]
    rng = generation["rng"]
    assert isinstance(individuals, list) and individuals
    assert isinstance(best, dict)
    assert isinstance(rng, dict)
    customer_count = len(best["transfer_mask"])
    route_count = len(best["routes"])
    transfer_route_count = len(best["transfer_capacities_free"])
    payload = bytearray(b"SCVRP_FULL_POP_V1")
    payload.extend(
        struct.pack(
            "<iIIIIiiIQ",
            generation["generation_id"],
            len(individuals),
            customer_count,
            route_count,
            transfer_route_count,
            generation["feasible_solutions"],
            generation["best_index"],
            rng["state"],
            rng["draw_count"],
        )
    )
    for individual in individuals:
        assert isinstance(individual, dict)
        _append_native_individual(payload, individual)
    _append_native_individual(payload, best)
    return sha256(payload).hexdigest()


def _assert_process_trace_matches_native(python_result, native: dict[str, object]) -> None:
    native_process = native["process_trace"]
    assert isinstance(native_process, dict)
    assert native_process["schema"] == "SCVRP_FULL_POP_V1"
    assert native_process["trace_schema"] == "SCVRP_FULL_TRACE_V1"
    assert native_process["algorithm"] == "sha256"
    assert [
        entry.canonical_digest for entry in python_result.process_trace
    ] == native_process["generation_digests"]
    assert python_result.process_trace_sha256 == native_process["trace_sha256"]
    assert [
        {
            "generation": entry.generation,
            "canonical_digest": entry.canonical_digest,
            "rng_state": entry.rng_state,
            "rng_draw_count": entry.rng_draw_count,
        }
        for entry in python_result.process_trace
    ] == native_process["generations"]
    assert [entry.generation for entry in python_result.process_trace] == list(
        range(1, python_result.generation_count + 1)
    )


@pytest.mark.parametrize("transitions", (0, 1, 6))
def test_python_fixed_loop_matches_native_for_bounded_runs(
    problem,
    native_kernel: Path,
    transitions: int,
) -> None:
    max_transitions = max(1, transitions)
    python_result = CDELS(problem, seed=1).solve(
        termination_mode="fixed_iterations",
        limit=transitions,
        max_transitions=max_transitions,
        trace=True,
    )
    native = run_scvrp_legacy_kernel(
        problem,
        SCVRPLegacyKernelRequest(
            seed=1,
            termination_mode="fixed_iterations",
            limit=transitions,
            max_transitions=max_transitions,
            trace=True,
        ),
        executable=native_kernel,
    )

    _assert_loop_result_matches_native(python_result, native)


@pytest.mark.parametrize(
    ("seed", "transitions", "iterations_per_temperature"),
    ((1, 6, 110), (2, 3, 2)),
)
def test_process_trace_matches_python_native_and_full_state_oracle(
    problem,
    native_kernel: Path,
    seed: int,
    transitions: int,
    iterations_per_temperature: int,
) -> None:
    python_result = CDELS(problem, seed=seed).solve(
        termination_mode="fixed_iterations",
        limit=transitions,
        iterations_per_temperature=iterations_per_temperature,
        max_transitions=transitions,
        trace=True,
        process_trace=True,
    )
    native = run_scvrp_legacy_kernel(
        problem,
        SCVRPLegacyKernelRequest(
            seed=seed,
            termination_mode="fixed_iterations",
            limit=transitions,
            iterations_per_temperature=iterations_per_temperature,
            max_transitions=transitions,
            trace=True,
            process_trace=True,
        ),
        executable=native_kernel,
    )
    full_state_oracle = run_scvrp_legacy_generation_probe(
        problem,
        SCVRPLegacyKernelRequest(
            seed=seed,
            termination_mode="fixed_iterations",
            limit=transitions,
            iterations_per_temperature=iterations_per_temperature,
            probe_new_generation=True,
        ),
        executable=native_kernel,
    )

    _assert_loop_result_matches_native(python_result, native)
    _assert_process_trace_matches_native(python_result, native)
    assert [
        entry.canonical_digest for entry in python_result.process_trace
    ] == [
        _digest_native_generation(generation)
        for generation in full_state_oracle["trace"]
    ]


def test_process_trace_is_observationally_pure(
    problem,
    native_kernel: Path,
) -> None:
    ordinary_python = CDELS(problem, seed=1).solve(
        termination_mode="fixed_iterations",
        limit=6,
        max_transitions=6,
        trace=True,
    )
    traced_python = CDELS(problem, seed=1).solve(
        termination_mode="fixed_iterations",
        limit=6,
        max_transitions=6,
        trace=True,
        process_trace=True,
    )
    ordinary_native = run_scvrp_legacy_kernel(
        problem,
        SCVRPLegacyKernelRequest(
            seed=1,
            termination_mode="fixed_iterations",
            limit=6,
            max_transitions=6,
            trace=True,
        ),
        executable=native_kernel,
    )
    traced_native = run_scvrp_legacy_kernel(
        problem,
        SCVRPLegacyKernelRequest(
            seed=1,
            termination_mode="fixed_iterations",
            limit=6,
            max_transitions=6,
            trace=True,
            process_trace=True,
        ),
        executable=native_kernel,
    )

    assert ordinary_python.result == traced_python.result
    assert ordinary_python.trace == traced_python.trace
    assert ordinary_python.rng_state == traced_python.rng_state
    assert ordinary_python.rng_draw_count == traced_python.rng_draw_count
    assert ordinary_python.final_temperature == traced_python.final_temperature
    assert ordinary_python.process_trace == ()
    assert ordinary_python.process_trace_sha256 is None
    for field in (
        "termination",
        "stop_cause",
        "generation_count",
        "transition_count",
        "temperature_stagnation",
        "final_temperature_hex",
        "rng_state",
        "rng_draw_count",
        "result",
        "trace",
    ):
        assert ordinary_native[field] == traced_native[field]


def test_process_trace_schema_vector_and_field_sensitivity(
    problem,
    native_kernel: Path,
) -> None:
    core = CDELS(problem, seed=1)
    generation = core.initialize_population()
    baseline = core.process_trace_generation(generation)
    native = run_scvrp_legacy_kernel(
        problem,
        SCVRPLegacyKernelRequest(
            seed=1,
            termination_mode="fixed_iterations",
            limit=0,
            max_transitions=1,
            process_trace=True,
        ),
        executable=native_kernel,
    )

    assert baseline.canonical_digest == (
        "0dc594e5b7c0b36045ec0f514ef795abd41ebab330de7b85d09d669aa29c1939"
    )
    assert native["process_trace"]["generation_digests"] == [
        baseline.canonical_digest
    ]
    assert native["process_trace"]["trace_sha256"] == (
        "773468a3a4cd3115a7b8c8e34e4ee98dda3b8e95e5c6b98d2e5d3376a36d4eff"
    )

    mutations = []

    changed = deepcopy(generation)
    changed.generation_id += 1
    mutations.append(changed)

    changed = deepcopy(generation)
    changed.feasible_solutions += 1
    mutations.append(changed)

    changed = deepcopy(generation)
    route = next(route for route in changed.individuals[0].routes if len(route) > 1)
    route.reverse()
    mutations.append(changed)

    changed = deepcopy(generation)
    changed.individuals[0].positions[0, 1] += 1
    mutations.append(changed)

    changed = deepcopy(generation)
    changed.individuals[0].transfer_mask[1] = 1
    mutations.append(changed)

    for field in (
        "cost",
        "transfer_vehicle_count",
        "transfer_total_capacity_free",
    ):
        changed = deepcopy(generation)
        setattr(changed.individuals[0], field, getattr(changed.individuals[0], field) + 1)
        mutations.append(changed)

    changed = deepcopy(generation)
    changed.individuals[0].feasible = not changed.individuals[0].feasible
    mutations.append(changed)

    changed = deepcopy(generation)
    changed.individuals[0].route_capacities_free[0] -= 1
    mutations.append(changed)

    changed = deepcopy(generation)
    changed.individuals[0].transfer_capacities_free[0] -= 1
    mutations.append(changed)

    changed = deepcopy(generation)
    changed.best_solution = core._make_hard_clone(changed.best_solution)
    assert changed.best_index == -1
    mutations.append(changed)

    assert all(
        core.process_trace_generation(changed).canonical_digest
        != baseline.canonical_digest
        for changed in mutations
    )

    core.rng.srand(2)
    assert (
        core.process_trace_generation(generation).canonical_digest
        != baseline.canonical_digest
    )


def test_process_trace_rejects_malformed_canonical_state(problem) -> None:
    core = CDELS(problem, seed=1)
    generation = core.initialize_population()

    malformed = deepcopy(generation)
    malformed.individuals.pop()
    with pytest.raises(ValueError, match="population size"):
        core.process_trace_generation(malformed)

    malformed = deepcopy(generation)
    malformed.individuals[0].routes.pop()
    with pytest.raises(ValueError, match="route count"):
        core.process_trace_generation(malformed)

    malformed = deepcopy(generation)
    first = malformed.individuals[0]
    first.routes[0][0] = first.routes[1][0]
    with pytest.raises(ValueError, match="each customer exactly once"):
        core.process_trace_generation(malformed)

    malformed = deepcopy(generation)
    malformed.individuals[0].positions = malformed.individuals[0].positions[:, :-1]
    with pytest.raises(ValueError, match="positions shape"):
        core.process_trace_generation(malformed)

    malformed = deepcopy(generation)
    malformed.individuals[0].transfer_mask[1] = 2
    with pytest.raises(ValueError, match="only 0/1"):
        core.process_trace_generation(malformed)

    malformed = deepcopy(generation)
    malformed.individuals[0].transfer_mask = malformed.individuals[0].transfer_mask[:-1]
    with pytest.raises(ValueError, match="transfer mask length"):
        core.process_trace_generation(malformed)

    malformed = deepcopy(generation)
    malformed.individuals[0].route_capacities_free.pop()
    with pytest.raises(ValueError, match="route capacity length"):
        core.process_trace_generation(malformed)

    malformed = deepcopy(generation)
    malformed.individuals[0].transfer_capacities_free.pop()
    with pytest.raises(ValueError, match="transfer capacity length"):
        core.process_trace_generation(malformed)

    malformed = deepcopy(generation)
    malformed.individuals[0].feasible = 1
    with pytest.raises(ValueError, match="feasible flag"):
        core.process_trace_generation(malformed)

    malformed = deepcopy(generation)
    best_index = malformed.best_index
    duplicate_index = 0 if best_index != 0 else 1
    malformed.individuals[duplicate_index] = malformed.best_solution
    with pytest.raises(ValueError, match="multiple population slots"):
        core.process_trace_generation(malformed)


def test_python_legacy_loop_matches_native_at_safety_stop(
    problem,
    native_kernel: Path,
) -> None:
    python_result = CDELS(problem, seed=1).solve(
        termination_mode="legacy_temperature_stagnation",
        limit=100,
        max_transitions=1,
        trace=True,
    )
    native = run_scvrp_legacy_kernel(
        problem,
        SCVRPLegacyKernelRequest(
            seed=1,
            termination_mode="legacy_temperature_stagnation",
            limit=100,
            max_transitions=1,
            trace=True,
        ),
        executable=native_kernel,
    )

    _assert_loop_result_matches_native(python_result, native)
    assert python_result.stop_cause == "max_transitions"
    assert python_result.final_temperature == 1.0


def test_python_legacy_loop_matches_native_when_safety_hits_complete_level(
    problem,
    native_kernel: Path,
) -> None:
    python_result = CDELS(problem, seed=1).solve(
        termination_mode="legacy_temperature_stagnation",
        limit=100,
        iterations_per_temperature=2,
        max_transitions=2,
        trace=True,
    )
    native = run_scvrp_legacy_kernel(
        problem,
        SCVRPLegacyKernelRequest(
            seed=1,
            termination_mode="legacy_temperature_stagnation",
            limit=100,
            iterations_per_temperature=2,
            max_transitions=2,
            trace=True,
        ),
        executable=native_kernel,
    )

    _assert_loop_result_matches_native(python_result, native)
    assert python_result.stop_cause == "max_transitions"
    assert python_result.temperature_stagnation == 0
    assert python_result.final_temperature == 1.0


@pytest.mark.parametrize(
    ("seed", "expected_transitions"),
    ((1, 6), (2, 4), (3, 3)),
)
def test_python_natural_stagnation_stop_matches_native(
    problem,
    native_kernel: Path,
    seed: int,
    expected_transitions: int,
) -> None:
    python_result = CDELS(problem, seed=seed).solve(
        termination_mode="legacy_temperature_stagnation",
        limit=0,
        iterations_per_temperature=1,
        max_transitions=20,
        trace=True,
    )
    native = run_scvrp_legacy_kernel(
        problem,
        SCVRPLegacyKernelRequest(
            seed=seed,
            termination_mode="legacy_temperature_stagnation",
            limit=0,
            iterations_per_temperature=1,
            max_transitions=20,
            trace=True,
        ),
        executable=native_kernel,
    )

    _assert_loop_result_matches_native(python_result, native)
    assert python_result.stop_cause == "legacy_temperature_stagnation"
    assert python_result.transition_count == expected_transitions


@pytest.mark.parametrize("seed", (1, 2))
@pytest.mark.parametrize("transitions", (2, 3))
def test_python_loop_matches_native_across_compressed_cooling_boundary(
    problem,
    native_kernel: Path,
    seed: int,
    transitions: int,
) -> None:
    python_result = CDELS(problem, seed=seed).solve(
        termination_mode="fixed_iterations",
        limit=transitions,
        iterations_per_temperature=2,
        max_transitions=transitions,
        trace=True,
    )
    native = run_scvrp_legacy_kernel(
        problem,
        SCVRPLegacyKernelRequest(
            seed=seed,
            termination_mode="fixed_iterations",
            limit=transitions,
            iterations_per_temperature=2,
            max_transitions=transitions,
            trace=True,
        ),
        executable=native_kernel,
    )

    _assert_loop_result_matches_native(python_result, native)
    assert python_result.final_temperature.hex() == "0x1.e666666666666p-1"


def test_python_loop_matches_native_after_temperature_underflows_to_zero(
    problem,
    native_kernel: Path,
) -> None:
    smallest_positive_float = float.fromhex("0x0.0000000000001p-1022")
    python_result = CDELS(problem, seed=1).solve(
        termination_mode="fixed_iterations",
        limit=3,
        cooling_rate=smallest_positive_float,
        iterations_per_temperature=1,
        max_transitions=3,
        trace=True,
    )
    native = run_scvrp_legacy_kernel(
        problem,
        SCVRPLegacyKernelRequest(
            seed=1,
            termination_mode="fixed_iterations",
            limit=3,
            cooling_rate=smallest_positive_float,
            iterations_per_temperature=1,
            max_transitions=3,
            trace=True,
        ),
        executable=native_kernel,
    )

    _assert_loop_result_matches_native(python_result, native)
    assert python_result.final_temperature == 0.0


@pytest.mark.slow
@pytest.mark.parametrize("transitions", (110, 111))
def test_python_fixed_loop_matches_native_across_first_cooling_boundary(
    problem,
    native_kernel: Path,
    transitions: int,
) -> None:
    python_result = CDELS(problem, seed=1).solve(
        termination_mode="fixed_iterations",
        limit=transitions,
        max_transitions=transitions,
        trace=True,
    )
    native = run_scvrp_legacy_kernel(
        problem,
        SCVRPLegacyKernelRequest(
            seed=1,
            termination_mode="fixed_iterations",
            limit=transitions,
            max_transitions=transitions,
            trace=True,
        ),
        executable=native_kernel,
    )

    _assert_loop_result_matches_native(python_result, native)
    assert python_result.final_temperature.hex() == "0x1.e666666666666p-1"


@pytest.mark.slow
@pytest.mark.skipif(
    os.environ.get("SCVRP_FULL_REPLAY") != "1",
    reason="set SCVRP_FULL_REPLAY=1 to run the ~8 minute exact replay",
)
def test_python_full_fixed_seed_one_trace_matches_native(
    problem,
    native_kernel: Path,
) -> None:
    """Long-form oracle: run separately when full replay evidence is needed."""
    python_result = CDELS(problem, seed=1).solve(
        termination_mode="fixed_iterations",
        limit=11_220,
        max_transitions=11_220,
        trace=True,
        process_trace=True,
    )
    native = run_scvrp_legacy_kernel(
        problem,
        SCVRPLegacyKernelRequest(
            seed=1,
            termination_mode="fixed_iterations",
            limit=11_220,
            max_transitions=11_220,
            trace=True,
            process_trace=True,
        ),
        executable=native_kernel,
        timeout=180.0,
    )

    _assert_loop_result_matches_native(python_result, native)
    _assert_process_trace_matches_native(python_result, native)
    assert len(python_result.process_trace) == 11_221
    assert python_result.process_trace_sha256 == (
        "2a6adf93d6f20b37fc18fbef1831dffa83a8c8b9d97b6edcf30cb44d6f07aa1e"
    )
    assert python_result.generation_count == 11_221
    assert python_result.rng_state == 3_106_006_966
    assert python_result.rng_draw_count == 9_603_103
    assert python_result.final_temperature.hex() == "0x1.5e2d52a31c76bp-8"


def _replace_transition_with_noop(core: CDELS, monkeypatch) -> list[float]:
    temperatures: list[float] = []

    def transition(
        generation: CDELSGeneration,
        temperature: float,
    ) -> CDELSGeneration:
        temperatures.append(temperature)
        return CDELSGeneration(
            individuals=generation.individuals,
            best_solution=generation.best_solution,
            feasible_solutions=generation.feasible_solutions,
            generation_id=core._take_generation_id(),
        )

    monkeypatch.setattr(core, "_new_generation", transition)
    return temperatures


@pytest.mark.parametrize(
    ("transitions", "expected_temperature", "expected_stagnation"),
    (
        (109, 1.0, 0),
        (110, 0.95, 1),
        (111, 0.95, 1),
    ),
)
def test_fixed_partial_level_cools_only_after_a_complete_level(
    problem,
    monkeypatch,
    transitions: int,
    expected_temperature: float,
    expected_stagnation: int,
) -> None:
    core = CDELS(problem, seed=1)
    observed_temperatures = _replace_transition_with_noop(core, monkeypatch)

    result = core.solve(
        termination_mode="fixed_iterations",
        limit=transitions,
        max_transitions=transitions,
    )

    assert result.transition_count == transitions
    assert result.final_temperature == expected_temperature
    assert result.temperature_stagnation == expected_stagnation
    assert observed_temperatures[:110] == [1.0] * min(transitions, 110)
    assert observed_temperatures[110:] == [0.95] * max(0, transitions - 110)


def test_safety_stop_at_complete_level_suppresses_cooling(
    problem,
    monkeypatch,
) -> None:
    core = CDELS(problem, seed=1)
    _replace_transition_with_noop(core, monkeypatch)

    result = core.solve(
        termination_mode="legacy_temperature_stagnation",
        limit=100,
        iterations_per_temperature=110,
        max_transitions=110,
    )

    assert result.stop_cause == "max_transitions"
    assert result.transition_count == 110
    assert result.temperature_stagnation == 0
    assert result.final_temperature == 1.0


def test_legacy_stagnation_stops_only_after_counter_exceeds_limit(
    problem,
    monkeypatch,
) -> None:
    core = CDELS(problem, seed=1)
    observed_temperatures = _replace_transition_with_noop(core, monkeypatch)

    result = core.solve(
        termination_mode="legacy_temperature_stagnation",
        limit=2,
        iterations_per_temperature=3,
        max_transitions=20,
        cooling_rate=0.5,
        trace=True,
    )

    assert result.stop_cause == "legacy_temperature_stagnation"
    assert result.transition_count == 9
    assert result.generation_count == 10
    assert result.temperature_stagnation == 3
    assert result.final_temperature == 0.125
    assert observed_temperatures == [1.0] * 3 + [0.5] * 3 + [0.25] * 3
    assert len(result.trace) == 10
    assert [snapshot.generation for snapshot in result.trace] == list(range(1, 11))


def test_full_legacy_schedule_matches_archive_transition_and_temperature_counts(
    problem,
    monkeypatch,
) -> None:
    core = CDELS(problem, seed=1)
    transitions = 0

    def improve_once_then_stagnate(
        generation: CDELSGeneration,
        temperature: float,
    ) -> CDELSGeneration:
        nonlocal transitions
        del temperature
        transitions += 1
        if transitions == 1:
            generation.best_solution.cost -= 1
        return CDELSGeneration(
            individuals=generation.individuals,
            best_solution=generation.best_solution,
            feasible_solutions=generation.feasible_solutions,
            generation_id=core._take_generation_id(),
        )

    monkeypatch.setattr(core, "_new_generation", improve_once_then_stagnate)

    result = core.solve(
        termination_mode="legacy_temperature_stagnation",
        limit=100,
        iterations_per_temperature=110,
        max_transitions=11_330,
        cooling_rate=0.95,
    )

    assert result.stop_cause == "legacy_temperature_stagnation"
    assert result.transition_count == 11_220
    assert result.generation_count == 11_221
    assert result.temperature_stagnation == 101
    assert result.final_temperature.hex() == "0x1.5e2d52a31c76bp-8"


@pytest.mark.parametrize(
    ("kwargs", "message"),
    (
        ({"termination_mode": "other", "limit": 1}, "unsupported termination_mode"),
        ({"termination_mode": "fixed_iterations", "limit": True}, "limit"),
        (
            {
                "termination_mode": "fixed_iterations",
                "limit": 1,
                "process_trace": 1,
            },
            "process_trace",
        ),
        (
            {
                "termination_mode": "fixed_iterations",
                "limit": 2,
                "max_transitions": 1,
            },
            "cannot exceed",
        ),
        (
            {
                "termination_mode": "fixed_iterations",
                "limit": 1,
                "start_temperature": 0.0,
            },
            "start_temperature",
        ),
    ),
)
def test_temperature_loop_rejects_invalid_control_values(
    problem,
    kwargs: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        CDELS(problem, seed=1).solve(**kwargs)
