"""Compatibility PRNG for the legacy Microsoft CRT ``srand``/``rand`` sequence.

This module is intentionally isolated from the default NumPy RNG.  CVRP/SCVRP
compatibility code may use it after the sequence is also checked against the
archived Visual Studio v142 executable.
"""

from __future__ import annotations


MSVC_RAND_MAX = 32_767
_UINT32_MASK = 0xFFFF_FFFF
_MULTIPLIER = 214_013
_INCREMENT = 2_531_011


class MsvcLegacyRand:
    """Reproduce the well-known Microsoft CRT 32-bit ``rand`` sequence."""

    __slots__ = ("_draw_count", "_state")

    def __init__(self, seed: int = 1) -> None:
        self.srand(seed)

    @property
    def state(self) -> int:
        """Return the current unsigned 32-bit internal state."""
        return self._state

    @property
    def draw_count(self) -> int:
        """Return how many values have been drawn since the latest ``srand``."""
        return self._draw_count

    def srand(self, seed: int) -> None:
        """Reset the generator as if ``srand((unsigned int) seed)`` was called."""
        self._state = int(seed) & _UINT32_MASK
        self._draw_count = 0

    def rand(self) -> int:
        """Return the next integer in the inclusive range ``0..32767``."""
        self._state = (self._state * _MULTIPLIER + _INCREMENT) & _UINT32_MASK
        self._draw_count += 1
        return (self._state >> 16) & MSVC_RAND_MAX

    def rand_mod(self, modulus: int) -> int:
        """Mirror the legacy ``rand() % modulus`` expression."""
        modulus = int(modulus)
        if modulus <= 0:
            raise ValueError("modulus must be > 0")
        return self.rand() % modulus

    def rand_unit(self) -> float:
        """Mirror the legacy ``rand() / (double) RAND_MAX`` expression."""
        return self.rand() / float(MSVC_RAND_MAX)


def make_msvc_legacy_rng(seed: int) -> MsvcLegacyRand:
    """Build an isolated Microsoft CRT-compatible legacy RNG."""
    return MsvcLegacyRand(seed)
