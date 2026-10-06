from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import numpy as np
import pytest

from mkp.problem.scvrp import load_legacy_scvrp_problem
from mkp.solver.CDELS import (
    CDELS,
    CDELSGeneration,
    MSVCRandom,
    _build_positions,
)
from mkp.solver.CDELS_numba import (
    CDELSNumba,
    _accept_trial_by_sa_numba,
    _crossover_numba,
    _generate_new_mutant_numba,
    _local_search_numba,
    _msvc_rand_mod_numba,
    _msvc_rand_numba,
    _reevaluate_packed_numba,
    _select_mutation_indices_numba,
    _select_trial_by_sa_numba,
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


def _solve(core, *, iterations: int):
    return core.solve(
        termination_mode="fixed_iterations",
        limit=iterations,
        start_temperature=1.0,
        cooling_rate=0.95,
        iterations_per_temperature=110,
        max_transitions=max(1, iterations),
        trace=True,
        process_trace=True,
    )


def _target_zero_trial(core):
    generation = core.initialize_population()
    mutant = core._mutation(generation, 0)
    trial = core._crossover(generation.individuals[0], mutant)
    core._reevaluate(trial)
    return trial


def _replace_transition_with_noop(core):
    observed_temperatures = []

    def transition(generation, temperature):
        observed_temperatures.append(temperature)
        return CDELSGeneration(
            individuals=generation.individuals,
            best_solution=generation.best_solution,
            feasible_solutions=generation.feasible_solutions,
            generation_id=core._take_generation_id(),
        )

    core._new_generation = transition
    return observed_temperatures


def test_cdels_numba_msvc_rng_fingerprint_matches_python() -> None:
    for seed in (1, 2, 30_091, 0xFFFF_FFFF):
        reference = MSVCRandom(seed)
        state = seed & 0xFFFF_FFFF
        draw_count = 0
        for _ in range(10_000):
            state, draw_count, value = _msvc_rand_numba(state, draw_count)
            assert value == reference.rand()
            assert state == reference.state
            assert draw_count == reference.draw_count

    reference = MSVCRandom(7)
    state = 7
    draw_count = 0
    for modulus in tuple(range(1, 128)) * 4:
        state, draw_count, value = _msvc_rand_mod_numba(
            state,
            draw_count,
            modulus,
        )
        assert value == reference.rand_mod(modulus)
        assert state == reference.state
        assert draw_count == reference.draw_count
    assert _msvc_rand_numba.nopython_signatures
    assert _msvc_rand_mod_numba.nopython_signatures


def test_cdels_numba_reevaluate_matches_python_state() -> None:
    problem = _problem()
    python_core = CDELS(problem, seed=1)
    numba_core = CDELSNumba(problem, seed=1)
    generation = python_core.initialize_population()

    cases = [deepcopy(source) for source in generation.individuals[:6]]

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
        python_individual = deepcopy(source)
        numba_individual = deepcopy(source)
        python_evaluation = python_core._reevaluate(python_individual)
        numba_evaluation = numba_core._reevaluate(numba_individual)

        assert numba_individual.canonical_dict() == python_individual.canonical_dict()
        assert numba_evaluation == python_evaluation

    assert _reevaluate_packed_numba.nopython_signatures


def test_cdels_numba_initial_population_matches_python() -> None:
    problem = _problem()
    python_core = CDELS(problem, seed=1)
    numba_core = CDELSNumba(problem, seed=1)

    python_generation = python_core.initialize_population()
    numba_generation = numba_core.initialize_population()

    assert numba_core.process_trace_generation(numba_generation) == (
        python_core.process_trace_generation(python_generation)
    )


def test_cdels_numba_mutation_and_crossover_match_python_full_state() -> None:
    """分開檢查 DE 兩階段，避免整體 trace 掩蓋局部差異。"""
    problem = _problem()
    # 這些固定案例包含 mutation collision/retry 的 8、9、10、11 draws，
    # 也包含 crossover 立即停止（3 draws）與完整掃描（17 draws）。
    cases = (
        (1, 0, 8, 3),
        (1, 13, 9, None),
        (30, 11, 10, None),
        (36, 1, 11, None),
        (9, 3, None, 17),
    )
    for seed, target_index, mutation_draws, crossover_draws in cases:
        python_core = CDELS(problem, seed=seed)
        numba_core = CDELSNumba(problem, seed=seed)
        python_generation = python_core.initialize_population()
        numba_generation = numba_core.initialize_population()

        mutation_draw_count_before = python_core.rng.draw_count
        python_mutant = python_core._mutation(python_generation, target_index)
        numba_mutant = numba_core._mutation(numba_generation, target_index)

        assert numba_mutant.canonical_dict() == python_mutant.canonical_dict()
        assert (numba_core.rng.state, numba_core.rng.draw_count) == (
            python_core.rng.state,
            python_core.rng.draw_count,
        )
        if mutation_draws is not None:
            assert (
                python_core.rng.draw_count - mutation_draw_count_before
                == mutation_draws
            )

        crossover_draw_count_before = python_core.rng.draw_count
        python_trial = python_core._crossover(
            python_generation.individuals[target_index],
            python_mutant,
        )
        numba_trial = numba_core._crossover(
            numba_generation.individuals[target_index],
            numba_mutant,
        )

        assert numba_trial.canonical_dict() == python_trial.canonical_dict()
        assert (numba_core.rng.state, numba_core.rng.draw_count) == (
            python_core.rng.state,
            python_core.rng.draw_count,
        )
        if crossover_draws is not None:
            assert (
                python_core.rng.draw_count - crossover_draw_count_before
                == crossover_draws
            )

    assert _select_mutation_indices_numba.nopython_signatures
    assert _generate_new_mutant_numba.nopython_signatures
    assert _crossover_numba.nopython_signatures


def test_cdels_numba_sa_acceptance_matches_python_fixed_vectors() -> None:
    """涵蓋更好、相等、較差、exp 上下溢及溫度下溢成零。"""
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
        python_core = CDELS(problem, seed=seed)
        numba_core = CDELSNumba(problem, seed=seed)

        python_accepted = python_core._accept_trial_by_sa(
            target_cost,
            trial_cost,
            temperature,
        )
        numba_accepted = numba_core._accept_trial_by_sa(
            target_cost,
            trial_cost,
            temperature,
        )

        assert numba_accepted is python_accepted
        assert (numba_core.rng.state, numba_core.rng.draw_count) == (
            python_core.rng.state,
            python_core.rng.draw_count,
        )
        assert numba_core.rng.draw_count == 1

    assert _accept_trial_by_sa_numba.nopython_signatures


def test_cdels_numba_new_generation_selection_matches_python() -> None:
    """確認 SA 後的保留、替換、elite 與舊世代不可變語意。"""
    problem = _problem()
    python_core = CDELS(problem, seed=1)
    numba_core = CDELSNumba(problem, seed=1)
    python_old = python_core.initialize_population()
    numba_old = numba_core.initialize_population()
    python_old_state = [
        individual.canonical_dict() for individual in python_old.individuals
    ]
    numba_old_state = [
        individual.canonical_dict() for individual in numba_old.individuals
    ]

    python_new = python_core._new_generation(python_old, 1.0)
    numba_new = numba_core._new_generation(numba_old, 1.0)

    assert numba_core.process_trace_generation(numba_new) == (
        python_core.process_trace_generation(python_new)
    )
    assert [
        index
        for index, (old, new) in enumerate(
            zip(numba_old.individuals, numba_new.individuals, strict=True)
        )
        if old is new
    ] == [0, 38]
    assert numba_new.best_index == python_new.best_index == 10
    assert numba_new.feasible_solutions == python_new.feasible_solutions == 42
    assert [
        individual.canonical_dict() for individual in python_old.individuals
    ] == python_old_state
    assert [
        individual.canonical_dict() for individual in numba_old.individuals
    ] == numba_old_state
    assert _select_trial_by_sa_numba.nopython_signatures


def test_cdels_numba_two_swap_matches_python_full_state() -> None:
    problem = _problem()
    for seed, target_index in ((1, 0), (1, 2), (2, 0), (7, 5)):
        python_core = CDELS(problem, seed=seed)
        numba_core = CDELSNumba(problem, seed=seed)
        python_generation = python_core.initialize_population()
        numba_generation = numba_core.initialize_population()
        python_mutant = python_core._mutation(python_generation, target_index)
        numba_mutant = numba_core._mutation(numba_generation, target_index)
        python_trial = python_core._crossover(
            python_generation.individuals[target_index],
            python_mutant,
        )
        numba_trial = numba_core._crossover(
            numba_generation.individuals[target_index],
            numba_mutant,
        )
        python_core._reevaluate(python_trial)
        numba_core._reevaluate(numba_trial)

        assert numba_trial.canonical_dict() == python_trial.canonical_dict()
        python_core._two_swap(python_trial)
        numba_core._two_swap(numba_trial)

        assert numba_trial.canonical_dict() == python_trial.canonical_dict()
        assert numba_core.rng.state == python_core.rng.state
        assert numba_core.rng.draw_count == python_core.rng.draw_count
    assert _two_swap_numba.nopython_signatures


def test_cdels_numba_two_swap_preserves_mixed_transfer_typo() -> None:
    problem = _problem()
    python_core = CDELS(problem, seed=1)
    numba_core = CDELSNumba(problem, seed=1)
    python_trial = _target_zero_trial(python_core)
    numba_trial = _target_zero_trial(numba_core)
    python_trial.transfer_mask[1] = 1
    numba_trial.transfer_mask[1] = 1
    python_core._reevaluate(python_trial)
    numba_core._reevaluate(numba_trial)

    python_core._two_swap(python_trial)
    numba_core._two_swap(numba_trial)

    assert numba_trial.canonical_dict() == python_trial.canonical_dict()
    assert numba_core.rng.state == python_core.rng.state
    assert numba_core.rng.draw_count == python_core.rng.draw_count


def test_cdels_numba_two_swap_preserves_mutable_container_identity() -> None:
    core = CDELSNumba(_problem(), seed=1)
    trial = _target_zero_trial(core)
    capacities = trial.route_capacities_free
    routes = trial.routes
    route_ids = tuple(id(route) for route in routes)

    core._two_swap(trial)

    assert trial.route_capacities_free is capacities
    assert trial.routes is routes
    assert tuple(id(route) for route in trial.routes) == route_ids


def test_cdels_numba_two_swap_differential_states() -> None:
    """固定產生不同 route/transfer/overload 分支，逐狀態比較基準版。"""
    problem = _problem()
    python_core = CDELS(problem, seed=1)
    numba_core = CDELSNumba(problem, seed=1)
    template = python_core.initialize_population().individuals[0]
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

        python_individual = deepcopy(source)
        numba_individual = deepcopy(source)
        python_core._reevaluate(python_individual)
        numba_core._reevaluate(numba_individual)
        python_core._two_swap(python_individual)
        numba_core._two_swap(numba_individual)

        assert numba_individual.canonical_dict() == python_individual.canonical_dict()
        python_core._strong_drop(python_individual)
        numba_core._strong_drop(numba_individual)
        assert numba_individual.canonical_dict() == python_individual.canonical_dict()


def test_cdels_numba_strong_drop_matches_python_full_state() -> None:
    problem = _problem()
    for seed, target_index in ((1, 0), (1, 2), (2, 0), (7, 5)):
        python_core = CDELS(problem, seed=seed)
        numba_core = CDELSNumba(problem, seed=seed)
        python_generation = python_core.initialize_population()
        numba_generation = numba_core.initialize_population()
        python_mutant = python_core._mutation(python_generation, target_index)
        numba_mutant = numba_core._mutation(numba_generation, target_index)
        python_trial = python_core._crossover(
            python_generation.individuals[target_index],
            python_mutant,
        )
        numba_trial = numba_core._crossover(
            numba_generation.individuals[target_index],
            numba_mutant,
        )
        python_core._reevaluate(python_trial)
        numba_core._reevaluate(numba_trial)

        python_core._strong_drop(python_trial)
        numba_core._strong_drop(numba_trial)

        assert numba_trial.canonical_dict() == python_trial.canonical_dict()
        assert numba_core.rng.state == python_core.rng.state
        assert numba_core.rng.draw_count == python_core.rng.draw_count
    assert _strong_drop_numba.nopython_signatures


def test_cdels_numba_strong_drop_mixed_transfer_and_container_identity() -> None:
    problem = _problem()
    python_core = CDELS(problem, seed=1)
    numba_core = CDELSNumba(problem, seed=1)
    python_trial = _target_zero_trial(python_core)
    numba_trial = _target_zero_trial(numba_core)
    for customer in (1, 3, 7):
        python_trial.transfer_mask[customer] = 1
        numba_trial.transfer_mask[customer] = 1
    python_core._reevaluate(python_trial)
    numba_core._reevaluate(numba_trial)
    capacities = numba_trial.route_capacities_free
    routes = numba_trial.routes
    route_ids = tuple(id(route) for route in routes)

    python_core._strong_drop(python_trial)
    numba_core._strong_drop(numba_trial)

    assert numba_trial.canonical_dict() == python_trial.canonical_dict()
    assert numba_trial.route_capacities_free is capacities
    assert numba_trial.routes is routes
    assert tuple(id(route) for route in numba_trial.routes) == route_ids


def test_cdels_numba_full_local_search_matches_python() -> None:
    problem = _problem()
    for seed, target_index in ((1, 0), (1, 2), (2, 0), (7, 5)):
        python_core = CDELS(problem, seed=seed)
        numba_core = CDELSNumba(problem, seed=seed)
        python_generation = python_core.initialize_population()
        numba_generation = numba_core.initialize_population()
        python_mutant = python_core._mutation(python_generation, target_index)
        numba_mutant = numba_core._mutation(numba_generation, target_index)
        python_trial = python_core._crossover(
            python_generation.individuals[target_index],
            python_mutant,
        )
        numba_trial = numba_core._crossover(
            numba_generation.individuals[target_index],
            numba_mutant,
        )
        python_core._reevaluate(python_trial)
        numba_core._reevaluate(numba_trial)
        capacities = numba_trial.route_capacities_free
        transfer_capacities = numba_trial.transfer_capacities_free
        routes = numba_trial.routes
        positions = numba_trial.positions
        transfer_mask = numba_trial.transfer_mask

        python_core._local_search(python_trial)
        numba_core._local_search(numba_trial)

        assert numba_trial.canonical_dict() == python_trial.canonical_dict()
        assert numba_core.rng.state == python_core.rng.state
        assert numba_core.rng.draw_count == python_core.rng.draw_count
        assert numba_trial.route_capacities_free is capacities
        assert numba_trial.transfer_capacities_free is transfer_capacities
        assert numba_trial.routes is routes
        assert numba_trial.positions is positions
        assert numba_trial.transfer_mask is transfer_mask
    assert _local_search_numba.nopython_signatures


def test_cdels_numba_transfer_primitives_match_python_rng_and_stale_state() -> None:
    problem = _problem()
    python_core = CDELS(problem, seed=1)
    numba_core = CDELSNumba(problem, seed=1)
    python_trial = _target_zero_trial(python_core)
    numba_trial = _target_zero_trial(numba_core)

    assert python_core._turn_random_customer_to_transfer(python_trial) is True
    assert numba_core._turn_random_customer_to_transfer(numba_trial) is True
    assert numba_trial.canonical_dict() == python_trial.canonical_dict()
    assert (numba_core.rng.state, numba_core.rng.draw_count) == (
        python_core.rng.state,
        python_core.rng.draw_count,
    )

    assert python_core._turn_random_transfer_to_nontransfer(python_trial) is True
    assert numba_core._turn_random_transfer_to_nontransfer(numba_trial) is True
    assert numba_trial.canonical_dict() == python_trial.canonical_dict()
    assert (numba_core.rng.state, numba_core.rng.draw_count) == (
        python_core.rng.state,
        python_core.rng.draw_count,
    )

    python_before = (python_core.rng.state, python_core.rng.draw_count)
    numba_before = (numba_core.rng.state, numba_core.rng.draw_count)
    assert python_core._turn_random_transfer_to_nontransfer(python_trial) is False
    assert numba_core._turn_random_transfer_to_nontransfer(numba_trial) is False
    assert (python_core.rng.state, python_core.rng.draw_count) == python_before
    assert (numba_core.rng.state, numba_core.rng.draw_count) == numba_before

    python_core = CDELS(problem, seed=1)
    numba_core = CDELSNumba(problem, seed=1)
    python_trial = _target_zero_trial(python_core)
    numba_trial = _target_zero_trial(numba_core)
    # 這個 prefix 的下一次 draw 固定選 customer 9；已 transfer 仍先耗一次 RNG。
    python_trial.transfer_mask[9] = 1
    numba_trial.transfer_mask[9] = 1
    python_before_draws = python_core.rng.draw_count
    numba_before_draws = numba_core.rng.draw_count
    assert python_core._turn_random_customer_to_transfer(python_trial) is False
    assert numba_core._turn_random_customer_to_transfer(numba_trial) is False
    assert numba_trial.canonical_dict() == python_trial.canonical_dict()
    assert python_core.rng.draw_count == python_before_draws + 1
    assert numba_core.rng.draw_count == numba_before_draws + 1
    assert numba_core.rng.state == python_core.rng.state


def test_cdels_numba_drop_success_and_retry_exhaustion_match_python() -> None:
    problem = _problem()
    for target_index in (0, 2):
        python_core = CDELS(problem, seed=1)
        numba_core = CDELSNumba(problem, seed=1)
        python_generation = python_core.initialize_population()
        numba_generation = numba_core.initialize_population()
        python_mutant = python_core._mutation(python_generation, target_index)
        numba_mutant = numba_core._mutation(numba_generation, target_index)
        python_trial = python_core._crossover(
            python_generation.individuals[target_index],
            python_mutant,
        )
        numba_trial = numba_core._crossover(
            numba_generation.individuals[target_index],
            numba_mutant,
        )
        python_core._reevaluate(python_trial)
        numba_core._reevaluate(numba_trial)

        python_result = python_core._drop_one_point_infeasible(python_trial)
        numba_result = numba_core._drop_one_point_infeasible(numba_trial)

        assert numba_result == python_result
        assert numba_trial.canonical_dict() == python_trial.canonical_dict()
        assert (numba_core.rng.state, numba_core.rng.draw_count) == (
            python_core.rng.state,
            python_core.rng.draw_count,
        )


def test_cdels_numba_six_transition_process_is_identical_to_python() -> None:
    problem = _problem()
    python_result = _solve(CDELS(problem, seed=1), iterations=6)
    numba_result = _solve(CDELSNumba(problem, seed=1), iterations=6)

    assert numba_result.process_trace == python_result.process_trace
    assert numba_result.process_trace_sha256 == python_result.process_trace_sha256
    assert numba_result.result == python_result.result
    assert numba_result.rng_state == python_result.rng_state
    assert numba_result.rng_draw_count == python_result.rng_draw_count


def test_cdels_numba_matches_through_first_cooling_boundary() -> None:
    problem = _problem()
    python_result = _solve(CDELS(problem, seed=1), iterations=111)
    numba_result = _solve(CDELSNumba(problem, seed=1), iterations=111)

    assert numba_result.process_trace == python_result.process_trace
    assert numba_result.process_trace_sha256 == python_result.process_trace_sha256
    assert numba_result.result == python_result.result
    assert numba_result.final_temperature.hex() == python_result.final_temperature.hex()
    assert numba_result.rng_state == python_result.rng_state
    assert numba_result.rng_draw_count == python_result.rng_draw_count


@pytest.mark.parametrize(
    ("transitions", "expected_temperature", "expected_stagnation"),
    ((109, 1.0, 0), (110, 0.95, 1), (111, 0.95, 1)),
)
def test_cdels_numba_temperature_boundary_uses_exact_controller_semantics(
    transitions,
    expected_temperature,
    expected_stagnation,
) -> None:
    core = CDELSNumba(_problem(), seed=1)
    observed = _replace_transition_with_noop(core)

    result = core.solve(
        termination_mode="fixed_iterations",
        limit=transitions,
        max_transitions=transitions,
    )

    assert result.transition_count == transitions
    assert result.final_temperature == expected_temperature
    assert result.temperature_stagnation == expected_stagnation
    assert observed[:110] == [1.0] * min(transitions, 110)
    assert observed[110:] == [0.95] * max(0, transitions - 110)


def test_cdels_numba_legacy_stagnation_and_full_schedule_boundaries() -> None:
    short_core = CDELSNumba(_problem(), seed=1)
    short_observed = _replace_transition_with_noop(short_core)
    short = short_core.solve(
        termination_mode="legacy_temperature_stagnation",
        limit=2,
        iterations_per_temperature=3,
        max_transitions=20,
        cooling_rate=0.5,
    )
    assert short.transition_count == 9
    assert short.temperature_stagnation == 3
    assert short.final_temperature == 0.125
    assert short_observed == [1.0] * 3 + [0.5] * 3 + [0.25] * 3

    full_core = CDELSNumba(_problem(), seed=1)
    _replace_transition_with_noop(full_core)
    full = full_core.solve(
        termination_mode="legacy_temperature_stagnation",
        limit=100,
        iterations_per_temperature=110,
        max_transitions=11_330,
        cooling_rate=0.95,
    )
    assert full.transition_count == 11_110
    assert full.temperature_stagnation == 101
    assert full.final_temperature.hex() == "0x1.709b7f6853db4p-8"
