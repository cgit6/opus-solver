"""Shared Numba helpers for the MKP solver implementations."""

from __future__ import annotations

import math

import numpy as np
from numba import njit

from ..tools.ctf_numba import ctf_flip_probability


def _argsort_pop_fit_desc_deterministic(pop_fit: np.ndarray, pop_size: int) -> np.ndarray:
    """Return deterministic descending-fitness indices (lower index wins ties)."""
    idx = np.arange(pop_size, dtype=np.int64)
    for i in range(pop_size):
        best = i
        for j in range(i + 1, pop_size):
            candidate = int(idx[j])
            current = int(idx[best])
            if float(pop_fit[candidate]) > float(pop_fit[current]) or (
                float(pop_fit[candidate]) == float(pop_fit[current]) and candidate < current
            ):
                best = j
        idx[i], idx[best] = idx[best], idx[i]
    return idx


def _expect_mkp_problem_tensors(
    values: np.ndarray,
    weights: np.ndarray,
    capacities: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Validate the int64 C-contiguous tensor contract provided by ProblemModel."""
    for name, array in (("values", values), ("weights", weights), ("capacities", capacities)):
        if array.dtype != np.int64:
            raise TypeError(f"{name}: expected np.int64 from ProblemModel, got {array.dtype}")
        if not array.flags.c_contiguous:
            raise ValueError(f"{name}: must be C-contiguous")
    return values, weights, capacities


@njit(cache=True)
def _ctf_flip_probability_fast(ctf_id: int, x: float) -> float:
    if ctf_id == 0:
        return abs(math.tanh(x))
    if ctf_id == 1:
        if x >= 0.0:
            return 1.0 / (1.0 + math.exp(-x))
        et = math.exp(x)
        return et / (1.0 + et)
    if ctf_id == 9:
        return abs(x) ** 1.6
    return ctf_flip_probability(ctf_id, x)


@njit(cache=True)
def _sort_pop_desc_deterministic_inplace(
    pop_sol: np.ndarray,
    pop_fit: np.ndarray,
    tmp_sol: np.ndarray,
    tmp_fit: np.ndarray,
    idx_work: np.ndarray,
    pop_size: int,
    items: int,
) -> None:
    """Sort population by descending fitness, with the original row index as tie-breaker."""
    for i in range(pop_size):
        idx_work[i] = i

    for i in range(pop_size):
        best = i
        for j in range(i + 1, pop_size):
            candidate = idx_work[j]
            current = idx_work[best]
            candidate_fit = pop_fit[candidate]
            current_fit = pop_fit[current]
            if candidate_fit > current_fit or (
                candidate_fit == current_fit and candidate < current
            ):
                best = j
        tmp_idx = idx_work[i]
        idx_work[i] = idx_work[best]
        idx_work[best] = tmp_idx

    for i in range(pop_size):
        source = idx_work[i]
        for j in range(items):
            tmp_sol[i, j] = pop_sol[source, j]
        tmp_fit[i] = pop_fit[source]

    for i in range(pop_size):
        for j in range(items):
            pop_sol[i, j] = tmp_sol[i, j]
        pop_fit[i] = tmp_fit[i]


@njit(cache=True)
def _map_position_excluding(pos: int, excluded: int) -> int:
    if pos >= excluded:
        return pos + 1
    return pos


@njit(cache=True)
def _select_two_distinct_indices_excluding(pop_size: int, excluded: int) -> tuple[int, int]:
    first_pos = np.random.randint(0, pop_size - 1)
    second_pos = np.random.randint(0, pop_size - 2)
    if second_pos >= first_pos:
        second_pos += 1
    return (
        _map_position_excluding(first_pos, excluded),
        _map_position_excluding(second_pos, excluded),
    )
