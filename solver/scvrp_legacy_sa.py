"""System adapter for the archived SCVRP CDELS-SA compatibility kernel."""

from __future__ import annotations

from dataclasses import dataclass
import math
import time
from typing import Any, Literal

import numpy as np

from ..engine.models import SolveResult
from ..problem import Problem, SCVRPProblem
from ..problem.scvrp import encode_scvrp_solution
from .scvrp_legacy_kernel import (
    PROTOCOL,
    SCVRPLegacyKernelError,
    SCVRPLegacyKernelRequest,
    build_scvrp_legacy_kernel,
    run_scvrp_legacy_kernel,
)


SOLVER_ID = "scvrp_legacy_sa"
COMPATIBILITY_PROFILE = "vs2019_v142_archive"
DE_TECHNIQUE = "rand_1_exp"
_EXPECTED_START_TEMPERATURE = 1.0
_EXPECTED_COOLING_RATE = 0.95
_EXPECTED_ITERATIONS_PER_TEMPERATURE = 110
_ALLOWED_PARAMS = {
    "compatibility_profile",
    "de_technique",
    "termination_mode",
    "start_temperature",
    "cooling_rate",
    "iterations_per_temperature",
    "timeout_seconds",
}


@dataclass(frozen=True)
class _AdapterConfig:
    run_seed: int
    max_iterations: int
    termination_mode: Literal["fixed_iterations"]
    start_temperature: float
    cooling_rate: float
    iterations_per_temperature: int
    timeout_seconds: float


@dataclass(frozen=True)
class _NativeOutput:
    protocol: str
    seed: int
    termination: str
    stop_cause: str
    generation_count: int
    transition_count: int
    temperature_stagnation: int
    final_temperature_hex: str
    rng_state: int
    rng_draw_count: int
    result_generation: int
    objective: int
    feasible_solution_count: int
    feasible: bool
    transfer_vehicle_count: int
    routes: tuple[tuple[int, ...], ...]
    transferred_customers: tuple[int, ...]
    trace: list[Any]


@dataclass(frozen=True)
class SCVRPLegacySASolver:
    """Run one legacy seed in an isolated native process."""

    def solve(
        self,
        problem: Problem,
        config: dict[str, Any],
        rng: np.random.Generator,
    ) -> SolveResult:
        del rng  # The compatibility profile deliberately uses only MSVC rand().
        if not isinstance(problem, SCVRPProblem):
            raise TypeError("SCVRPLegacySASolver only supports SCVRPProblem")
        adapter = _parse_config(config)

        executable = build_scvrp_legacy_kernel()
        request = SCVRPLegacyKernelRequest(
            seed=adapter.run_seed,
            termination_mode=adapter.termination_mode,
            limit=adapter.max_iterations,
            start_temperature=adapter.start_temperature,
            cooling_rate=adapter.cooling_rate,
            iterations_per_temperature=adapter.iterations_per_temperature,
            max_transitions=adapter.max_iterations,
            trace=False,
        )
        started = time.perf_counter()
        native = run_scvrp_legacy_kernel(
            problem,
            request,
            executable=executable,
            timeout=adapter.timeout_seconds,
        )
        algorithm_runtime = time.perf_counter() - started

        output = _parse_native_output(native)
        if output.protocol != PROTOCOL:
            raise SCVRPLegacyKernelError("native kernel returned a different protocol")
        if output.seed != adapter.run_seed:
            raise SCVRPLegacyKernelError("native kernel returned a different seed")
        if output.termination != adapter.termination_mode:
            raise SCVRPLegacyKernelError("native kernel returned a different termination mode")
        if output.stop_cause != "fixed_iterations":
            raise SCVRPLegacyKernelError(
                f"native kernel stopped unexpectedly: {output.stop_cause}"
            )
        if output.transition_count != adapter.max_iterations:
            raise SCVRPLegacyKernelError("native kernel returned a different transition count")
        if output.generation_count != output.transition_count + 1:
            raise SCVRPLegacyKernelError("native kernel returned an invalid generation count")
        if output.result_generation != output.generation_count:
            raise SCVRPLegacyKernelError("native kernel snapshot generation mismatch")
        if output.trace != []:
            raise SCVRPLegacyKernelError("system adapter requires native trace output to be disabled")

        evaluation = problem.evaluate(output.routes, output.transferred_customers)
        if output.objective != evaluation.objective:
            raise SCVRPLegacyKernelError(
                "native/Python objective mismatch: "
                f"{output.objective} != {evaluation.objective}"
            )
        if output.feasible != evaluation.legacy_feasible:
            raise SCVRPLegacyKernelError("native/Python legacy feasibility mismatch")
        if output.transfer_vehicle_count != evaluation.transfer_vehicle_count:
            raise SCVRPLegacyKernelError("native/Python transfer vehicle count mismatch")

        encoded = encode_scvrp_solution(
            output.routes,
            output.transferred_customers,
            n_customers=problem.n_customers,
        )
        population_size = 3 * problem.n_customers
        if not 0 <= output.feasible_solution_count <= population_size:
            raise SCVRPLegacyKernelError(
                "native kernel returned an invalid feasible solution count"
            )
        evaluation_count = population_size * output.generation_count
        stop_reason = _stop_reason(output.stop_cause)
        return SolveResult(
            problem_id=problem.problem_id,
            solver_id=str(config.get("solver_id", SOLVER_ID)),
            run_seed=adapter.run_seed,
            best_solution=encoded,
            best_objective=output.objective,
            feasible=output.feasible,
            evaluation_count=evaluation_count,
            stop_reason=stop_reason,
            runtime=algorithm_runtime,
            linprog_runtime=0.0,
            error=None,
            metadata={
                "compatibility_profile": COMPATIBILITY_PROFILE,
                "de_technique": DE_TECHNIQUE,
                "native_protocol": output.protocol,
                "termination_mode": adapter.termination_mode,
                "stop_cause": output.stop_cause,
                "population_size": population_size,
                "generation_count": output.generation_count,
                "transition_count": output.transition_count,
                "feasible_solution_count": output.feasible_solution_count,
                "temperature_stagnation": output.temperature_stagnation,
                "final_temperature_hex": output.final_temperature_hex,
                "rng_algorithm": "msvc_rand",
                "rng_state": output.rng_state,
                "rng_draw_count": output.rng_draw_count,
                "transfer_vehicle_count": output.transfer_vehicle_count,
            },
        )


def _parse_config(config: dict[str, Any]) -> _AdapterConfig:
    if not isinstance(config, dict):
        raise TypeError("config must be a mapping")
    if "run_seed" not in config:
        raise ValueError("run_seed is required for SCVRP legacy compatibility")
    run_seed = _strict_int(config["run_seed"], name="run_seed")
    if run_seed <= 0:
        raise ValueError("run_seed must be > 0 for SCVRP legacy compatibility")
    if run_seed > 0xFFFF_FFFF:
        raise ValueError("run_seed must fit in an unsigned 32-bit integer")
    solver_id = str(config.get("solver_id", SOLVER_ID))
    if solver_id != SOLVER_ID:
        raise ValueError(f"solver_id must be {SOLVER_ID!r}")

    stop_condition = config.get("stop_condition")
    if not isinstance(stop_condition, dict) or stop_condition.get("type") != "max_iterations":
        raise ValueError("SCVRP legacy compatibility requires stop_condition.type=max_iterations")
    max_iterations = _strict_int(
        stop_condition.get("max_iterations"),
        name="stop_condition.max_iterations",
    )
    if max_iterations <= 0:
        raise ValueError("stop_condition.max_iterations must be > 0")
    if max_iterations > 0x7FFF_FFFE:
        raise ValueError("stop_condition.max_iterations is too large")

    params = config.get("params")
    if not isinstance(params, dict):
        raise ValueError("params must be a mapping")
    unknown = sorted(set(params) - _ALLOWED_PARAMS)
    if unknown:
        raise ValueError(f"unsupported SCVRP legacy params: {unknown}")
    required = _ALLOWED_PARAMS - {"timeout_seconds"}
    missing = sorted(required - set(params))
    if missing:
        raise ValueError(f"missing SCVRP legacy params: {missing}")

    if params["compatibility_profile"] != COMPATIBILITY_PROFILE:
        raise ValueError(f"params.compatibility_profile must be {COMPATIBILITY_PROFILE!r}")
    if params["de_technique"] != DE_TECHNIQUE:
        raise ValueError(f"params.de_technique must be {DE_TECHNIQUE!r}")
    termination_mode = str(params["termination_mode"])
    if termination_mode != "fixed_iterations":
        raise ValueError("params.termination_mode must be 'fixed_iterations'")

    start_temperature = _strict_float(params["start_temperature"], name="params.start_temperature")
    cooling_rate = _strict_float(params["cooling_rate"], name="params.cooling_rate")
    iterations_per_temperature = _strict_int(
        params["iterations_per_temperature"],
        name="params.iterations_per_temperature",
    )
    timeout_seconds = _strict_float(params.get("timeout_seconds", 120.0), name="params.timeout_seconds")

    if start_temperature != _EXPECTED_START_TEMPERATURE:
        raise ValueError("params.start_temperature must be 1.0 in the compatibility profile")
    if cooling_rate != _EXPECTED_COOLING_RATE:
        raise ValueError("params.cooling_rate must be 0.95 in the compatibility profile")
    if iterations_per_temperature != _EXPECTED_ITERATIONS_PER_TEMPERATURE:
        raise ValueError("params.iterations_per_temperature must be 110 in the compatibility profile")
    if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise ValueError("params.timeout_seconds must be > 0")

    return _AdapterConfig(
        run_seed=run_seed,
        max_iterations=max_iterations,
        termination_mode="fixed_iterations",
        start_temperature=start_temperature,
        cooling_rate=cooling_rate,
        iterations_per_temperature=iterations_per_temperature,
        timeout_seconds=timeout_seconds,
    )


def _strict_int(value: Any, *, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, np.integer)):
        raise ValueError(f"{name} must be an integer")
    return int(value)


def _strict_float(value: Any, *, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float, np.integer, np.floating)):
        raise ValueError(f"{name} must be numeric")
    return float(value)


def _parse_native_output(native: Any) -> _NativeOutput:
    if not isinstance(native, dict):
        raise SCVRPLegacyKernelError("native kernel result must be a JSON object")
    try:
        native_result = native["result"]
        if not isinstance(native_result, dict):
            raise SCVRPLegacyKernelError("native kernel result.result must be a JSON object")

        raw_routes = _native_list(native_result["routes"], name="result.routes")
        routes = tuple(
            tuple(
                _native_int(customer, name=f"result.routes[{route_index}][{customer_index}]")
                for customer_index, customer in enumerate(
                    _native_list(route, name=f"result.routes[{route_index}]")
                )
            )
            for route_index, route in enumerate(raw_routes)
        )
        transferred_customers = tuple(
            _native_int(customer, name=f"result.transferred_customers[{index}]")
            for index, customer in enumerate(
                _native_list(
                    native_result["transferred_customers"],
                    name="result.transferred_customers",
                )
            )
        )
        return _NativeOutput(
            protocol=_native_string(native["protocol"], name="protocol"),
            seed=_native_int(native["seed"], name="seed"),
            termination=_native_string(native["termination"], name="termination"),
            stop_cause=_native_string(native["stop_cause"], name="stop_cause"),
            generation_count=_native_non_negative_int(
                native["generation_count"], name="generation_count"
            ),
            transition_count=_native_non_negative_int(
                native["transition_count"], name="transition_count"
            ),
            temperature_stagnation=_native_non_negative_int(
                native["temperature_stagnation"], name="temperature_stagnation"
            ),
            final_temperature_hex=_native_string(
                native["final_temperature_hex"], name="final_temperature_hex"
            ),
            rng_state=_native_non_negative_int(native["rng_state"], name="rng_state"),
            rng_draw_count=_native_non_negative_int(
                native["rng_draw_count"], name="rng_draw_count"
            ),
            result_generation=_native_non_negative_int(
                native_result["generation"], name="result.generation"
            ),
            objective=_native_int(native_result["objective"], name="result.objective"),
            feasible_solution_count=_native_non_negative_int(
                native_result["feasible_solutions"], name="result.feasible_solutions"
            ),
            feasible=_native_bool(native_result["feasible"], name="result.feasible"),
            transfer_vehicle_count=_native_non_negative_int(
                native_result["transfer_vehicle_count"],
                name="result.transfer_vehicle_count",
            ),
            routes=routes,
            transferred_customers=transferred_customers,
            trace=_native_list(native["trace"], name="trace"),
        )
    except KeyError as exc:
        raise SCVRPLegacyKernelError(
            f"native kernel result is missing field: {exc.args[0]}"
        ) from exc


def _native_int(value: Any, *, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise SCVRPLegacyKernelError(f"native kernel field {name} must be an integer")
    return value


def _native_non_negative_int(value: Any, *, name: str) -> int:
    parsed = _native_int(value, name=name)
    if parsed < 0:
        raise SCVRPLegacyKernelError(f"native kernel field {name} must be >= 0")
    return parsed


def _native_bool(value: Any, *, name: str) -> bool:
    if not isinstance(value, bool):
        raise SCVRPLegacyKernelError(f"native kernel field {name} must be a boolean")
    return value


def _native_string(value: Any, *, name: str) -> str:
    if not isinstance(value, str):
        raise SCVRPLegacyKernelError(f"native kernel field {name} must be a string")
    return value


def _native_list(value: Any, *, name: str) -> list[Any]:
    if not isinstance(value, list):
        raise SCVRPLegacyKernelError(f"native kernel field {name} must be a JSON array")
    return value


def _stop_reason(stop_cause: str) -> str:
    if stop_cause in {"fixed_iterations", "max_transitions"}:
        return "max_iterations_reached"
    raise SCVRPLegacyKernelError(f"native kernel returned unknown stop cause: {stop_cause!r}")
