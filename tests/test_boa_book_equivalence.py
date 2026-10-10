from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from mkp.problem.continuous_objectives import get_continuous_objective
from mkp.solver.BOA import BOACompatibilityResult, run_boa_compatibility
from mkp.tools.book_continuous_oracle import run_boa_archive_oracle


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "book_continuous"
PROFILES = (
    ("book_archive_boa_base_v1", "boa_base_seed12345_short.json"),
    ("book_archive_boa_spring_v1", "boa_spring_seed12345_short.json"),
)


def _archive_path() -> Path:
    matches = sorted((ROOT / "note").glob("《Python智能优化算法：从原理到代码实现与应用》代码-*.zip"))
    if not matches:
        pytest.skip("book continuous source archive is not present")
    if len(matches) != 1:
        raise AssertionError(f"expected one book continuous source archive, found {len(matches)}")
    return matches[0]


def _array_record(value: Any) -> dict[str, Any]:
    array = np.ascontiguousarray(np.asarray(value))
    record: dict[str, Any] = {
        "shape": list(array.shape),
        "dtype": array.dtype.str,
        "sha256": hashlib.sha256(array.tobytes(order="C")).hexdigest(),
    }
    if array.dtype.kind == "f" and array.size <= 32:
        record["float_hex"] = [float(item).hex() for item in array.reshape(-1)]
    elif array.dtype.kind in "iu" and array.size <= 32:
        record["values"] = [int(item) for item in array.reshape(-1)]
    return record


def _canonical_sha256(value: object) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _run_python_core(profile: str, *, process_trace: bool) -> BOACompatibilityResult:
    return run_boa_compatibility(
        compatibility_profile=profile,
        population_size=8,
        dimension=2,
        lower_bounds=np.full(2, -10.0, dtype=np.float64),
        upper_bounds=np.full(2, 10.0, dtype=np.float64),
        max_iterations=3,
        objective=get_continuous_objective("sphere").evaluate,
        seed=12345,
        process_trace=process_trace,
    )


def _result_record(result: BOACompatibilityResult) -> dict[str, object]:
    return {
        "best_score": _array_record(result.best_score),
        "best_position": _array_record(result.best_position),
        "curve": _array_record(result.curve),
        "numpy_rng_state_sha256": result.numpy_rng_state_sha256,
        "python_rng_state_sha256": result.python_rng_state_sha256,
    }


@pytest.mark.parametrize(("profile", "fixture_name"), PROFILES)
def test_boa_python_core_matches_profile_golden(profile: str, fixture_name: str) -> None:
    golden = json.loads((FIXTURE_ROOT / fixture_name).read_text(encoding="utf-8"))
    result = _run_python_core(profile, process_trace=True)

    assert len(result.trace) == 84
    assert result.evaluation_count == 76
    assert _canonical_sha256(result.trace) == golden["trace_sha256"]
    assert _result_record(result) == golden["result"]


@pytest.mark.parametrize(("profile", "fixture_name"), PROFILES)
def test_boa_python_core_matches_live_archive_event_by_event(
    profile: str,
    fixture_name: str,
) -> None:
    del fixture_name
    oracle = run_boa_archive_oracle(
        _archive_path(),
        compatibility_profile=profile,
        seed=12345,
        population_size=8,
        dimension=2,
        max_iterations=3,
        lower_bound=-10.0,
        upper_bound=10.0,
    )
    result = _run_python_core(profile, process_trace=True)

    assert list(result.trace) == oracle["trace"]
    assert _result_record(result) == oracle["result"]


@pytest.mark.parametrize(("profile", "fixture_name"), PROFILES)
def test_boa_python_core_is_repeatable_without_trace(profile: str, fixture_name: str) -> None:
    del fixture_name
    first = _run_python_core(profile, process_trace=False)
    second = _run_python_core(profile, process_trace=False)

    assert first.trace == second.trace == ()
    assert _result_record(first) == _result_record(second)
    assert first.evaluation_count == second.evaluation_count == 76


def test_boa_python_core_rejects_unknown_profile() -> None:
    with pytest.raises(ValueError, match="unknown BOA compatibility profile"):
        _run_python_core("not-a-profile", process_trace=False)
