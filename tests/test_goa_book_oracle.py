from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

import pytest

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


def _run() -> dict[str, object]:
    return run_goa_archive_oracle(
        _archive_path(),
        compatibility_profile="book_archive_goa_v1",
        seed=12345,
        population_size=8,
        dimension=2,
        max_iterations=3,
        lower_bound=-10.0,
        upper_bound=10.0,
    )


def _canonical_sha256(value: object) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def test_goa_archive_oracle_is_repeatable() -> None:
    assert _run() == _run()


def test_goa_archive_oracle_matches_golden() -> None:
    golden = json.loads(FIXTURE.read_text(encoding="utf-8"))
    actual = _run()

    assert actual["compatibility_profile"] == golden["compatibility_profile"]
    assert actual["source_sha256"] == golden["source_sha256"]
    assert actual["parameters"] == golden["parameters"]
    assert _canonical_sha256(actual["trace"]) == golden["trace_sha256"]
    assert actual["result"] == golden["result"]
    assert len(actual["trace"]) == 552
    assert Counter(event["name"] for event in actual["trace"]) == {
        "initialization": 1,
        "objective": 32,
        "CaculateFitness": 4,
        "SortFitness": 4,
        "SortPosition": 4,
        "BorderCheck": 3,
        "distance": 168,
        "S_func": 336,
    }
    assert actual["captured_stdout"] == (
        "第 0 次迭代\n第 1 次迭代\n第 2 次迭代\n"
    )
