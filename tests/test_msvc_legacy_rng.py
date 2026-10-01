from __future__ import annotations

from hashlib import sha256

import pytest

from mkp.rng import MSVC_RAND_MAX, MsvcLegacyRand, make_msvc_legacy_rng


def test_msvc_legacy_rng_matches_microsoft_documented_example() -> None:
    rng = make_msvc_legacy_rng(1792)

    assert [rng.rand() for _ in range(10)] == [
        5890,
        1279,
        19497,
        1207,
        11420,
        3377,
        15317,
        29489,
        9716,
        23323,
    ]


def test_msvc_legacy_rng_matches_windows_ucrt_seed_fingerprint() -> None:
    """Guard the seed 1..10 stream captured from Windows UCRT rand()."""
    payload = "".join(
        f"{seed}:" + ",".join(str(rng.rand()) for _ in range(32)) + "\n"
        for seed in range(1, 11)
        for rng in [MsvcLegacyRand(seed)]
    ).encode("ascii")

    assert sha256(payload).hexdigest() == "158bbea3bdd6b8d011ba0edf0b5be07d5647aa2e2aa8196ffe3e9a1edd1fddc6"


def test_msvc_legacy_rng_srand_restarts_the_sequence() -> None:
    rng = MsvcLegacyRand(123)
    first = [rng.rand() for _ in range(20)]
    assert rng.draw_count == 20

    rng.srand(123)

    assert rng.draw_count == 0
    assert [rng.rand() for _ in range(20)] == first
    assert rng.draw_count == 20


def test_msvc_legacy_rng_uses_unsigned_32_bit_seed_conversion() -> None:
    assert MsvcLegacyRand(-1).rand() == MsvcLegacyRand(0xFFFF_FFFF).rand()
    assert MsvcLegacyRand(0x1_0000_0001).rand() == MsvcLegacyRand(1).rand()


def test_msvc_legacy_rng_legacy_helpers_consume_exactly_one_draw() -> None:
    helper_rng = MsvcLegacyRand(999)
    raw_rng = MsvcLegacyRand(999)

    raw_for_mod = raw_rng.rand()
    assert helper_rng.rand_mod(17) == raw_for_mod % 17

    raw_for_unit = raw_rng.rand()
    assert helper_rng.rand_unit() == raw_for_unit / float(MSVC_RAND_MAX)
    assert helper_rng.draw_count == raw_rng.draw_count == 2


def test_msvc_legacy_rng_rand_mod_rejects_non_positive_modulus() -> None:
    with pytest.raises(ValueError, match="modulus must be > 0"):
        MsvcLegacyRand().rand_mod(0)
