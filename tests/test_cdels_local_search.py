from __future__ import annotations

from pathlib import Path

from mkp.problem.scvrp import load_legacy_scvrp_problem
from mkp.solver.CDELS import CDELS


FIXTURES = Path(__file__).parent / "fixtures" / "scvrp"


def _problem():
    return load_legacy_scvrp_problem(
        FIXTURES / "p_n16_k8.vrp",
        FIXTURES / "p_n16_k8_routecap2_transfer1.txt",
        dataset="P",
        problem_id="P-n16-k8-routecap2-transfer1",
        best_known=350,
    )


def _seed_one_target_zero_trial():
    core = CDELS(_problem(), seed=1)
    generation = core.initialize_population()
    mutant = core._mutation(generation, 0)
    trial = core._crossover(generation.individuals[0], mutant)
    core._reevaluate(trial)
    return core, trial


def test_customer_delta_costs_skip_transferred_neighbors_without_rng_draws() -> None:
    core = CDELS(_problem(), seed=1)
    individual = core.initialize_population().individuals[0]
    draw_count = core.rng.draw_count
    rng_state = core.rng.state
    distances = core.problem.distance_matrix

    # Customer 5 is bracketed by 3 and 11 in route [3, 5, 11].  Marking
    # both neighbors transferred makes the archived helpers walk to depot 0
    # in both directions before applying their edge delta.
    individual.cost = 1_000
    individual.transfer_mask[3] = 1
    individual.transfer_mask[11] = 1
    assert core._customer_removal_cost(individual, 3, 11, 5) == int(
        1_000 - distances[0, 5] - distances[5, 0] + distances[0, 0]
    )
    assert core._customer_insertion_cost(individual, 3, 11, 5) == int(
        1_000 + distances[0, 5] + distances[5, 0] - distances[0, 0]
    )

    individual.transfer_mask[5] = 1
    assert core._customer_removal_cost(individual, 3, 11, 5) == 1_000
    assert core._customer_insertion_cost(individual, 3, 11, 5) == 1_000
    assert core.rng.draw_count == draw_count
    assert core.rng.state == rng_state


def test_seed_one_transfer_turns_have_fixed_step_one_behavior_without_native_kernel() -> None:
    core, trial = _seed_one_target_zero_trial()
    genome = trial.genome_dict()

    assert core.rng.draw_count == 14_467
    assert core.rng.state == 1_889_806_266
    assert trial.cost == 632
    assert trial.feasible is False
    assert trial.route_capacities_free == [1, 4, 2, 1, 20, -7, 5, 8]
    assert trial.transfer_capacities_free == [8, 6, 11, 8, 19, 31, 11, 30, 7]
    assert trial.transfer_vehicle_count == 0
    assert trial.transfer_total_capacity_free == 0

    assert core._turn_random_customer_to_transfer(trial) is True
    assert core.rng.draw_count == 14_468
    assert core.rng.state == 3_220_541_333
    assert trial.genome_dict()["routes"] == genome["routes"]
    assert trial.genome_dict()["positions"] == genome["positions"]
    assert trial.transfer_mask.tolist() == [0] * 9 + [1] + [0] * 6
    assert trial.cost == 641
    # The incremental C++ operation deliberately leaves these two fields stale.
    assert trial.feasible is False
    assert trial.route_capacities_free == [1, 4, 2, 1, 20, -7, 5, 8]
    assert trial.transfer_capacities_free == [0, 6, 11, 8, 19, 31, 11, 30, 7]
    assert trial.transfer_vehicle_count == 1
    assert trial.transfer_total_capacity_free == 27

    assert core._turn_random_transfer_to_nontransfer(trial) is True
    assert core.rng.draw_count == 14_469
    assert core.rng.state == 2_838_004_740
    assert trial.genome_dict()["routes"] == genome["routes"]
    assert trial.genome_dict()["positions"] == genome["positions"]
    assert trial.transfer_mask.tolist() == [0] * 16
    assert trial.cost == 632
    assert trial.feasible is False
    assert trial.route_capacities_free == [1, 4, 2, 1, 20, -7, 5, 8]
    # The archived 1 -> 0 operation does not restore per-fixed-route capacity.
    assert trial.transfer_capacities_free == [0, 6, 11, 8, 19, 31, 11, 30, 7]
    assert trial.transfer_vehicle_count == 0
    assert trial.transfer_total_capacity_free == 35


def test_turn_to_nontransfer_with_no_transfers_is_a_rng_free_noop() -> None:
    core = CDELS(_problem(), seed=1)
    individual = core.initialize_population().individuals[0]
    before = individual.canonical_dict()
    draw_count = core.rng.draw_count
    rng_state = core.rng.state

    assert core._turn_random_transfer_to_nontransfer(individual) is False
    assert individual.canonical_dict() == before
    assert core.rng.draw_count == draw_count
    assert core.rng.state == rng_state


def test_turn_to_transfer_consumes_its_draw_before_already_transferred_noop() -> None:
    core, trial = _seed_one_target_zero_trial()
    # The next MSVC draw selects customer 9 for this exact prefix.
    trial.transfer_mask[9] = 1
    before = trial.canonical_dict()
    draw_count = core.rng.draw_count
    rng_state = core.rng.state

    assert core._turn_random_customer_to_transfer(trial) is False
    assert trial.canonical_dict() == before
    assert core.rng.draw_count == draw_count + 1
    assert core.rng.state != rng_state


def test_seed_one_reinsertion_vector_is_rng_free_and_uses_independent_states() -> None:
    core, trial = _seed_one_target_zero_trial()
    baseline = trial.canonical_dict()
    draw_count = core.rng.draw_count
    rng_state = core.rng.state

    if_improves = core._make_hard_clone(trial)
    assert (
        core._reinsert_customer_best_position_if_improves(
            if_improves,
            1,
            1,
        )
        is False
    )
    assert if_improves.canonical_dict() == baseline
    assert core.rng.draw_count == draw_count
    assert core.rng.state == rng_state

    forced = core._make_hard_clone(trial)
    assert (
        core._reinsert_customer_best_position(
            forced,
            1,
            1,
        )
        is None
    )
    assert forced.routes == [
        [3, 5, 11],
        [1, 6],
        [10, 13],
        [4, 15],
        [7],
        [8, 12],
        [2],
        [9, 14],
    ]
    assert forced.positions.tolist() == [
        [0, 1, 6, 0, 3, 0, 1, 4, 5, 7, 2, 0, 5, 2, 7, 3],
        [0, 0, 0, 0, 0, 1, 1, 0, 0, 0, 0, 2, 1, 1, 1, 1],
    ]
    assert forced.transfer_mask.tolist() == [0] * 16
    assert forced.cost == 646
    assert forced.feasible is False
    assert forced.route_capacities_free == [1, -15, 21, 1, 20, -7, 5, 8]
    assert forced.transfer_capacities_free == [8, 6, 11, 8, 19, 31, 11, 30, 7]
    assert forced.transfer_vehicle_count == 0
    assert forced.transfer_total_capacity_free == 0
    assert core.rng.draw_count == draw_count
    assert core.rng.state == rng_state

    # Both probes start from separate copies of the post-crossover reevaluation
    # state, so neither the source nor the conditional result can be polluted.
    assert trial.canonical_dict() == baseline
    assert if_improves.canonical_dict() == baseline


def test_reinsertion_accepts_strict_improvement_at_first_best_position() -> None:
    core, trial = _seed_one_target_zero_trial()
    draw_count = core.rng.draw_count
    rng_state = core.rng.state

    assert core._reinsert_customer_best_position_if_improves(trial, 13, 7) is True
    assert trial.cost == 610
    assert trial.routes[2] == [1, 10]
    assert trial.routes[7] == [13, 9, 14]
    assert trial.route_capacities_free == [1, 4, 8, 1, 20, -7, 5, 2]
    assert tuple(trial.positions[:, 13]) == (7, 0)
    assert core.rng.draw_count == draw_count
    assert core.rng.state == rng_state


def test_forced_transferred_reinsertion_keeps_stale_capacity_and_empty_route_bug() -> None:
    core, trial = _seed_one_target_zero_trial()
    trial.transfer_mask[6] = 1
    core._reevaluate(trial)
    canonical_capacities = list(trial.route_capacities_free)
    canonical_transfer_capacities = list(trial.transfer_capacities_free)
    draw_count = core.rng.draw_count
    rng_state = core.rng.state

    # Nonempty destination: all insertion deltas tie for a transferred
    # customer, so the first physical slot wins and cost remains unchanged.
    core._reinsert_customer_best_position(trial, 6, 4)
    assert trial.cost == 634
    assert trial.routes[1] == []
    assert trial.routes[4] == [6, 7]
    assert trial.route_capacities_free == canonical_capacities
    assert trial.transfer_capacities_free == canonical_transfer_capacities

    # Empty destination special-case charges a depot roundtrip even though the
    # customer is still transferred.  This observable legacy bug is retained.
    core._reinsert_customer_best_position(trial, 6, 1)
    assert trial.cost == 658
    assert trial.routes[1] == [6]
    assert trial.routes[4] == [7]
    assert trial.route_capacities_free == canonical_capacities
    assert trial.transfer_capacities_free == canonical_transfer_capacities
    assert trial.transfer_mask[6] == 1
    assert core.rng.draw_count == draw_count
    assert core.rng.state == rng_state


def test_drop_infeasible_fixed_repair_vector_without_native_kernel() -> None:
    core, trial = _seed_one_target_zero_trial()
    baseline = trial.canonical_dict()
    result = core._make_hard_clone(trial)

    assert core.rng.draw_count == 14_467
    assert core.rng.state == 1_889_806_266
    assert core._drop_one_point_infeasible(result) == 553
    assert core.rng.draw_count == 14_473
    assert core.rng.state == 747_906_568
    assert result.canonical_dict() == {
        "routes": [
            [3, 5, 11],
            [6],
            [1, 10, 13],
            [4, 15],
            [12, 7],
            [8],
            [2],
            [9, 14],
        ],
        "positions": [
            [0, 2, 6, 0, 3, 0, 1, 4, 5, 7, 2, 0, 4, 2, 7, 3],
            [0, 0, 0, 0, 0, 1, 0, 1, 0, 0, 1, 2, 0, 2, 1, 1],
        ],
        "transfer_mask": [0] * 16,
        "cost": 553,
        "feasible": True,
        "route_capacities_free": [1, 4, 2, 1, 6, 7, 5, 8],
        "transfer_capacities_free": [8, 6, 11, 8, 19, 31, 11, 30, 7],
        "transfer_vehicle_count": 0,
        "transfer_total_capacity_free": 0,
    }
    assert trial.canonical_dict() == baseline


def test_drop_infeasible_fixed_retry_failure_vector_without_native_kernel() -> None:
    core = CDELS(_problem(), seed=1)
    generation = core.initialize_population()
    mutant = core._mutation(generation, 2)
    trial = core._crossover(generation.individuals[2], mutant)
    core._reevaluate(trial)
    baseline = trial.canonical_dict()
    result = core._make_hard_clone(trial)

    assert core.rng.draw_count == 14_467
    assert core.rng.state == 1_889_806_266
    assert core._drop_one_point_infeasible(result) == -1
    assert core.rng.draw_count == 14_471
    assert core.rng.state == 505_795_230
    assert result.canonical_dict() == baseline == {
        "routes": [
            [1, 15],
            [2],
            [3, 5],
            [8],
            [6],
            [4, 12],
            [14, 9, 13],
            [7, 11, 10],
        ],
        "positions": [
            [0, 0, 1, 2, 5, 2, 4, 7, 3, 6, 7, 7, 5, 6, 6, 0],
            [0, 0, 0, 0, 0, 1, 0, 0, 0, 1, 2, 1, 1, 2, 0, 1],
        ],
        "transfer_mask": [0] * 16,
        "cost": 625,
        "feasible": False,
        "route_capacities_free": [5, 5, 8, 7, 4, -2, 2, 5],
        "transfer_capacities_free": [8, 6, 11, 8, 19, 31, 11, 30, 7],
        "transfer_vehicle_count": 0,
        "transfer_total_capacity_free": 0,
    }
    assert trial.canonical_dict() == baseline


def test_local_search_fixed_orchestration_vector_without_native_kernel() -> None:
    core, trial = _seed_one_target_zero_trial()
    baseline = trial.canonical_dict()
    result = core._make_hard_clone(trial)

    assert core.rng.draw_count == 14_467
    assert core.rng.state == 1_889_806_266
    assert core._local_search(result) is None
    assert core.rng.draw_count == 14_486
    assert core.rng.state == 3_415_770_119
    assert result.canonical_dict() == {
        "routes": [
            [9, 13],
            [6],
            [10, 3, 15],
            [4, 11],
            [1, 7],
            [8, 12],
            [2],
            [5, 14],
        ],
        "positions": [
            [0, 4, 6, 2, 3, 7, 1, 4, 5, 0, 2, 3, 5, 0, 7, 2],
            [0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1, 1, 1, 1, 2],
        ],
        "transfer_mask": [0] * 16,
        "cost": 566,
        "feasible": False,
        "route_capacities_free": [21, 4, 0, 5, 1, -7, 5, 5],
        "transfer_capacities_free": [8, 6, 11, 8, 19, 31, 11, 30, 7],
        "transfer_vehicle_count": 0,
        "transfer_total_capacity_free": 0,
    }
    assert trial.canonical_dict() == baseline


def test_strong_drop_fixed_vector_is_rng_free_and_isolated_without_native_kernel() -> None:
    core, trial = _seed_one_target_zero_trial()
    baseline = trial.canonical_dict()
    draw_count = core.rng.draw_count
    rng_state = core.rng.state
    result = core._make_hard_clone(trial)

    assert core._strong_drop(result) is None
    assert result.canonical_dict() == {
        "routes": [
            [3, 13, 5],
            [6],
            [1, 10, 11],
            [4, 15],
            [7],
            [8, 12],
            [2],
            [9, 14],
        ],
        "positions": [
            [0, 2, 6, 0, 3, 0, 1, 4, 5, 7, 2, 2, 5, 0, 7, 3],
            [0, 0, 0, 0, 0, 2, 0, 0, 0, 0, 1, 2, 1, 1, 1, 1],
        ],
        "transfer_mask": [0] * 16,
        "cost": 586,
        "feasible": False,
        "route_capacities_free": [2, 4, 1, 1, 20, -7, 5, 8],
        "transfer_capacities_free": [8, 6, 11, 8, 19, 31, 11, 30, 7],
        "transfer_vehicle_count": 0,
        "transfer_total_capacity_free": 0,
    }
    assert core.rng.draw_count == draw_count
    assert core.rng.state == rng_state
    assert trial.canonical_dict() == baseline


def test_two_swap_fixed_vector_restarts_after_each_strict_improvement() -> None:
    core, trial = _seed_one_target_zero_trial()
    draw_count = core.rng.draw_count
    rng_state = core.rng.state

    assert trial.cost == 632
    assert core._two_swap(trial) is None
    assert trial.routes == [
        [10, 3, 15],
        [6],
        [7, 9, 13],
        [4, 11],
        [1],
        [8, 12],
        [2],
        [5, 14],
    ]
    assert trial.positions.tolist() == [
        [0, 4, 6, 0, 3, 7, 1, 2, 5, 2, 0, 3, 5, 2, 7, 0],
        [0, 0, 0, 1, 0, 0, 0, 0, 0, 1, 0, 1, 1, 2, 1, 2],
    ]
    assert trial.transfer_mask.tolist() == [0] * 16
    assert trial.cost == 539
    # The archived move improves an infeasible individual incrementally.  It
    # neither repairs the overloaded route nor performs a full reevaluation.
    assert trial.feasible is False
    assert trial.route_capacities_free == [0, 4, 6, 5, 16, -7, 5, 5]
    assert trial.transfer_capacities_free == [8, 6, 11, 8, 19, 31, 11, 30, 7]
    assert trial.transfer_vehicle_count == 0
    assert trial.transfer_total_capacity_free == 0
    assert core.rng.draw_count == draw_count
    assert core.rng.state == rng_state


def test_two_swap_fixed_mixed_transfer_vector_preserves_transfer_state() -> None:
    core, trial = _seed_one_target_zero_trial()
    trial.transfer_mask[1] = 1
    core._reevaluate(trial)
    draw_count = core.rng.draw_count
    rng_state = core.rng.state

    assert trial.cost == 658
    assert trial.feasible is False
    assert core._two_swap(trial) is None
    assert trial.routes == [
        [10, 3, 15],
        [6],
        [1, 9, 13],
        [4, 11],
        [7],
        [8, 12],
        [2],
        [5, 14],
    ]
    assert trial.positions.tolist() == [
        [0, 2, 6, 0, 3, 7, 1, 4, 5, 2, 0, 3, 5, 2, 7, 0],
        [0, 0, 0, 1, 0, 0, 0, 0, 0, 1, 0, 1, 1, 2, 1, 2],
    ]
    assert trial.transfer_mask.tolist() == [0, 1] + [0] * 14
    assert trial.cost == 581
    assert trial.feasible is False
    assert trial.route_capacities_free == [0, 4, 21, 5, 20, -7, 5, 5]
    assert trial.transfer_capacities_free == [8, 6, 11, 8, 0, 31, 11, 30, 7]
    assert trial.transfer_vehicle_count == 1
    assert trial.transfer_total_capacity_free == 16
    assert core.rng.draw_count == draw_count
    assert core.rng.state == rng_state
