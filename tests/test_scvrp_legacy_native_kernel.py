from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

import pytest

from mkp.problem.scvrp import load_legacy_scvrp_problem
from mkp.solver.scvrp_legacy_kernel import (
    SCVRPLegacyKernelRequest,
    build_scvrp_legacy_kernel,
    run_scvrp_legacy_kernel,
    verify_legacy_source_hashes,
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


def _golden() -> dict[str, object]:
    return json.loads(
        (FIXTURES / "p_n16_k8_seeds_1_10_golden.json").read_text(encoding="ascii")
    )


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


def test_native_kernel_reuses_content_addressed_build(native_kernel: Path) -> None:
    assert native_kernel.is_file()
    assert build_scvrp_legacy_kernel(cache_root=native_kernel.parent.parent) == native_kernel


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
def test_native_kernel_seed_one_full_trace_matches_archive(native_kernel: Path) -> None:
    golden = _golden()
    seed_golden = golden["seeds"][0]
    common = golden["common_result"]
    problem = _problem()
    result = run_scvrp_legacy_kernel(
        problem,
        SCVRPLegacyKernelRequest(
            seed=1,
            termination_mode="legacy_temperature_stagnation",
            limit=100,
            trace=True,
        ),
        executable=native_kernel,
    )

    best_trace = sha256()
    objective_feasible_trace = sha256()
    semantic_trace = sha256()
    for index, row in enumerate(result["trace"]):
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
            "solution": None
            if index == 0
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

    assert result["generation_count"] == common["generation_count"] == 11_221
    assert result["transition_count"] == 11_220
    assert result["temperature_stagnation"] == 101
    assert result["rng_draw_count"] == 9_603_103
    assert result["result"]["objective"] == common["objective"] == 350
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
