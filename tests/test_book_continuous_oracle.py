from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from mkp.tools.book_continuous_oracle import run_abc_archive_oracle


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "book_continuous" / "abc_seed12345_short.json"


def _archive_path() -> Path:
    matches = sorted((ROOT / "note").glob("《Python智能优化算法：从原理到代码实现与应用》代码-*.zip"))
    if not matches:
        pytest.skip("book continuous source archive is not present")
    if len(matches) != 1:
        raise AssertionError(f"expected one book continuous source archive, found {len(matches)}")
    return matches[0]


def _run_oracle() -> dict[str, object]:
    return run_abc_archive_oracle(
        _archive_path(),
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


def test_abc_archive_oracle_is_repeatable() -> None:
    assert _run_oracle() == _run_oracle()


def test_abc_archive_oracle_matches_frozen_golden() -> None:
    golden = json.loads(FIXTURE.read_text(encoding="utf-8"))
    actual = _run_oracle()

    assert actual["source_sha256"] == golden["source_sha256"]
    assert actual["parameters"] == golden["parameters"]
    assert _canonical_sha256(actual["trace"]) == golden["trace_sha256"]
    assert actual["result"] == golden["result"]
