from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

import pytest

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


def _run(profile: str) -> dict[str, object]:
    return run_boa_archive_oracle(
        _archive_path(),
        compatibility_profile=profile,
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


@pytest.mark.parametrize(("profile", "fixture_name"), PROFILES)
def test_boa_archive_oracle_is_repeatable(profile: str, fixture_name: str) -> None:
    del fixture_name
    assert _run(profile) == _run(profile)


@pytest.mark.parametrize(("profile", "fixture_name"), PROFILES)
def test_boa_archive_oracle_matches_profile_golden(profile: str, fixture_name: str) -> None:
    golden = json.loads((FIXTURE_ROOT / fixture_name).read_text(encoding="utf-8"))
    actual = _run(profile)

    assert actual["compatibility_profile"] == golden["compatibility_profile"]
    assert actual["source_sha256"] == golden["source_sha256"]
    assert actual["parameters"] == golden["parameters"]
    assert _canonical_sha256(actual["trace"]) == golden["trace_sha256"]
    assert actual["result"] == golden["result"]
    assert len(actual["trace"]) == 84
    assert Counter(event["name"] for event in actual["trace"]) == {
        "initialization": 1,
        "objective": 76,
        "CaculateFitness": 4,
        "BorderCheck": 3,
    }
    assert actual["captured_stdout"] == "第0次迭代\n第1次迭代\n第2次迭代\n"


def test_boa_profiles_are_numerically_distinct() -> None:
    base = _run("book_archive_boa_base_v1")
    spring = _run("book_archive_boa_spring_v1")

    assert base["source_sha256"] != spring["source_sha256"]
    assert base["trace"] != spring["trace"]
    assert base["result"]["best_score"] != spring["result"]["best_score"]
