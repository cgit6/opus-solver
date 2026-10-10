from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from mkp.problem.continuous_objectives import get_continuous_objective
from mkp.solver.GOA import GOACompatibilityResult, run_goa_compatibility
from mkp.tools.book_continuous_oracle import run_goa_archive_oracle


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "book_continuous" / "goa_seed12345_short.json"


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


def _run_python_core(*, process_trace: bool) -> GOACompatibilityResult:
    return run_goa_compatibility(
        compatibility_profile="book_archive_goa_v1",
        population_size=8,
        dimension=2,
        lower_bounds=np.full(2, -10.0, dtype=np.float64),
        upper_bounds=np.full(2, 10.0, dtype=np.float64),
        max_iterations=3,
        objective=get_continuous_objective("sphere").evaluate,
        seed=12345,
        process_trace=process_trace,
    )


def _result_record(result: GOACompatibilityResult) -> dict[str, object]:
    return {
        "best_score": _array_record(result.best_score),
        "best_position": _array_record(result.best_position),
        "curve": _array_record(result.curve),
        "numpy_rng_state_sha256": result.numpy_rng_state_sha256,
        "python_rng_state_sha256": result.python_rng_state_sha256,
    }


def test_goa_python_core_matches_frozen_archive_golden() -> None:
    golden = json.loads(FIXTURE.read_text(encoding="utf-8"))
    result = _run_python_core(process_trace=True)

    assert len(result.trace) == 552
    assert result.evaluation_count == 32
    assert _canonical_sha256(result.trace) == golden["trace_sha256"]
    assert _result_record(result) == golden["result"]


def test_goa_python_core_matches_live_archive_event_by_event() -> None:
    oracle = run_goa_archive_oracle(
        _archive_path(),
        compatibility_profile="book_archive_goa_v1",
        seed=12345,
        population_size=8,
        dimension=2,
        max_iterations=3,
        lower_bound=-10.0,
        upper_bound=10.0,
    )
    result = _run_python_core(process_trace=True)

    assert list(result.trace) == oracle["trace"]
    assert _result_record(result) == oracle["result"]


def test_goa_python_core_is_repeatable_without_trace() -> None:
    first = _run_python_core(process_trace=False)
    second = _run_python_core(process_trace=False)

    assert first.trace == second.trace == ()
    assert _result_record(first) == _result_record(second)
    assert first.evaluation_count == second.evaluation_count == 32


def test_goa_python_core_rejects_unknown_profile() -> None:
    with pytest.raises(ValueError, match="unknown GOA compatibility profile"):
        run_goa_compatibility(
            compatibility_profile="not-a-profile",
            population_size=8,
            dimension=2,
            lower_bounds=np.full(2, -10.0),
            upper_bounds=np.full(2, 10.0),
            max_iterations=3,
            objective=get_continuous_objective("sphere").evaluate,
            seed=12345,
        )
