from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
import errno
from hashlib import sha256
import json
import math
from multiprocessing import get_context
from pathlib import Path
import subprocess
import time
from typing import Any

import pytest

from mkp.problem.scvrp import load_legacy_scvrp_problem
from mkp.rng.msvc_legacy import MSVC_RAND_MAX, MsvcLegacyRand
from mkp.solver.CDELS import CDELS
from mkp.solver.CDELS_workspace import CDELSWorkspace
import mkp.tools.scvrp_native_oracle as legacy_kernel_module
from mkp.tools.scvrp_native_oracle import (
    SCVRPLegacyKernelError,
    SCVRPLegacyKernelRequest,
    SCVRPLegacySAAcceptanceCase,
    build_scvrp_legacy_kernel,
    run_scvrp_legacy_generation_probe,
    run_scvrp_legacy_kernel,
    run_scvrp_legacy_probe,
    verify_legacy_source_hashes,
)


FIXTURES = Path(__file__).parent / "fixtures" / "scvrp"

# These are deterministic fingerprints derived from the verified compatibility
# kernel.  The archived report/solution files did not emit RNG state or draw
# counts, so these values are regression guards rather than direct archive data.
_DERIVED_RNG_FINGERPRINTS = {
    1: (3_106_006_966, 9_603_103),
    2: (2_823_875_481, 9_604_909),
    3: (620_018_894, 9_611_061),
    4: (2_049_270_995, 9_615_757),
    5: (2_313_037_320, 9_620_437),
    6: (4_029_438_883, 9_609_267),
    7: (440_143_037, 9_617_718),
    8: (1_693_365_476, 9_619_932),
    9: (3_323_558_197, 9_612_412),
    10: (789_138_256, 9_621_566),
}

_DEFINED_INDIVIDUAL_STATE_FIELDS = (
    "routes",
    "positions",
    "transfer_mask",
    "cost",
    "feasible",
    "route_capacities_free",
    "transfer_capacities_free",
    "transfer_vehicle_count",
    "transfer_total_capacity_free",
)

_SA_ACCEPTANCE_CASES = (
    SCVRPLegacySAAcceptanceCase(30091, 100, 90, 1.0),
    SCVRPLegacySAAcceptanceCase(1, 100, 100, 1.0),
    SCVRPLegacySAAcceptanceCase(30091, 100, 100, 1.0),
    SCVRPLegacySAAcceptanceCase(1, 100, 101, 10.0),
    SCVRPLegacySAAcceptanceCase(30091, 100, 101, 10.0),
    SCVRPLegacySAAcceptanceCase(1, 0, 1_000, 1.0),
    SCVRPLegacySAAcceptanceCase(1, 0x7FFF_FFFF, 0, 1.0),
)


def _problem():
    return load_legacy_scvrp_problem(
        FIXTURES / "p_n16_k8.vrp",
        FIXTURES / "p_n16_k8_routecap2_transfer1.txt",
        dataset="P",
        problem_id="P-n16-k8-routecap2-transfer1",
        best_known=350,
    )


def _golden() -> dict[str, object]:
    return json.loads(
        (FIXTURES / "p_n16_k8_seeds_1_10_golden.json").read_text(encoding="ascii")
    )


def _seed_golden_by_seed(golden: dict[str, object]) -> dict[int, dict[str, object]]:
    rows = golden["seeds"]
    assert isinstance(rows, list)
    seeds = [int(row["seed"]) for row in rows]
    assert len(seeds) == len(set(seeds)), "golden seed rows must not contain duplicates"
    assert set(seeds) == set(range(1, 11)), "golden seed rows must cover seeds 1..10"
    return {int(row["seed"]): row for row in rows}


def _assert_defined_state_matches_native(
    native: object,
    python_individual: Any,
    *,
    stage: str,
) -> None:
    assert isinstance(native, dict)
    canonical = python_individual.canonical_dict()
    assert set(native) == set(_DEFINED_INDIVIDUAL_STATE_FIELDS)
    for field in _DEFINED_INDIVIDUAL_STATE_FIELDS:
        assert native[field] == canonical[field], f"native mismatch at {stage}.{field}"


def _assert_generation_matches_native(
    native: object,
    python_generation: Any,
    core: CDELS,
    *,
    stage: str,
) -> None:
    assert isinstance(native, dict)
    assert set(native) == {
        "generation_id",
        "best_index",
        "feasible_solutions",
        "individuals",
        "best",
        "rng",
    }
    assert native["generation_id"] == python_generation.generation_id
    assert native["best_index"] == python_generation.best_index
    assert native["feasible_solutions"] == python_generation.feasible_solutions
    assert native["rng"] == {
        "state": core.rng.state,
        "draw_count": core.rng.draw_count,
    }

    native_individuals = native["individuals"]
    assert isinstance(native_individuals, list)
    assert len(native_individuals) == len(python_generation.individuals)
    for index, (native_individual, python_individual) in enumerate(
        zip(native_individuals, python_generation.individuals, strict=True)
    ):
        _assert_defined_state_matches_native(
            native_individual,
            python_individual,
            stage=f"{stage}.individuals[{index}]",
        )
    _assert_defined_state_matches_native(
        native["best"],
        python_generation.best,
        stage=f"{stage}.best",
    )

    if python_generation.best_index == -1:
        assert all(
            individual is not python_generation.best
            for individual in python_generation.individuals
        )
    else:
        assert (
            python_generation.individuals[python_generation.best_index]
            is python_generation.best
        )

    canonical_payload = json.dumps(
        native_individuals,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")
    python_trace = core.trace_generation(python_generation, stage=stage)
    assert sha256(canonical_payload).hexdigest() == python_trace.population_sha256


def _assert_python_new_generations_match_native(
    native_kernel: Path,
    *,
    seed: int,
    transitions: int,
    temperature: float = 1.0,
    cooling_rate: float = 0.95,
    iterations_per_temperature: int = 110,
) -> dict[str, Any]:
    problem = _problem()
    native = run_scvrp_legacy_generation_probe(
        problem,
        SCVRPLegacyKernelRequest(
            seed=seed,
            termination_mode="fixed_iterations",
            limit=transitions,
            start_temperature=temperature,
            cooling_rate=cooling_rate,
            iterations_per_temperature=iterations_per_temperature,
            probe_new_generation=True,
        ),
        executable=native_kernel,
        timeout=20.0,
    )
    assert native["protocol"] == legacy_kernel_module.GENERATION_PROBE_PROTOCOL
    assert native["seed"] == seed
    assert _normalized_hex(native["temperature_hex"]) == float(temperature).hex()
    expected_temperatures: list[float] = []
    current_temperature = float(temperature)
    for transition in range(1, transitions + 1):
        expected_temperatures.append(current_temperature)
        if transition % iterations_per_temperature == 0:
            current_temperature *= cooling_rate
    assert [
        _normalized_hex(value) for value in native["temperature_schedule_hex"]
    ] == [value.hex() for value in expected_temperatures]
    assert len(native["trace"]) == transitions + 1

    core = CDELS(problem, seed=seed)
    generation = core.initialize_population()
    _assert_generation_matches_native(
        native["trace"][0],
        generation,
        core,
        stage="generation_1",
    )
    for transition in range(1, transitions + 1):
        generation = core._new_generation(
            generation,
            expected_temperatures[transition - 1],
        )
        _assert_generation_matches_native(
            native["trace"][transition],
            generation,
            core,
            stage=f"generation_{transition + 1}",
        )
    return native


def _normalized_hex(value: str) -> str:
    return float.fromhex(value).hex()


def _assert_python_sa_acceptance_matches_native(native_kernel: Path) -> None:
    problem = _problem()
    native = run_scvrp_legacy_probe(
        problem,
        SCVRPLegacyKernelRequest(
            seed=1,
            termination_mode="fixed_iterations",
            limit=0,
            probe_target=0,
            probe_sa_cases=_SA_ACCEPTANCE_CASES,
        ),
        executable=native_kernel,
    )
    assert native["protocol"] == legacy_kernel_module.PROBE_PROTOCOL
    native_cases = native["sa_acceptance_probe"]
    assert isinstance(native_cases, list)
    assert len(native_cases) == len(_SA_ACCEPTANCE_CASES)

    core = CDELS(problem, seed=999)
    for case, native_case in zip(_SA_ACCEPTANCE_CASES, native_cases, strict=True):
        assert set(native_case) == {
            "rng_seed",
            "target_cost",
            "trial_cost",
            "temperature_hex",
            "raw_rand",
            "rand_value_hex",
            "exponent_hex",
            "probability_hex",
            "accepted",
            "rng",
        }
        assert native_case["rng_seed"] == case.rng_seed
        assert native_case["target_cost"] == case.target_cost
        assert native_case["trial_cost"] == case.trial_cost

        reference_rng = MsvcLegacyRand(case.rng_seed)
        raw_rand = reference_rng.rand()
        rand_value = raw_rand / float(MSVC_RAND_MAX)
        exponent = (case.target_cost - case.trial_cost) / float(case.temperature)
        try:
            probability = math.exp(exponent)
        except OverflowError:
            probability = math.inf
        assert native_case["raw_rand"] == raw_rand
        assert _normalized_hex(native_case["temperature_hex"]) == float(
            case.temperature
        ).hex()
        assert _normalized_hex(native_case["rand_value_hex"]) == rand_value.hex()
        assert _normalized_hex(native_case["exponent_hex"]) == exponent.hex()
        assert _normalized_hex(native_case["probability_hex"]) == probability.hex()

        core.rng.srand(case.rng_seed)
        accepted = core._accept_trial_by_sa(
            case.target_cost,
            case.trial_cost,
            case.temperature,
        )
        assert native_case["accepted"] is accepted
        assert native_case["rng"] == {
            "state": core.rng.state,
            "draw_count": core.rng.draw_count,
        }

    # The batch owns an isolated RNG branch and restores the reevaluated-trial
    # prefix before the pre-existing probes continue.
    assert native["two_swap_probe"]["rng"] == native["rng_after_reevaluate"]


def _assert_python_drop_infeasible_matches_native(
    native_kernel: Path,
    *,
    seed: int,
    target_index: int,
) -> None:
    problem = _problem()
    native = run_scvrp_legacy_probe(
        problem,
        SCVRPLegacyKernelRequest(
            seed=seed,
            termination_mode="fixed_iterations",
            limit=0,
            probe_target=target_index,
        ),
        executable=native_kernel,
    )
    assert native["protocol"] == legacy_kernel_module.PROBE_PROTOCOL

    core = CDELS(problem, seed=seed)
    generation = core.initialize_population()
    mutant = core._mutation(generation, target_index)
    trial = core._crossover(generation.individuals[target_index], mutant)
    core._reevaluate(trial)
    baseline = trial.canonical_dict()

    native_probe = native["drop_infeasible_probe"]
    if trial.feasible:
        assert native_probe is None
        return

    assert isinstance(native_probe, dict)
    result = core._make_hard_clone(trial)
    return_value = core._drop_one_point_infeasible(result)
    assert native_probe["return_value"] == return_value
    assert native_probe["rng"] == {
        "state": core.rng.state,
        "draw_count": core.rng.draw_count,
    }
    _assert_defined_state_matches_native(
        native_probe["state"],
        result,
        stage="drop_infeasible_probe.state",
    )
    assert trial.canonical_dict() == baseline


def _assert_python_local_search_matches_native(
    native_kernel: Path,
    *,
    seed: int,
    target_index: int,
) -> None:
    problem = _problem()
    native = run_scvrp_legacy_probe(
        problem,
        SCVRPLegacyKernelRequest(
            seed=seed,
            termination_mode="fixed_iterations",
            limit=0,
            probe_target=target_index,
            probe_local_search=True,
        ),
        executable=native_kernel,
        timeout=10.0,
    )
    assert native["protocol"] == legacy_kernel_module.PROBE_PROTOCOL

    core = CDELS(problem, seed=seed)
    generation = core.initialize_population()
    mutant = core._mutation(generation, target_index)
    trial = core._crossover(generation.individuals[target_index], mutant)
    core._reevaluate(trial)
    baseline = trial.canonical_dict()

    native_probe = native["local_search_probe"]
    assert isinstance(native_probe, dict)
    result = core._make_hard_clone(trial)
    assert core._local_search(result) is None
    assert native_probe["rng"] == {
        "state": core.rng.state,
        "draw_count": core.rng.draw_count,
    }
    _assert_defined_state_matches_native(
        native_probe["state"],
        result,
        stage="local_search_probe.state",
    )
    assert trial.canonical_dict() == baseline


def _assert_python_step_one_matches_native(
    native_kernel: Path,
    *,
    seed: int,
    target_index: int,
) -> None:
    problem = _problem()
    native = run_scvrp_legacy_probe(
        problem,
        SCVRPLegacyKernelRequest(
            seed=seed,
            termination_mode="fixed_iterations",
            limit=0,
            probe_target=target_index,
        ),
        executable=native_kernel,
    )
    assert (
        native["protocol"]
        == legacy_kernel_module.PROBE_PROTOCOL
        == "SCVRP_LEGACY_PROBE_V8"
    )
    core = CDELS(problem, seed=seed)
    generation = core.initialize_population()

    assert native["rng_after_initial"] == {
        "state": core.rng.state,
        "draw_count": core.rng.draw_count,
    }
    assert native["target"] == generation.individuals[target_index].genome_dict()

    mutant = core._mutation(generation, target_index)
    assert native["rng_after_mutation"] == {
        "state": core.rng.state,
        "draw_count": core.rng.draw_count,
    }
    assert native["mutant"] == mutant.genome_dict()

    trial = core._crossover(generation.individuals[target_index], mutant)
    assert native["rng_after_crossover"] == {
        "state": core.rng.state,
        "draw_count": core.rng.draw_count,
    }
    assert native["trial"] == trial.genome_dict()

    core._reevaluate(trial)
    trial_baseline = trial.canonical_dict()
    baseline_rng = {
        "state": core.rng.state,
        "draw_count": core.rng.draw_count,
    }
    assert native["rng_after_reevaluate"] == {
        "state": core.rng.state,
        "draw_count": core.rng.draw_count,
    }
    _assert_defined_state_matches_native(
        native["trial_reevaluated"],
        trial,
        stage="trial_reevaluated",
    )

    native_drop = native["drop_infeasible_probe"]
    if trial.feasible:
        # The archived function is only defined for an overloaded state; its
        # invalid-route selection loop would not terminate for a feasible one.
        assert native_drop is None
    else:
        assert isinstance(native_drop, dict)
        drop_result = core._make_hard_clone(trial)
        return_value = core._drop_one_point_infeasible(drop_result)
        assert native_drop["return_value"] == return_value
        assert native_drop["rng"] == {
            "state": core.rng.state,
            "draw_count": core.rng.draw_count,
        }
        _assert_defined_state_matches_native(
            native_drop["state"],
            drop_result,
            stage="drop_infeasible_probe.state",
        )
        assert trial.canonical_dict() == trial_baseline

        # The C++ runner replays the same prefix after its isolated stochastic
        # probe.  Do likewise so all pre-existing probe assertions retain their
        # original RNG starting point.
        core.rng.srand(seed)
        for _ in range(baseline_rng["draw_count"]):
            core.rng.rand()
        assert core.rng.state == baseline_rng["state"]
        assert core.rng.draw_count == baseline_rng["draw_count"]

    two_swap_result = core._make_hard_clone(trial)
    assert core._two_swap(two_swap_result) is None
    assert native["two_swap_probe"]["rng"] == baseline_rng
    _assert_defined_state_matches_native(
        native["two_swap_probe"]["state"],
        two_swap_result,
        stage="two_swap_probe.state",
    )
    assert core.rng.state == baseline_rng["state"]
    assert core.rng.draw_count == baseline_rng["draw_count"]
    assert trial.canonical_dict() == trial_baseline
    assert native["two_swap_mixed_probe"] is None

    strong_drop_result = core._make_hard_clone(trial)
    assert core._strong_drop(strong_drop_result) is None
    assert native["strong_drop_probe"]["rng"] == baseline_rng
    _assert_defined_state_matches_native(
        native["strong_drop_probe"]["state"],
        strong_drop_result,
        stage="strong_drop_probe.state",
    )
    assert core.rng.state == baseline_rng["state"]
    assert core.rng.draw_count == baseline_rng["draw_count"]
    assert trial.canonical_dict() == trial_baseline
    assert native["strong_drop_mixed_probe"] is None
    assert native["local_search_probe"] is None
    assert native["sa_acceptance_probe"] is None

    core._turn_random_customer_to_transfer(trial)
    assert native["rng_after_turn_to_transfer"] == {
        "state": core.rng.state,
        "draw_count": core.rng.draw_count,
    }
    _assert_defined_state_matches_native(
        native["after_turn_to_transfer"],
        trial,
        stage="after_turn_to_transfer",
    )

    core._turn_random_transfer_to_nontransfer(trial)
    assert native["rng_after_turn_to_no_transfer"] == {
        "state": core.rng.state,
        "draw_count": core.rng.draw_count,
    }
    _assert_defined_state_matches_native(
        native["after_turn_to_no_transfer"],
        trial,
        stage="after_turn_to_no_transfer",
    )


def _assert_python_mixed_two_swap_matches_native(
    native_kernel: Path,
    *,
    seed: int,
    target_index: int,
    transfer_customer: int,
) -> None:
    problem = _problem()
    native = run_scvrp_legacy_probe(
        problem,
        SCVRPLegacyKernelRequest(
            seed=seed,
            termination_mode="fixed_iterations",
            limit=0,
            probe_target=target_index,
            probe_two_swap_transfer_customer=transfer_customer,
        ),
        executable=native_kernel,
    )
    assert native["protocol"] == legacy_kernel_module.PROBE_PROTOCOL

    core = CDELS(problem, seed=seed)
    generation = core.initialize_population()
    mutant = core._mutation(generation, target_index)
    trial = core._crossover(generation.individuals[target_index], mutant)
    core._reevaluate(trial)
    trial_baseline = trial.canonical_dict()

    mixed = core._make_hard_clone(trial)
    mixed.transfer_mask[transfer_customer] = 1
    core._reevaluate(mixed)
    baseline_rng = {
        "state": core.rng.state,
        "draw_count": core.rng.draw_count,
    }

    native_probe = native["two_swap_mixed_probe"]
    assert isinstance(native_probe, dict)
    assert native_probe["transfer_customer"] == transfer_customer
    _assert_defined_state_matches_native(
        native_probe["baseline"],
        mixed,
        stage="two_swap_mixed_probe.baseline",
    )
    assert core._two_swap(mixed) is None
    assert native_probe["rng"] == baseline_rng
    _assert_defined_state_matches_native(
        native_probe["state"],
        mixed,
        stage="two_swap_mixed_probe.state",
    )
    assert core.rng.state == baseline_rng["state"]
    assert core.rng.draw_count == baseline_rng["draw_count"]
    assert trial.canonical_dict() == trial_baseline


def _assert_python_mixed_strong_drop_matches_native(
    native_kernel: Path,
    *,
    seed: int,
    target_index: int,
    transfer_customer: int,
) -> None:
    problem = _problem()
    native = run_scvrp_legacy_probe(
        problem,
        SCVRPLegacyKernelRequest(
            seed=seed,
            termination_mode="fixed_iterations",
            limit=0,
            probe_target=target_index,
            probe_strong_drop_transfer_customer=transfer_customer,
        ),
        executable=native_kernel,
    )
    assert native["protocol"] == legacy_kernel_module.PROBE_PROTOCOL

    core = CDELS(problem, seed=seed)
    generation = core.initialize_population()
    mutant = core._mutation(generation, target_index)
    trial = core._crossover(generation.individuals[target_index], mutant)
    core._reevaluate(trial)
    trial_baseline = trial.canonical_dict()

    mixed = core._make_hard_clone(trial)
    mixed.transfer_mask[transfer_customer] = 1
    core._reevaluate(mixed)
    baseline_rng = {
        "state": core.rng.state,
        "draw_count": core.rng.draw_count,
    }

    native_probe = native["strong_drop_mixed_probe"]
    assert isinstance(native_probe, dict)
    assert native_probe["transfer_customer"] == transfer_customer
    _assert_defined_state_matches_native(
        native_probe["baseline"],
        mixed,
        stage="strong_drop_mixed_probe.baseline",
    )
    assert core._strong_drop(mixed) is None
    assert native_probe["rng"] == baseline_rng
    _assert_defined_state_matches_native(
        native_probe["state"],
        mixed,
        stage="strong_drop_mixed_probe.state",
    )
    assert core.rng.state == baseline_rng["state"]
    assert core.rng.draw_count == baseline_rng["draw_count"]
    assert trial.canonical_dict() == trial_baseline


def _assert_python_reinsertion_matches_native(
    native_kernel: Path,
    *,
    seed: int,
    target_index: int,
    customer: int,
    new_route: int,
) -> None:
    problem = _problem()
    native = run_scvrp_legacy_probe(
        problem,
        SCVRPLegacyKernelRequest(
            seed=seed,
            termination_mode="fixed_iterations",
            limit=0,
            probe_target=target_index,
            probe_reinsert_customer=customer,
            probe_reinsert_new_route=new_route,
        ),
        executable=native_kernel,
    )
    assert native["protocol"] == legacy_kernel_module.PROBE_PROTOCOL

    core = CDELS(problem, seed=seed)
    generation = core.initialize_population()
    mutant = core._mutation(generation, target_index)
    trial = core._crossover(generation.individuals[target_index], mutant)
    core._reevaluate(trial)
    baseline = trial.canonical_dict()
    baseline_rng = {
        "state": core.rng.state,
        "draw_count": core.rng.draw_count,
    }
    _assert_defined_state_matches_native(
        native["trial_reevaluated"],
        trial,
        stage="trial_reevaluated",
    )

    native_probe = native["reinsertion_probe"]
    assert isinstance(native_probe, dict)
    assert native_probe["customer"] == customer
    assert native_probe["new_route"] == new_route

    if_improves = core._make_hard_clone(trial)
    applied = core._reinsert_customer_best_position_if_improves(
        if_improves,
        customer,
        new_route,
    )
    assert native_probe["if_improves"]["applied"] is applied
    assert native_probe["if_improves"]["rng"] == baseline_rng
    _assert_defined_state_matches_native(
        native_probe["if_improves"]["state"],
        if_improves,
        stage="reinsertion_probe.if_improves.state",
    )
    assert core.rng.state == baseline_rng["state"]
    assert core.rng.draw_count == baseline_rng["draw_count"]

    forced = core._make_hard_clone(trial)
    assert (
        core._reinsert_customer_best_position(forced, customer, new_route)
        is None
    )
    assert native_probe["forced"]["rng"] == baseline_rng
    _assert_defined_state_matches_native(
        native_probe["forced"]["state"],
        forced,
        stage="reinsertion_probe.forced.state",
    )
    assert core.rng.state == baseline_rng["state"]
    assert core.rng.draw_count == baseline_rng["draw_count"]
    assert trial.canonical_dict() == baseline


def _build_native_kernel_after_barrier(cache_root: str, barrier: Any) -> str:
    """Spawn-worker entry point; it must remain at module scope to be picklable."""
    barrier.wait(timeout=30)
    return str(build_scvrp_legacy_kernel(cache_root=Path(cache_root)))


def _hold_build_lock(lock_path: str, ready: Any, release: Any) -> None:
    """Hold a build lock in an independent spawned process until released."""
    import fcntl

    with Path(lock_path).open("a+b") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        ready.set()
        if not release.wait(timeout=2):
            raise TimeoutError("test did not release the build lock")
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _write_hanging_executable(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        """#!/usr/bin/env python3
import signal
import sys

signal.signal(signal.SIGALRM, lambda *_: sys.exit(0))
signal.alarm(2)
signal.pause()
""",
        encoding="ascii",
    )
    path.chmod(0o755)


def _write_stub_compiler(
    path: Path,
    *,
    compiler_version: str,
    linked_executable: Path,
) -> None:
    path.write_text(
        f"""#!/usr/bin/env python3
from pathlib import Path
import shutil
import sys

if sys.argv[1:] == ["--version"]:
    sys.stdout.write({compiler_version!r})
    raise SystemExit(0)

output = Path(sys.argv[sys.argv.index("-o") + 1])
if "-c" in sys.argv:
    output.touch()
else:
    shutil.copyfile({str(linked_executable)!r}, output)
    output.chmod(0o755)
""",
        encoding="ascii",
    )
    path.chmod(0o755)


@pytest.fixture(scope="module")
def native_kernel(tmp_path_factory: pytest.TempPathFactory) -> Path:
    cache = tmp_path_factory.mktemp("scvrp-native-cache")
    return build_scvrp_legacy_kernel(cache_root=cache)


def test_archived_native_sources_are_unchanged() -> None:
    verify_legacy_source_hashes()


@pytest.mark.parametrize(
    ("override", "error_match"),
    (
        pytest.param({"seed": True}, "seed must be an integer", id="boolean-seed"),
        pytest.param({"seed": 0x1_0000_0000}, "unsigned 32-bit", id="seed-overflow"),
        pytest.param({"limit": 1.0}, "limit must be an integer", id="float-limit"),
        pytest.param(
            {"max_transitions": 0x7FFF_FFFF},
            "max_transitions must be < INT32_MAX",
            id="transition-overflow",
        ),
        pytest.param(
            {"start_temperature": float("inf")},
            "start_temperature must be > 0",
            id="infinite-temperature",
        ),
        pytest.param({"trace": 1}, "trace must be a boolean", id="integer-trace"),
    ),
)
def test_native_kernel_request_rejects_unsafe_protocol_values(
    override: dict[str, object],
    error_match: str,
) -> None:
    values: dict[str, object] = {
        "seed": 1,
        "termination_mode": "fixed_iterations",
        "limit": 1,
    }
    values.update(override)

    with pytest.raises(ValueError, match=error_match):
        SCVRPLegacyKernelRequest(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("override", "error_match"),
    (
        pytest.param({"rng_seed": True}, "rng_seed must be an integer", id="boolean-seed"),
        pytest.param({"rng_seed": -1}, "unsigned 32-bit", id="negative-seed"),
        pytest.param({"rng_seed": 0x1_0000_0000}, "unsigned 32-bit", id="seed-overflow"),
        pytest.param({"target_cost": True}, "target_cost must be an integer", id="boolean-target"),
        pytest.param({"target_cost": -1}, "target_cost must be in", id="negative-target"),
        pytest.param({"trial_cost": 0x8000_0000}, "trial_cost must be in", id="trial-overflow"),
        pytest.param({"temperature": True}, "temperature must be", id="boolean-temperature"),
        pytest.param({"temperature": 0.0}, "temperature must be", id="zero-temperature"),
        pytest.param({"temperature": float("inf")}, "temperature must be", id="infinite-temperature"),
    ),
)
def test_sa_acceptance_case_rejects_unsafe_values(
    override: dict[str, object],
    error_match: str,
) -> None:
    values: dict[str, object] = {
        "rng_seed": 1,
        "target_cost": 100,
        "trial_cost": 101,
        "temperature": 1.0,
    }
    values.update(override)

    with pytest.raises(ValueError, match=error_match):
        SCVRPLegacySAAcceptanceCase(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("override", "error_match"),
    (
        pytest.param(
            {"probe_target": 0, "probe_reinsert_customer": 1},
            "must be provided together",
            id="missing-new-route",
        ),
        pytest.param(
            {"probe_reinsert_customer": 1, "probe_reinsert_new_route": 0},
            "probe_target is required",
            id="missing-probe-target",
        ),
        pytest.param(
            {
                "probe_target": 0,
                "probe_reinsert_customer": True,
                "probe_reinsert_new_route": 0,
            },
            "probe_reinsert_customer must be an integer",
            id="boolean-customer",
        ),
        pytest.param(
            {
                "probe_target": 0,
                "probe_reinsert_customer": 0,
                "probe_reinsert_new_route": 1,
            },
            "probe_reinsert_customer must be > 0",
            id="depot-customer",
        ),
        pytest.param(
            {
                "probe_target": 0,
                "probe_reinsert_customer": 1,
                "probe_reinsert_new_route": -1,
            },
            "probe_reinsert_new_route must be >= 0",
            id="negative-new-route",
        ),
        pytest.param(
            {
                "probe_target": 0,
                "probe_reinsert_customer": 0x8000_0000,
                "probe_reinsert_new_route": 0,
            },
            "probe_reinsert_customer must fit in a signed 32-bit integer",
            id="customer-overflow",
        ),
        pytest.param(
            {"probe_two_swap_transfer_customer": 1},
            "probe_target is required for a two-swap transfer probe",
            id="missing-two-swap-probe-target",
        ),
        pytest.param(
            {
                "probe_target": 0,
                "probe_two_swap_transfer_customer": True,
            },
            "probe_two_swap_transfer_customer must be an integer",
            id="boolean-two-swap-transfer-customer",
        ),
        pytest.param(
            {
                "probe_target": 0,
                "probe_two_swap_transfer_customer": 0,
            },
            "probe_two_swap_transfer_customer must be > 0",
            id="depot-two-swap-transfer-customer",
        ),
        pytest.param(
            {
                "probe_target": 0,
                "probe_two_swap_transfer_customer": 0x8000_0000,
            },
            "probe_two_swap_transfer_customer must fit in a signed 32-bit integer",
            id="two-swap-transfer-customer-overflow",
        ),
        pytest.param(
            {"probe_strong_drop_transfer_customer": 1},
            "probe_target is required for a strong-drop transfer probe",
            id="missing-strong-drop-probe-target",
        ),
        pytest.param(
            {
                "probe_target": 0,
                "probe_strong_drop_transfer_customer": True,
            },
            "probe_strong_drop_transfer_customer must be an integer",
            id="boolean-strong-drop-transfer-customer",
        ),
        pytest.param(
            {
                "probe_target": 0,
                "probe_strong_drop_transfer_customer": 0,
            },
            "probe_strong_drop_transfer_customer must be > 0",
            id="depot-strong-drop-transfer-customer",
        ),
        pytest.param(
            {
                "probe_target": 0,
                "probe_strong_drop_transfer_customer": 0x8000_0000,
            },
            "probe_strong_drop_transfer_customer must fit in a signed 32-bit integer",
            id="strong-drop-transfer-customer-overflow",
        ),
        pytest.param(
            {"probe_local_search": True},
            "probe_target is required for a local-search probe",
            id="missing-local-search-probe-target",
        ),
        pytest.param(
            {"probe_target": 0, "probe_local_search": 1},
            "probe_local_search must be a boolean",
            id="integer-local-search-flag",
        ),
        pytest.param(
            {"probe_sa_cases": (_SA_ACCEPTANCE_CASES[0],)},
            "probe_target is required for an SA acceptance probe",
            id="missing-sa-probe-target",
        ),
        pytest.param(
            {"probe_target": 0, "probe_sa_cases": [_SA_ACCEPTANCE_CASES[0]]},
            "probe_sa_cases must be a tuple",
            id="mutable-sa-case-list",
        ),
        pytest.param(
            {"probe_target": 0, "probe_sa_cases": (_SA_ACCEPTANCE_CASES[0],) * 17},
            "probe_sa_cases must contain at most 16 cases",
            id="too-many-sa-cases",
        ),
        pytest.param(
            {"probe_target": 0, "probe_sa_cases": (object(),)},
            "must be an SCVRPLegacySAAcceptanceCase",
            id="invalid-sa-case-type",
        ),
        pytest.param(
            {"probe_new_generation": 1},
            "probe_new_generation must be a boolean",
            id="integer-new-generation-flag",
        ),
        pytest.param(
            {"process_trace": 1},
            "process_trace must be a boolean",
            id="integer-process-trace-flag",
        ),
        pytest.param(
            {"process_trace": True, "probe_target": 0},
            "process_trace is only available for a complete loop run",
            id="process-trace-with-target-probe",
        ),
        pytest.param(
            {"process_trace": True, "limit": 1, "probe_new_generation": True},
            "process_trace is only available for a complete loop run",
            id="process-trace-with-generation-probe",
        ),
        pytest.param(
            {"limit": 1, "probe_target": 0, "probe_new_generation": True},
            "cannot be combined with a target probe",
            id="new-generation-with-target-probe",
        ),
        pytest.param(
            {"probe_new_generation": True},
            "requires fixed_iterations with limit in",
            id="new-generation-zero-transitions",
        ),
        pytest.param(
            {"limit": 112, "probe_new_generation": True},
            "requires fixed_iterations with limit in",
            id="new-generation-too-many-transitions",
        ),
        pytest.param(
            {"limit": 1, "trace": True, "probe_new_generation": True},
            "owns its isolated trace",
            id="new-generation-with-runtime-trace",
        ),
    ),
)
def test_native_kernel_request_rejects_invalid_local_search_probe_fields(
    override: dict[str, object],
    error_match: str,
) -> None:
    values: dict[str, object] = {
        "seed": 1,
        "termination_mode": "fixed_iterations",
        "limit": 0,
    }
    values.update(override)

    with pytest.raises(ValueError, match=error_match):
        SCVRPLegacyKernelRequest(**values)  # type: ignore[arg-type]


def test_native_kernel_reuses_content_addressed_build(native_kernel: Path) -> None:
    assert native_kernel.is_file()
    assert build_scvrp_legacy_kernel(cache_root=native_kernel.parent.parent) == native_kernel


@pytest.mark.parametrize(
    "build_timeout",
    (
        pytest.param(True, id="boolean"),
        pytest.param("0.1", id="non-number"),
        pytest.param(float("nan"), id="nan"),
        pytest.param(float("inf"), id="infinite"),
        pytest.param(0, id="zero"),
        pytest.param(-0.01, id="negative"),
    ),
)
def test_native_kernel_rejects_invalid_build_timeout(
    tmp_path: Path,
    build_timeout: object,
) -> None:
    with pytest.raises(ValueError, match="build_timeout"):
        build_scvrp_legacy_kernel(
            cache_root=tmp_path / "invalid-timeout-cache",
            build_timeout=build_timeout,  # type: ignore[arg-type,call-arg]
        )


def test_native_kernel_build_lock_obeys_deadline(
    native_kernel: Path,
    tmp_path: Path,
) -> None:
    cache_root = tmp_path / "locked-cold-cache"
    artifact_dir = cache_root / native_kernel.parent.name
    artifact_dir.mkdir(parents=True)
    lock_path = artifact_dir / ".build.lock"
    spawn_context = get_context("spawn")
    ready = spawn_context.Event()
    release = spawn_context.Event()
    holder = spawn_context.Process(
        target=_hold_build_lock,
        args=(str(lock_path), ready, release),
    )
    holder.start()

    try:
        assert ready.wait(timeout=5), "spawned process did not acquire the build lock"
        started_at = time.monotonic()
        with pytest.raises(SCVRPLegacyKernelError, match="(?i)build lock"):
            build_scvrp_legacy_kernel(
                cache_root=cache_root,
                build_timeout=0.05,  # type: ignore[call-arg]
            )
        assert time.monotonic() - started_at < 1.0
    finally:
        release.set()
        holder.join(timeout=5)
        if holder.is_alive():
            holder.terminate()
            holder.join(timeout=5)

    assert holder.exitcode == 0


def test_native_kernel_valid_cache_does_not_wait_for_stale_build_lock(
    native_kernel: Path,
) -> None:
    cache_root = native_kernel.parent.parent
    lock_path = native_kernel.parent / ".build.lock"
    spawn_context = get_context("spawn")
    ready = spawn_context.Event()
    release = spawn_context.Event()
    holder = spawn_context.Process(
        target=_hold_build_lock,
        args=(str(lock_path), ready, release),
    )
    holder.start()

    try:
        assert ready.wait(timeout=5), "spawned process did not acquire the build lock"
        started_at = time.monotonic()
        assert (
            build_scvrp_legacy_kernel(
                cache_root=cache_root,
                build_timeout=0.5,  # type: ignore[call-arg]
            )
            == native_kernel
        )
        assert time.monotonic() - started_at < 1.0
    finally:
        release.set()
        holder.join(timeout=5)
        if holder.is_alive():
            holder.terminate()
            holder.join(timeout=5)

    assert holder.exitcode == 0


def test_native_kernel_cached_self_test_phase_timeout_rebuilds(
    native_kernel: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        legacy_kernel_module,
        "_SELF_TEST_TIMEOUT_SECONDS",
        0.03,
        raising=False,
    )
    cache_root = tmp_path / "invalid-cached-executable"
    executable = cache_root / native_kernel.parent.name / "scvrp_legacy_runner"
    _write_hanging_executable(executable)
    compiler_version = subprocess.run(
        ["g++", "--version"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    ).stdout
    compiler = tmp_path / "stub-compiler"
    _write_stub_compiler(
        compiler,
        compiler_version=compiler_version,
        linked_executable=native_kernel,
    )

    assert (
        build_scvrp_legacy_kernel(
            cache_root=cache_root,
            compiler=str(compiler),
            build_timeout=1.0,
        )
        == executable
    )
    completed = subprocess.run(
        [str(executable), "--self-test"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=1,
        check=False,
    )
    assert completed.returncode == 0
    assert completed.stdout.strip() == "SCVRP_LEGACY_RUNNER_SELF_TEST_V1"


def test_native_kernel_cached_self_test_uses_global_deadline(
    native_kernel: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        legacy_kernel_module,
        "_SELF_TEST_TIMEOUT_SECONDS",
        1.0,
        raising=False,
    )
    cache_root = tmp_path / "global-self-test-deadline"
    executable = cache_root / native_kernel.parent.name / "scvrp_legacy_runner"
    _write_hanging_executable(executable)

    with pytest.raises(SCVRPLegacyKernelError, match="build timed out"):
        build_scvrp_legacy_kernel(cache_root=cache_root, build_timeout=0.1)


def test_native_kernel_candidate_self_test_phase_timeout_is_explicit_failure(
    native_kernel: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        legacy_kernel_module,
        "_SELF_TEST_TIMEOUT_SECONDS",
        0.03,
        raising=False,
    )
    hanging_candidate = tmp_path / "hanging-candidate"
    _write_hanging_executable(hanging_candidate)
    compiler_version = subprocess.run(
        ["g++", "--version"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    ).stdout
    compiler = tmp_path / "candidate-stub-compiler"
    _write_stub_compiler(
        compiler,
        compiler_version=compiler_version,
        linked_executable=hanging_candidate,
    )
    cache_root = tmp_path / "candidate-self-test-timeout"

    with pytest.raises(SCVRPLegacyKernelError, match="failed its RNG self-test"):
        build_scvrp_legacy_kernel(
            cache_root=cache_root,
            compiler=str(compiler),
            build_timeout=1.0,
        )
    assert list(cache_root.rglob("build-*")) == []


def test_native_kernel_build_lock_retries_interrupted_flock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import fcntl

    real_flock = fcntl.flock
    attempts = 0

    def interrupt_once(file_descriptor: int, operation: int) -> None:
        nonlocal attempts
        if operation & fcntl.LOCK_NB and attempts == 0:
            attempts += 1
            raise InterruptedError(errno.EINTR, "interrupted test flock")
        real_flock(file_descriptor, operation)

    monkeypatch.setattr(fcntl, "flock", interrupt_once)
    with (tmp_path / "interrupted.lock").open("a+b") as lock_file:
        legacy_kernel_module._acquire_build_lock(
            lock_file,
            deadline=time.monotonic() + 1,
        )
        real_flock(lock_file.fileno(), fcntl.LOCK_UN)

    assert attempts == 1


def test_native_build_process_cleans_up_on_base_exception_without_masking(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    interruption = KeyboardInterrupt("test interrupt")

    class InterruptingProcess:
        pid = 12345
        returncode = None

        def communicate(self, timeout: float | None = None) -> tuple[str, str]:
            raise interruption

    process = InterruptingProcess()
    cleanup_calls: list[object] = []

    monkeypatch.setattr(
        legacy_kernel_module.subprocess,
        "Popen",
        lambda *args, **kwargs: process,
    )

    def failing_cleanup(value: object) -> None:
        cleanup_calls.append(value)
        raise RuntimeError("test cleanup failure")

    monkeypatch.setattr(
        legacy_kernel_module,
        "_kill_process_group_and_reap",
        failing_cleanup,
    )

    with pytest.raises(KeyboardInterrupt) as raised:
        legacy_kernel_module._run_build_process(
            ["fake-build-command"],
            deadline=time.monotonic() + 1,
            phase="test phase",
        )

    assert raised.value is interruption
    assert cleanup_calls == [process]
    assert any(
        "test cleanup failure" in note
        for note in getattr(raised.value, "__notes__", ())
    )


@pytest.mark.parametrize(
    ("deadline", "timeout_cap", "finished_at", "expected_timeout"),
    (
        pytest.param(1.0, None, 1.0, 1.0, id="global-deadline"),
        pytest.param(10.0, 0.5, 0.5, 0.5, id="phase-cap"),
    ),
)
def test_native_build_process_rejects_success_returned_at_deadline(
    monkeypatch: pytest.MonkeyPatch,
    deadline: float,
    timeout_cap: float | None,
    finished_at: float,
    expected_timeout: float,
) -> None:
    from types import SimpleNamespace

    readings = iter((0.0, 0.0, 0.0, finished_at))

    def monotonic() -> float:
        return next(readings, finished_at)

    communicate_timeouts: list[float] = []

    class CompletedProcess:
        pid = 12345
        returncode = 0

        def communicate(self, timeout: float | None = None) -> tuple[str, str]:
            assert timeout is not None
            communicate_timeouts.append(timeout)
            return "completed stdout", "completed stderr"

    process = CompletedProcess()
    monkeypatch.setattr(
        legacy_kernel_module,
        "time",
        SimpleNamespace(monotonic=monotonic),
    )
    monkeypatch.setattr(
        legacy_kernel_module.subprocess,
        "Popen",
        lambda *args, **kwargs: process,
    )

    def unexpected_cleanup(*args: object) -> None:
        raise AssertionError("a process returned by communicate is already reaped")

    monkeypatch.setattr(
        legacy_kernel_module,
        "_cleanup_process_after_exception",
        unexpected_cleanup,
    )

    with pytest.raises(subprocess.TimeoutExpired) as raised:
        legacy_kernel_module._run_build_process(
            ["fake-build-command"],
            deadline=deadline,
            phase="test phase",
            timeout_cap=timeout_cap,
        )

    assert communicate_timeouts == [expected_timeout]
    assert raised.value.timeout == expected_timeout
    assert raised.value.output == "completed stdout"
    assert raised.value.stderr == "completed stderr"


def test_native_kernel_checks_deadline_before_publishing_candidate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    phases: list[str] = []
    self_test_calls: list[Path] = []
    replace_calls: list[tuple[object, object]] = []

    def fake_remaining(deadline: float, *, phase: str) -> float:
        phases.append(phase)
        if phase == "publishing compiled executable":
            raise SCVRPLegacyKernelError(
                "native kernel build timed out during publishing compiled executable"
            )
        return 1.0

    def fake_run_checked(
        command: list[str],
        *,
        deadline: float,
        phase: str,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 0, "stub compiler version\n", "")

    def fake_self_test(
        executable: Path,
        *,
        deadline: float,
        phase: str,
    ) -> bool:
        self_test_calls.append(executable)
        return len(self_test_calls) == 3

    def unexpected_replace(source: object, destination: object) -> None:
        replace_calls.append((source, destination))
        raise AssertionError("candidate was published after its deadline")

    monkeypatch.setattr(
        legacy_kernel_module,
        "_remaining_build_time",
        fake_remaining,
    )
    monkeypatch.setattr(legacy_kernel_module, "_run_checked", fake_run_checked)
    monkeypatch.setattr(
        legacy_kernel_module,
        "_kernel_fingerprint",
        lambda source_root, compiler_version: "test-fingerprint",
    )
    monkeypatch.setattr(legacy_kernel_module, "_passes_self_test", fake_self_test)
    monkeypatch.setattr(legacy_kernel_module.os, "replace", unexpected_replace)
    cache_root = tmp_path / "publish-deadline-cache"

    with pytest.raises(SCVRPLegacyKernelError, match="publishing compiled executable"):
        build_scvrp_legacy_kernel(cache_root=cache_root, build_timeout=1.0)

    assert len(self_test_calls) == 3
    assert phases[-1] == "publishing compiled executable"
    assert replace_calls == []
    assert list(cache_root.rglob("build-*")) == []


def test_native_kernel_compiler_version_timeout_is_wrapped_and_cleaned(
    tmp_path: Path,
) -> None:
    import fcntl

    compiler = tmp_path / "hanging-compiler"
    compiler.write_text(
        '''#!/usr/bin/env python3
from pathlib import Path
import signal
import subprocess
import sys

if sys.argv[1:] != ["--version"]:
    raise SystemExit(97)

lock_path = Path(__file__).with_suffix(".held")
child_code = r"""
import fcntl
import signal
import sys

with open(sys.argv[1], "w") as lock_file:
    fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
    print("READY", flush=True)
    signal.pause()
"""
child = subprocess.Popen(
    [sys.executable, "-c", child_code, str(lock_path)],
    text=True,
    stdout=subprocess.PIPE,
)
if child.stdout is None or child.stdout.readline().strip() != "READY":
    raise SystemExit(98)

def bounded_exit(*_):
    child.kill()
    child.wait()
    raise SystemExit(0)

signal.signal(signal.SIGALRM, bounded_exit)
signal.alarm(2)
signal.pause()
''',
        encoding="ascii",
    )
    compiler.chmod(0o755)
    cache_root = tmp_path / "compiler-timeout-cache"

    started_at = time.monotonic()
    with pytest.raises(SCVRPLegacyKernelError):
        build_scvrp_legacy_kernel(
            cache_root=cache_root,
            compiler=str(compiler),
            build_timeout=0.5,  # type: ignore[call-arg]
        )
    assert time.monotonic() - started_at < 1.5
    assert list(cache_root.rglob("build-*")) == []
    assert list(cache_root.rglob("scvrp_legacy_runner")) == []

    held_marker = compiler.with_suffix(".held")
    assert held_marker.exists()
    with held_marker.open("a+b") as marker_file:
        fcntl.flock(marker_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(marker_file.fileno(), fcntl.LOCK_UN)


def test_native_kernel_concurrent_spawn_build_is_atomic(tmp_path: Path) -> None:
    cache_root = tmp_path / "cold-cache"
    assert not cache_root.exists()
    spawn_context = get_context("spawn")

    with spawn_context.Manager() as manager:
        barrier = manager.Barrier(2)
        with ProcessPoolExecutor(max_workers=2, mp_context=spawn_context) as executor:
            futures = [
                executor.submit(
                    _build_native_kernel_after_barrier,
                    str(cache_root),
                    barrier,
                )
                for _ in range(2)
            ]
            built_paths = [Path(future.result(timeout=60)) for future in futures]

    assert built_paths[0] == built_paths[1]
    executable = built_paths[0]
    assert executable.is_file()
    completed = subprocess.run(
        [str(executable), "--self-test"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=10,
        check=False,
    )
    assert completed.returncode == 0
    assert completed.stdout.strip() == "SCVRP_LEGACY_RUNNER_SELF_TEST_V1"
    assert completed.stderr == ""
    assert list(cache_root.rglob("scvrp_legacy_runner")) == [executable]
    assert list(cache_root.rglob("build-*")) == []


def test_native_kernel_timeout_kills_child_and_cached_executable_recovers(
    native_kernel: Path,
) -> None:
    problem = _problem()
    long_request = SCVRPLegacyKernelRequest(
        seed=1,
        termination_mode="fixed_iterations",
        limit=100_000,
        max_transitions=100_000,
    )

    with pytest.raises(SCVRPLegacyKernelError, match="timed out"):
        run_scvrp_legacy_kernel(
            problem,
            long_request,
            executable=native_kernel,
            timeout=0.01,
        )

    recovered = run_scvrp_legacy_kernel(
        problem,
        SCVRPLegacyKernelRequest(
            seed=1,
            termination_mode="fixed_iterations",
            limit=1,
            max_transitions=1,
        ),
        executable=native_kernel,
        timeout=30,
    )
    assert recovered["generation_count"] == 2
    assert recovered["transition_count"] == 1
    assert recovered["stop_cause"] == "fixed_iterations"
    assert recovered["result"]["objective"] == 437


def test_native_kernel_matches_first_two_archived_generations(native_kernel: Path) -> None:
    result = run_scvrp_legacy_kernel(
        _problem(),
        SCVRPLegacyKernelRequest(
            seed=1,
            termination_mode="fixed_iterations",
            limit=1,
            trace=True,
        ),
        executable=native_kernel,
    )

    assert result["generation_count"] == 2
    assert result["transition_count"] == 1
    assert result["rng_draw_count"] == 16_073
    assert result["trace"][0] == {
        "generation": 1,
        "objective": 493,
        "feasible_solutions": 32,
        "feasible": True,
        "transfer_vehicle_count": 0,
        "routes": [[8], [15, 10, 5], [6], [2], [7, 14], [1, 13, 9], [11, 4], [3, 12]],
        "transferred_customers": [],
    }
    assert result["result"] == {
        "generation": 2,
        "objective": 437,
        "feasible_solutions": 42,
        "feasible": True,
        "transfer_vehicle_count": 1,
        "routes": [[9, 7], [2], [8, 13], [10, 12, 15], [1, 3], [14, 5], [11, 4], [6]],
        "transferred_customers": [2],
    }


def test_python_new_generation_fixed_fingerprint_without_native_kernel() -> None:
    core = CDELS(_problem(), seed=1)
    generation_1 = core.initialize_population()
    generation_1_state = [
        individual.canonical_dict() for individual in generation_1.individuals
    ]

    generation_2 = core._new_generation(generation_1, 1.0)
    trace = core.trace_generation(generation_2, stage="new_generation")

    assert trace.generation_id == 2
    assert trace.population_sha256 == (
        "06f4e6d78618dc2347305efd7ad0db6f811bcb30adb08d23e292458acb3a9695"
    )
    assert trace.population_size == 48
    assert trace.best_index == 10
    assert trace.best_cost == 437
    assert trace.feasible_solutions == 42
    assert trace.rng_state == 2_587_854_408
    assert trace.rng_draw_count == 16_073
    assert [
        index
        for index, (old, new) in enumerate(
            zip(generation_1.individuals, generation_2.individuals, strict=True)
        )
        if old is new
    ] == [0, 38]
    assert [
        individual.canonical_dict() for individual in generation_1.individuals
    ] == generation_1_state


@pytest.mark.parametrize(
    (
        "seed",
        "transitions",
        "temperature",
        "cooling_rate",
        "iterations_per_temperature",
    ),
    (
        pytest.param(1, 6, 1.0, 0.95, 110, id="seed-1-retained-elite"),
        pytest.param(2, 1, 1.0, 0.95, 110, id="seed-2"),
        pytest.param(3, 1, 1.0, 0.95, 110, id="seed-3"),
        pytest.param(3, 3, 1.0, 0.95, 2, id="seed-3-cross-cooling"),
        pytest.param(7, 3, 1.0, 0.95, 2, id="seed-7-cross-cooling"),
        pytest.param(10, 8, 0.95, 0.95, 110, id="seed-10-cooled-temperature"),
    ),
)
def test_python_new_generation_matches_native_population_column_by_column(
    native_kernel: Path,
    seed: int,
    transitions: int,
    temperature: float,
    cooling_rate: float,
    iterations_per_temperature: int,
) -> None:
    native = _assert_python_new_generations_match_native(
        native_kernel,
        seed=seed,
        transitions=transitions,
        temperature=temperature,
        cooling_rate=cooling_rate,
        iterations_per_temperature=iterations_per_temperature,
    )
    if seed == 1:
        assert native["trace"][-1]["best_index"] == -1
        assert native["trace"][-1]["best"]["cost"] == 367


def test_workspace_generation_matches_native_population_column_by_column(
    native_kernel: Path,
) -> None:
    """Workspace 版本也必須直接通過 C++ oracle，不能只比對 Python 基準。"""
    problem = _problem()
    native = run_scvrp_legacy_generation_probe(
        problem,
        SCVRPLegacyKernelRequest(
            seed=1,
            termination_mode="fixed_iterations",
            limit=1,
            start_temperature=1.0,
            cooling_rate=0.95,
            iterations_per_temperature=110,
            probe_new_generation=True,
        ),
        executable=native_kernel,
        timeout=20.0,
    )
    core = CDELSWorkspace(problem, seed=1)
    generation = core.initialize_population()
    _assert_generation_matches_native(
        native["trace"][0],
        generation,
        core,
        stage="workspace_generation_1",
    )

    generation = core._new_generation(generation, 1.0)
    _assert_generation_matches_native(
        native["trace"][1],
        generation,
        core,
        stage="workspace_generation_2",
    )


@pytest.mark.slow
def test_python_full_population_matches_native_through_first_real_cooling_boundary(
    native_kernel: Path,
) -> None:
    _assert_python_new_generations_match_native(
        native_kernel,
        seed=1,
        transitions=111,
        temperature=1.0,
        cooling_rate=0.95,
        iterations_per_temperature=110,
    )


def test_python_step_one_local_search_matches_native_stage_oracle_column_by_column(
    native_kernel: Path,
) -> None:
    _assert_python_step_one_matches_native(
        native_kernel,
        seed=1,
        target_index=0,
    )


@pytest.mark.parametrize(
    ("case", "expected", "expected_state"),
    (
        pytest.param(_SA_ACCEPTANCE_CASES[0], True, 2_147_428_898, id="better-raw-max"),
        pytest.param(_SA_ACCEPTANCE_CASES[1], True, 2_745_024, id="equal-accepted"),
        pytest.param(_SA_ACCEPTANCE_CASES[2], False, 2_147_428_898, id="equal-raw-max"),
        pytest.param(_SA_ACCEPTANCE_CASES[3], True, 2_745_024, id="worse-accepted"),
        pytest.param(_SA_ACCEPTANCE_CASES[4], False, 2_147_428_898, id="worse-rejected"),
        pytest.param(_SA_ACCEPTANCE_CASES[5], False, 2_745_024, id="underflow"),
        pytest.param(_SA_ACCEPTANCE_CASES[6], True, 2_745_024, id="positive-overflow"),
    ),
)
def test_python_sa_acceptance_fixed_vectors_without_native_kernel(
    case: SCVRPLegacySAAcceptanceCase,
    expected: bool,
    expected_state: int,
) -> None:
    core = CDELS(_problem(), seed=999)
    core.rng.srand(case.rng_seed)

    assert (
        core._accept_trial_by_sa(
            case.target_cost,
            case.trial_cost,
            case.temperature,
        )
        is expected
    )
    assert core.rng.state == expected_state
    assert core.rng.draw_count == 1


def test_python_sa_acceptance_matches_native_batch_oracle(native_kernel: Path) -> None:
    _assert_python_sa_acceptance_matches_native(native_kernel)


@pytest.mark.parametrize(
    "target_index",
    (
        pytest.param(0, id="repair-success"),
        pytest.param(2, id="retry-failure"),
        pytest.param(4, id="feasible-not-applicable"),
    ),
)
def test_python_drop_infeasible_matches_native_for_stable_branches(
    native_kernel: Path,
    target_index: int,
) -> None:
    _assert_python_drop_infeasible_matches_native(
        native_kernel,
        seed=1,
        target_index=target_index,
    )


@pytest.mark.slow
@pytest.mark.parametrize(
    "target_index",
    range(10),
    ids=lambda target: f"target-{target}",
)
def test_python_local_search_matches_native_for_first_ten_safe_targets(
    native_kernel: Path,
    target_index: int,
) -> None:
    _assert_python_local_search_matches_native(
        native_kernel,
        seed=1,
        target_index=target_index,
    )


@pytest.mark.slow
@pytest.mark.parametrize("seed", range(2, 6), ids=lambda seed: f"seed-{seed}")
def test_python_local_search_matches_native_for_additional_safe_seeds(
    native_kernel: Path,
    seed: int,
) -> None:
    _assert_python_local_search_matches_native(
        native_kernel,
        seed=seed,
        target_index=0,
    )


@pytest.mark.parametrize(
    ("customer", "new_route"),
    (
        pytest.param(1, 1, id="conditional-noop-forced-move"),
        pytest.param(13, 7, id="strict-improvement"),
        pytest.param(10, 7, id="different-forced-best-position"),
    ),
)
def test_python_reinsertion_matches_native_for_stable_vectors(
    native_kernel: Path,
    customer: int,
    new_route: int,
) -> None:
    _assert_python_reinsertion_matches_native(
        native_kernel,
        seed=1,
        target_index=0,
        customer=customer,
        new_route=new_route,
    )


def test_python_mixed_transfer_two_swap_matches_native_column_by_column(
    native_kernel: Path,
) -> None:
    _assert_python_mixed_two_swap_matches_native(
        native_kernel,
        seed=1,
        target_index=0,
        transfer_customer=1,
    )


def test_python_mixed_transfer_strong_drop_matches_native_column_by_column(
    native_kernel: Path,
) -> None:
    _assert_python_mixed_strong_drop_matches_native(
        native_kernel,
        seed=1,
        target_index=0,
        transfer_customer=1,
    )


@pytest.mark.slow
@pytest.mark.parametrize(
    "transfer_customer",
    range(1, 16),
    ids=lambda customer: f"customer-{customer}",
)
def test_python_mixed_transfer_strong_drop_matches_native_for_every_customer(
    native_kernel: Path,
    transfer_customer: int,
) -> None:
    _assert_python_mixed_strong_drop_matches_native(
        native_kernel,
        seed=1,
        target_index=0,
        transfer_customer=transfer_customer,
    )


@pytest.mark.slow
@pytest.mark.parametrize("seed", range(1, 6), ids=lambda seed: f"seed-{seed}")
def test_python_step_one_matches_native_for_first_ten_targets(
    native_kernel: Path,
    seed: int,
) -> None:
    for target_index in range(10):
        _assert_python_step_one_matches_native(
            native_kernel,
            seed=seed,
            target_index=target_index,
        )


def test_native_kernel_reports_transition_safety_limit(native_kernel: Path) -> None:
    result = run_scvrp_legacy_kernel(
        _problem(),
        SCVRPLegacyKernelRequest(
            seed=1,
            termination_mode="legacy_temperature_stagnation",
            limit=100,
            max_transitions=1,
        ),
        executable=native_kernel,
    )

    assert result["stop_cause"] == "max_transitions"
    assert result["generation_count"] == 2
    assert result["transition_count"] == 1
    assert result["trace"] == []


@pytest.mark.slow
@pytest.mark.parametrize("seed", range(1, 11), ids=lambda seed: f"seed-{seed}")
def test_native_kernel_full_trace_matches_archive_for_all_seeds(
    native_kernel: Path,
    seed: int,
) -> None:
    golden = _golden()
    assert golden["schema"] == "optiforge.scvrp-legacy-golden/v1"
    seed_golden = _seed_golden_by_seed(golden)[seed]
    common = golden["common_result"]
    parameters = golden["parameters"]
    assert parameters == {
        "de_technique": "rand_1_exp",
        "start_temperature": 1.0,
        "cooling_rate": 0.95,
        "iterations_per_temperature": 110,
        "max_temperature_stagnation": 100,
    }
    problem = _problem()
    result = run_scvrp_legacy_kernel(
        problem,
        SCVRPLegacyKernelRequest(
            seed=seed,
            termination_mode="legacy_temperature_stagnation",
            limit=int(parameters["max_temperature_stagnation"]),
            start_temperature=float(parameters["start_temperature"]),
            cooling_rate=float(parameters["cooling_rate"]),
            iterations_per_temperature=int(parameters["iterations_per_temperature"]),
            max_transitions=11_330,
            trace=True,
        ),
        executable=native_kernel,
    )

    trace = result["trace"]
    assert len(trace) == common["generation_count"] == 11_221
    for trace_index, row in enumerate(trace):
        expected_generation = trace_index + 1
        assert row["generation"] == expected_generation, (
            f"seed={seed} trace_index={trace_index}: "
            f"generation={row['generation']} != {expected_generation}"
        )

    best_trace = sha256()
    objective_feasible_trace = sha256()
    semantic_trace = sha256()
    for row in trace:
        best_trace.update(f"{row['objective']}\n".encode("ascii"))
        objective_feasible_trace.update(
            f"{row['generation']},{row['objective']},{row['feasible_solutions']}\n".encode(
                "ascii"
            )
        )
        semantic_record = {
            "generation": row["generation"],
            "best": row["objective"],
            "feasible": row["feasible_solutions"],
            # The archive does not print a solution block for generation one.
            "solution": None
            if row["generation"] == 1
            else {
                "cost": row["objective"],
                "routes": row["routes"],
                "transfers": row["transferred_customers"],
                "transfer_cars": row["transfer_vehicle_count"],
            },
        }
        semantic_trace.update(
            (json.dumps(semantic_record, sort_keys=True, separators=(",", ":")) + "\n").encode(
                "ascii"
            )
        )

    assert trace[0]["objective"] == seed_golden["initial_best"]
    assert trace[0]["feasible_solutions"] == seed_golden["initial_feasible"]
    first_optimum_generation = next(
        (
            row["generation"]
            for row in trace
            if row["objective"] == common["objective"]
        ),
        None,
    )
    assert first_optimum_generation == seed_golden["first_optimum_generation"], (
        f"seed={seed}: first objective {common['objective']} generation "
        f"was {first_optimum_generation!r}, expected "
        f"{seed_golden['first_optimum_generation']}"
    )
    assert trace[-1] == result["result"]

    assert result["seed"] == seed
    assert result["termination"] == "legacy_temperature_stagnation"
    assert result["stop_cause"] == "legacy_temperature_stagnation"
    assert result["generation_count"] == common["generation_count"] == 11_221
    assert result["transition_count"] == 11_220
    # Stagnation/temperature are source-derived compatibility guards; the raw
    # archived report independently anchors the observable trace hashes below.
    assert result["temperature_stagnation"] == 101
    assert result["final_temperature_hex"] == "0x1.5e2d52a31c76bp-8"
    expected_rng_state, expected_rng_draw_count = _DERIVED_RNG_FINGERPRINTS[seed]
    assert result["rng_state"] == expected_rng_state
    assert result["rng_draw_count"] == expected_rng_draw_count
    assert result["result"]["objective"] == common["objective"] == 350
    assert result["result"]["feasible_solutions"] == 48
    assert result["result"]["feasible"] is common["feasible"] is True
    assert result["result"]["routes"] == seed_golden["routes"]
    assert result["result"]["transferred_customers"] == common["transferred_customers"]
    assert result["result"]["transfer_vehicle_count"] == common["transfer_vehicle_count"]
    assert best_trace.hexdigest() == seed_golden["best_trace_sha256"]
    assert objective_feasible_trace.hexdigest() == seed_golden["objective_feasible_trace_sha256"]
    assert semantic_trace.hexdigest() == seed_golden["semantic_trace_sha256"]

    evaluation = problem.evaluate(
        result["result"]["routes"],
        result["result"]["transferred_customers"],
    )
    assert evaluation.objective == common["objective"]
    assert evaluation.route_cost == common["route_cost"]
    assert evaluation.transfer_cost == common["transfer_cost"]
    assert evaluation.transferred_demand == common["transferred_demand"]
    assert evaluation.legacy_feasible is common["feasible"]
    assert evaluation.strict_feasible is True
    assert evaluation.violations == ()
