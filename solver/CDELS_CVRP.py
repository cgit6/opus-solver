"""CDELS for the classical Capacitated Vehicle Routing Problem.

The SCVRP implementation in :mod:`mkp.solver.CDELS` contains a reusable
CVRP core: population initialization, differential mutation, exponential
crossover, route local search, simulated-annealing selection, and the
temperature loop.  This module keeps those operations in the same order and
removes only the two transfer-customer operations that do not exist in CVRP.

Route convention:

* customer ``0`` is the depot and is not stored inside a route;
* every customer ``1..n-1`` occurs in exactly one route;
* empty routes are preserved because they represent unused vehicles.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import math
import time
from typing import Any, ClassVar, Literal

import numpy as np

from ..engine.models import SolveResult
from ..problem.cvrp import (
    CVRPEvaluation,
    CVRPProblem,
    encode_cvrp_solution,
)
from ..problem.interface import Problem
from ..problem.scvrp import LEGACY_INFEASIBILITY_PENALTY
from .CDELS import (
    CDELS,
    CDELSGeneration,
    CDELSIndividual,
    CDELSProcessTrace,
    CDELSRunResult,
    CDELSSnapshot,
    _cpp_hexfloat,
    _local_search,
)


class CDELSCVRP(CDELS):
    """CDELS search state specialized for a plain CVRP problem."""

    def __init__(self, problem: CVRPProblem, *, seed: int) -> None:
        # CDELS.__init__ only reads fields shared by CVRP and SCVRP.  Calling
        # it here also preserves the exact MSVC RNG and population-size rule.
        super().__init__(problem, seed=seed)
        self.problem: CVRPProblem = problem

    def _reevaluate(
        self,
        individual: CDELSIndividual,
    ) -> CVRPEvaluation:
        """Rebuild every derived field from the current ordered routes.

        CDELS uses one fixed ``+100`` score while it repairs an infeasible
        individual.  The raw route length remains available from the returned
        evaluation and is used for the final Engine result once feasible.
        """

        evaluation = self.problem.evaluate(individual.routes)
        individual.cost = evaluation.objective + (
            0 if evaluation.feasible else LEGACY_INFEASIBILITY_PENALTY
        )
        individual.feasible = evaluation.feasible
        individual.route_capacities_free = list(
            evaluation.route_capacities_free
        )

        # These fields exist on the shared Individual representation.  CVRP
        # has no transfer vehicles, so their only valid state is empty/zero.
        individual.transfer_mask.fill(0)
        individual.transfer_capacities_free = []
        individual.transfer_vehicle_count = 0
        individual.transfer_total_capacity_free = 0
        return evaluation

    def _local_search(self, individual: CDELSIndividual) -> None:
        """Run the CDELS route search without SCVRP transfer operations.

        The shared control loop still performs, in order, two-swap,
        strong-drop (best reinsertion), and infeasible-route repair.  The two
        no-op callbacks occupy the places where SCVRP changes transfer state;
        they deliberately consume no random number because CVRP has no such
        decision.
        """

        _local_search(
            individual,
            turn_random_customer_to_transfer=_no_transfer_operation,
            two_swap_move=self._two_swap,
            strong_drop_move=self._strong_drop,
            drop_one_point_infeasible_move=(
                self._drop_one_point_infeasible
            ),
            turn_random_transfer_to_nontransfer=_no_transfer_operation,
            reevaluate=self._reevaluate,
        )

    def process_trace_generation(
        self,
        generation: CDELSGeneration,
    ) -> CDELSProcessTrace:
        """Hash the complete CVRP population, elite identity, and RNG state."""

        if len(generation.individuals) != self.population_size:
            raise ValueError("CDELS-CVRP population size changed during tracing")
        best_index = generation.best_index
        identity_matches = sum(
            individual is generation.best_solution
            for individual in generation.individuals
        )
        if identity_matches not in {0, 1}:
            raise ValueError("CDELS-CVRP elite appears in multiple population slots")
        if (best_index == -1) != (identity_matches == 0):
            raise ValueError("CDELS-CVRP elite identity/index mismatch")

        payload = {
            "schema": "CVRP_FULL_POP_V1",
            "generation": generation.generation_id,
            "feasible_solutions": generation.feasible_solutions,
            "best_index": best_index,
            "rng_state": self.rng.state,
            "rng_draw_count": self.rng.draw_count,
            "population": [
                individual.canonical_dict()
                for individual in generation.individuals
            ],
            # The elite can survive outside the current population after SA
            # selection, so it must be hashed separately as well.
            "elite": generation.best_solution.canonical_dict(),
        }
        encoded = json.dumps(
            payload,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("ascii")
        return CDELSProcessTrace(
            generation=generation.generation_id,
            canonical_digest=sha256(encoded).hexdigest(),
            rng_state=self.rng.state,
            rng_draw_count=self.rng.draw_count,
        )


def _no_transfer_operation(individual: CDELSIndividual) -> bool:
    """CVRP placeholder for the two SCVRP-only transfer steps."""

    del individual
    return False


# ============================================================
# Engine adapter
# ============================================================

CDELS_CVRP_SOLVER_ID = "cdels_cvrp"
CDELS_CVRP_PROFILE = "cdels_cvrp_v1"
_DE_TECHNIQUE = "rand_1_exp"
_EXPECTED_START_TEMPERATURE = 1.0
_EXPECTED_COOLING_RATE = 0.95
_EXPECTED_ITERATIONS_PER_TEMPERATURE = 110
_ALLOWED_PARAMS = {
    "algorithm_profile",
    "de_technique",
    "termination_mode",
    "start_temperature",
    "cooling_rate",
    "iterations_per_temperature",
}


@dataclass(frozen=True)
class _AdapterConfig:
    run_seed: int
    max_iterations: int
    termination_mode: Literal["fixed_iterations"]
    start_temperature: float
    cooling_rate: float
    iterations_per_temperature: int


class CDELSCVRPSolverError(RuntimeError):
    """The CDELS-CVRP core violated its Engine-facing contract."""


@dataclass(frozen=True)
class CDELSCVRPSolver:
    """Run :class:`CDELSCVRP` through the standard OptiForge interface."""

    core_class: ClassVar[type[CDELSCVRP]] = CDELSCVRP
    execution_backend: ClassVar[str] = "python"
    solver_id: ClassVar[str] = CDELS_CVRP_SOLVER_ID

    def solve(
        self,
        problem: Problem,
        config: dict[str, Any],
        rng: np.random.Generator,
    ) -> SolveResult:
        # The algorithm owns an MSVC-compatible RNG.  Mixing in the Engine's
        # NumPy generator would make an identical run_seed non-reproducible.
        del rng
        if not isinstance(problem, CVRPProblem):
            raise TypeError("CDELSCVRPSolver only supports CVRPProblem")
        adapter = _parse_adapter_config(config)

        algorithm = self.core_class(problem, seed=adapter.run_seed)
        started = time.perf_counter()
        output = algorithm.solve(
            termination_mode=adapter.termination_mode,
            limit=adapter.max_iterations,
            start_temperature=adapter.start_temperature,
            cooling_rate=adapter.cooling_rate,
            iterations_per_temperature=adapter.iterations_per_temperature,
            max_transitions=adapter.max_iterations,
            trace=False,
            process_trace=False,
        )
        runtime = time.perf_counter() - started
        _validate_core_output(output, expected_transitions=adapter.max_iterations)

        result = output.result
        evaluation = problem.evaluate(result.routes)
        search_penalty = (
            0 if evaluation.feasible else LEGACY_INFEASIBILITY_PENALTY
        )
        search_score = evaluation.objective + search_penalty
        if result.objective != search_score:
            raise CDELSCVRPSolverError(
                "CDELS-CVRP/evaluator search-score mismatch: "
                f"{result.objective} != {search_score}"
            )
        if result.feasible != evaluation.feasible:
            raise CDELSCVRPSolverError(
                "CDELS-CVRP/evaluator feasibility mismatch"
            )
        if result.transferred_customers or result.transfer_vehicle_count != 0:
            raise CDELSCVRPSolverError(
                "CDELS-CVRP returned transfer state for a CVRP problem"
            )

        encoded = encode_cvrp_solution(result.routes)
        population_size = 3 * problem.n_customers
        if not 0 <= result.feasible_solutions <= population_size:
            raise CDELSCVRPSolverError(
                "CDELS-CVRP returned an invalid feasible-solution count"
            )
        return SolveResult(
            problem_id=problem.problem_id,
            solver_id=self.solver_id,
            run_seed=adapter.run_seed,
            best_solution=encoded,
            # The public problem objective is route length.  The temporary
            # infeasibility penalty belongs to the search and is kept only in
            # metadata, so objective meaning stays consistent system-wide.
            best_objective=evaluation.objective,
            feasible=evaluation.feasible,
            evaluation_count=population_size * output.generation_count,
            stop_reason="max_iterations_reached",
            runtime=runtime,
            linprog_runtime=0.0,
            error=None,
            metadata={
                "algorithm_profile": CDELS_CVRP_PROFILE,
                "de_technique": _DE_TECHNIQUE,
                "execution_backend": self.execution_backend,
                "termination_mode": adapter.termination_mode,
                "stop_cause": output.stop_cause,
                "population_size": population_size,
                "generation_count": output.generation_count,
                "transition_count": output.transition_count,
                "feasible_solution_count": result.feasible_solutions,
                "temperature_stagnation": output.temperature_stagnation,
                "final_temperature_hex": _cpp_hexfloat(
                    output.final_temperature
                ),
                "rng_algorithm": "msvc_rand",
                "rng_state": output.rng_state,
                "rng_draw_count": output.rng_draw_count,
                "raw_objective": evaluation.objective,
                "search_penalty": search_penalty,
                "search_score": search_score,
            },
        )


def _parse_adapter_config(config: dict[str, Any]) -> _AdapterConfig:
    """Reject incomplete settings instead of silently changing the run."""

    if not isinstance(config, dict):
        raise TypeError("config must be a mapping")
    if "run_seed" not in config:
        raise ValueError("run_seed is required for CDELS-CVRP")
    run_seed = _strict_int(config["run_seed"], name="run_seed")
    if not 0 < run_seed <= 0xFFFF_FFFF:
        raise ValueError("run_seed must be in unsigned 32-bit range 1..4294967295")
    if str(config.get("solver_id", CDELS_CVRP_SOLVER_ID)) != CDELS_CVRP_SOLVER_ID:
        raise ValueError(f"solver_id must be {CDELS_CVRP_SOLVER_ID!r}")

    stop = config.get("stop_condition")
    if not isinstance(stop, dict) or stop.get("type") != "max_iterations":
        raise ValueError(
            "CDELS-CVRP requires stop_condition.type=max_iterations"
        )
    max_iterations = _strict_int(
        stop.get("max_iterations"),
        name="stop_condition.max_iterations",
    )
    if not 0 < max_iterations <= 0x7FFF_FFFE:
        raise ValueError("stop_condition.max_iterations is outside the valid range")

    params = config.get("params")
    if not isinstance(params, dict):
        raise ValueError("params must be a mapping")
    unknown = sorted(set(params) - _ALLOWED_PARAMS)
    missing = sorted(_ALLOWED_PARAMS - set(params))
    if unknown:
        raise ValueError(f"unsupported CDELS-CVRP params: {unknown}")
    if missing:
        raise ValueError(f"missing CDELS-CVRP params: {missing}")
    if params["algorithm_profile"] != CDELS_CVRP_PROFILE:
        raise ValueError(
            f"params.algorithm_profile must be {CDELS_CVRP_PROFILE!r}"
        )
    if params["de_technique"] != _DE_TECHNIQUE:
        raise ValueError(f"params.de_technique must be {_DE_TECHNIQUE!r}")
    if params["termination_mode"] != "fixed_iterations":
        raise ValueError("params.termination_mode must be 'fixed_iterations'")

    start_temperature = _strict_float(
        params["start_temperature"],
        name="params.start_temperature",
    )
    cooling_rate = _strict_float(
        params["cooling_rate"],
        name="params.cooling_rate",
    )
    iterations_per_temperature = _strict_int(
        params["iterations_per_temperature"],
        name="params.iterations_per_temperature",
    )
    if start_temperature != _EXPECTED_START_TEMPERATURE:
        raise ValueError("params.start_temperature must be 1.0")
    if cooling_rate != _EXPECTED_COOLING_RATE:
        raise ValueError("params.cooling_rate must be 0.95")
    if iterations_per_temperature != _EXPECTED_ITERATIONS_PER_TEMPERATURE:
        raise ValueError("params.iterations_per_temperature must be 110")
    return _AdapterConfig(
        run_seed=run_seed,
        max_iterations=max_iterations,
        termination_mode="fixed_iterations",
        start_temperature=start_temperature,
        cooling_rate=cooling_rate,
        iterations_per_temperature=iterations_per_temperature,
    )


def _strict_int(value: Any, *, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, np.integer)):
        raise ValueError(f"{name} must be an integer")
    return int(value)


def _strict_float(value: Any, *, name: str) -> float:
    if isinstance(value, bool) or not isinstance(
        value,
        (int, float, np.integer, np.floating),
    ):
        raise ValueError(f"{name} must be numeric")
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError(f"{name} must be finite")
    return parsed


def _validate_core_output(
    output: CDELSRunResult,
    *,
    expected_transitions: int,
) -> None:
    if not isinstance(output, CDELSRunResult):
        raise CDELSCVRPSolverError("CDELS-CVRP returned an invalid loop result")
    if not isinstance(output.result, CDELSSnapshot):
        raise CDELSCVRPSolverError("CDELS-CVRP returned an invalid snapshot")
    if output.termination != "fixed_iterations":
        raise CDELSCVRPSolverError("CDELS-CVRP changed the termination mode")
    if output.stop_cause != "fixed_iterations":
        raise CDELSCVRPSolverError(
            f"CDELS-CVRP stopped unexpectedly: {output.stop_cause}"
        )
    if output.transition_count != expected_transitions:
        raise CDELSCVRPSolverError(
            "CDELS-CVRP returned a different transition count"
        )
    if output.generation_count != output.transition_count + 1:
        raise CDELSCVRPSolverError("CDELS-CVRP generation count is invalid")
    if output.result.generation != output.generation_count:
        raise CDELSCVRPSolverError("CDELS-CVRP snapshot generation mismatch")
    if output.trace or output.process_trace or output.process_trace_sha256 is not None:
        raise CDELSCVRPSolverError(
            "Engine execution requires CDELS-CVRP tracing to be disabled"
        )
