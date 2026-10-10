"""Read-only oracle runner for the book's archived continuous algorithms.

The archive is never extracted or modified.  This module executes only the
whitelisted imports and function definitions from one algorithm file, seeds
both legacy RNG streams, and returns bit-oriented trace fingerprints.
"""

from __future__ import annotations

import argparse
import ast
import contextlib
import hashlib
import io
import json
import math
import random
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from zipfile import ZipFile

import numpy as np

from ..problem.continuous_objectives import get_continuous_objective


_ALLOWED_IMPORT_ROOTS = {"copy", "math", "numpy", "random"}
_ABC_TRACED_FUNCTIONS = (
    "initialization",
    "BorderCheck",
    "CaculateFitness",
    "SortFitness",
    "SortPosition",
    "RouletteWheelSelection",
)
_BOA_TRACED_FUNCTIONS = (
    "initialization",
    "BorderCheck",
    "CaculateFitness",
)
_GOA_TRACED_FUNCTIONS = (
    "initialization",
    "BorderCheck",
    "CaculateFitness",
    "SortFitness",
    "SortPosition",
    "distance",
    "S_func",
)
_GSA_TRACED_FUNCTIONS = (
    "initialization",
    "BorderCheck",
    "CaculateFitness",
    "SortFitness",
    "SortPosition",
)

BOA_PROFILE_MEMBER_SUFFIXES = {
    "book_archive_boa_base_v1": "/chapter4/4.3.1/BOA.py",
    "book_archive_boa_spring_v1": "/chapter4/4.3.4/BOA.py",
}
GOA_PROFILE_MEMBER_SUFFIXES = {
    "book_archive_goa_v1": "/chapter3/3.3.1/GOA.py",
}
GSA_PROFILE_MEMBER_SUFFIXES = {
    "book_archive_gsa_v1": "/chapter9/9.3.1/GSA.py",
}


@dataclass(frozen=True)
class BookABCEngineeringCase:
    """Parameters written in the corresponding chapter 2 ``main.py``."""

    main_member_suffix: str
    population_size: int
    dimension: int
    max_iterations: int
    lower_bounds: tuple[float, ...]
    upper_bounds: tuple[float, ...]


ABC_ENGINEERING_CASES: dict[str, BookABCEngineeringCase] = {
    "pressure_vessel": BookABCEngineeringCase(
        main_member_suffix="/chapter2/2.3.2/main.py",
        population_size=50,
        dimension=4,
        max_iterations=500,
        lower_bounds=(0.0, 0.0, 10.0, 10.0),
        upper_bounds=(100.0, 100.0, 100.0, 100.0),
    ),
    "three_bar_truss": BookABCEngineeringCase(
        main_member_suffix="/chapter2/2.3.3/main.py",
        population_size=30,
        dimension=2,
        max_iterations=100,
        lower_bounds=(0.001, 0.001),
        upper_bounds=(1.0, 1.0),
    ),
    "tension_compression_spring": BookABCEngineeringCase(
        main_member_suffix="/chapter2/2.3.4/main.py",
        population_size=30,
        dimension=3,
        max_iterations=100,
        lower_bounds=(0.05, 0.25, 2.0),
        upper_bounds=(2.0, 1.3, 15.0),
    ),
}


@dataclass(frozen=True)
class BookBOAEngineeringCase:
    main_member_suffix: str
    compatibility_profile: str
    population_size: int
    dimension: int
    max_iterations: int
    lower_bounds: tuple[float, ...]
    upper_bounds: tuple[float, ...]


BOA_ENGINEERING_CASES: dict[str, BookBOAEngineeringCase] = {
    "pressure_vessel": BookBOAEngineeringCase(
        main_member_suffix="/chapter4/4.3.2/main.py",
        compatibility_profile="book_archive_boa_base_v1",
        population_size=50,
        dimension=4,
        max_iterations=500,
        lower_bounds=(0.0, 0.0, 10.0, 10.0),
        upper_bounds=(100.0, 100.0, 100.0, 100.0),
    ),
    "three_bar_truss": BookBOAEngineeringCase(
        main_member_suffix="/chapter4/4.3.3/main.py",
        compatibility_profile="book_archive_boa_base_v1",
        population_size=30,
        dimension=2,
        max_iterations=100,
        lower_bounds=(0.001, 0.001),
        upper_bounds=(1.0, 1.0),
    ),
    "tension_compression_spring": BookBOAEngineeringCase(
        main_member_suffix="/chapter4/4.3.4/main.py",
        compatibility_profile="book_archive_boa_spring_v1",
        population_size=30,
        dimension=3,
        max_iterations=100,
        lower_bounds=(0.05, 0.25, 2.0),
        upper_bounds=(2.0, 1.3, 15.0),
    ),
}


@dataclass(frozen=True)
class BookGOAEngineeringCase:
    algorithm_member_suffix: str
    main_member_suffix: str
    population_size: int
    dimension: int
    max_iterations: int
    lower_bounds: tuple[float, ...]
    upper_bounds: tuple[float, ...]


GOA_ENGINEERING_CASES: dict[str, BookGOAEngineeringCase] = {
    "pressure_vessel": BookGOAEngineeringCase(
        algorithm_member_suffix="/chapter3/3.3.2/GOA.py",
        main_member_suffix="/chapter3/3.3.2/main.py",
        population_size=50,
        dimension=4,
        max_iterations=500,
        lower_bounds=(0.0, 0.0, 10.0, 10.0),
        upper_bounds=(100.0, 100.0, 100.0, 100.0),
    ),
    "three_bar_truss": BookGOAEngineeringCase(
        algorithm_member_suffix="/chapter3/3.3.3/GOA.py",
        main_member_suffix="/chapter3/3.3.3/main.py",
        population_size=30,
        dimension=2,
        max_iterations=100,
        lower_bounds=(0.001, 0.001),
        upper_bounds=(1.0, 1.0),
    ),
    "tension_compression_spring": BookGOAEngineeringCase(
        algorithm_member_suffix="/chapter3/3.3.4/GOA.py",
        main_member_suffix="/chapter3/3.3.4/main.py",
        population_size=30,
        dimension=3,
        max_iterations=100,
        lower_bounds=(0.05, 0.25, 2.0),
        upper_bounds=(2.0, 1.3, 15.0),
    ),
}


class _LegacyNumpyProxy:
    """Restore the old ``np.math`` alias while forwarding every other NumPy name."""

    math = math

    def __getattr__(self, name: str) -> Any:
        return getattr(np, name)


def _load_algorithm_namespace(
    archive: Path,
    algorithm: str,
    *,
    member_suffix: str | None = None,
) -> tuple[dict[str, Any], str, str]:
    target_name = f"{algorithm}.py"
    with ZipFile(archive) as zip_file:
        members = [name for name in zip_file.namelist() if Path(name).name == target_name]
        if member_suffix is not None:
            members = [name for name in members if name.endswith(member_suffix)]
        if not members:
            location = target_name if member_suffix is None else member_suffix
            raise FileNotFoundError(f"{location} was not found in {archive}")
        variants: dict[str, tuple[str, bytes]] = {}
        for member in members:
            source_bytes = zip_file.read(member)
            digest = hashlib.sha256(source_bytes).hexdigest()
            variants.setdefault(digest, (member, source_bytes))
    if len(variants) != 1:
        raise ValueError(
            f"{target_name} has {len(variants)} source variants; select a compatibility profile explicitly."
        )

    source_sha256, (member, source_bytes) = next(iter(variants.items()))
    source = source_bytes.decode("utf-8")
    tree = ast.parse(source, filename=member)
    safe_body: list[ast.stmt] = []
    for node in tree.body:
        if isinstance(node, ast.Import):
            roots = {alias.name.split(".", 1)[0] for alias in node.names}
            if not roots.issubset(_ALLOWED_IMPORT_ROOTS):
                raise ValueError(f"Disallowed import in archive member {member}: {sorted(roots)}")
            safe_body.append(node)
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".", 1)[0]
            if root not in _ALLOWED_IMPORT_ROOTS:
                raise ValueError(f"Disallowed import in archive member {member}: {root}")
            safe_body.append(node)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            safe_body.append(node)
        elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            safe_body.append(node)
        else:
            raise ValueError(f"Disallowed top-level statement in archive member {member}: {type(node).__name__}")

    namespace: dict[str, Any] = {}
    safe_module = ast.fix_missing_locations(ast.Module(body=safe_body, type_ignores=[]))
    exec(compile(safe_module, member, "exec"), namespace)
    return namespace, member, source_sha256


def _load_archive_function(
    archive: Path,
    *,
    member_suffix: str,
    function_name: str,
) -> tuple[Callable[..., Any], str, str]:
    """Load one function without executing imports, plotting, or the source main block."""

    with ZipFile(archive) as zip_file:
        members = [name for name in zip_file.namelist() if name.endswith(member_suffix)]
        if len(members) != 1:
            raise ValueError(
                f"expected exactly one archive member ending in {member_suffix!r}, found {len(members)}"
            )
        member = members[0]
        source_bytes = zip_file.read(member)
    source_sha256 = hashlib.sha256(source_bytes).hexdigest()
    tree = ast.parse(source_bytes.decode("utf-8"), filename=member)
    function_nodes = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == function_name
    ]
    if len(function_nodes) != 1:
        raise ValueError(
            f"expected exactly one {function_name!r} function in archive member {member}"
        )
    safe_module = ast.fix_missing_locations(
        ast.Module(body=[function_nodes[0]], type_ignores=[])
    )
    # The pressure-vessel source targets an older NumPy where ``np.math`` was
    # an alias for Python's math module. NumPy 2 removed that alias, so the
    # read-only oracle restores only the old namespace behavior.
    namespace: dict[str, Any] = {"np": _LegacyNumpyProxy()}
    exec(compile(safe_module, member, "exec"), namespace)
    return namespace[function_name], member, source_sha256


def _array_record(value: Any) -> dict[str, Any]:
    array = np.ascontiguousarray(np.asarray(value))
    raw = array.tobytes(order="C")
    record: dict[str, Any] = {
        "shape": list(array.shape),
        "dtype": array.dtype.str,
        "sha256": hashlib.sha256(raw).hexdigest(),
    }
    if array.dtype.kind == "f" and array.size <= 32:
        record["float_hex"] = [float(item).hex() for item in array.reshape(-1)]
    elif array.dtype.kind in "iu" and array.size <= 32:
        record["values"] = [int(item) for item in array.reshape(-1)]
    return record


def _numpy_rng_state_sha256() -> str:
    algorithm, keys, position, has_gauss, cached_gaussian = np.random.get_state()
    digest = hashlib.sha256()
    digest.update(algorithm.encode("ascii"))
    digest.update(np.ascontiguousarray(keys).tobytes())
    digest.update(str(position).encode("ascii"))
    digest.update(str(has_gauss).encode("ascii"))
    digest.update(float(cached_gaussian).hex().encode("ascii"))
    return digest.hexdigest()


def _python_rng_state_sha256() -> str:
    return hashlib.sha256(repr(random.getstate()).encode("ascii")).hexdigest()


def _event(name: str, **values: Any) -> dict[str, Any]:
    return {
        "name": name,
        "values": {key: _array_record(value) for key, value in values.items()},
        "numpy_rng_state_sha256": _numpy_rng_state_sha256(),
        "python_rng_state_sha256": _python_rng_state_sha256(),
    }


def _install_abc_trace(namespace: dict[str, Any], trace: list[dict[str, Any]]) -> None:
    for function_name in _ABC_TRACED_FUNCTIONS:
        original = namespace[function_name]

        def wrapped(*args: Any, _name: str = function_name, _original: Callable[..., Any] = original, **kwargs: Any) -> Any:
            result = _original(*args, **kwargs)
            if isinstance(result, tuple):
                trace.append(_event(_name, **{f"result_{index}": item for index, item in enumerate(result)}))
            else:
                trace.append(_event(_name, result=result))
            return result

        namespace[function_name] = wrapped


def _install_boa_trace(namespace: dict[str, Any], trace: list[dict[str, Any]]) -> None:
    for function_name in _BOA_TRACED_FUNCTIONS:
        original = namespace[function_name]

        def wrapped(*args: Any, _name: str = function_name, _original: Callable[..., Any] = original, **kwargs: Any) -> Any:
            result = _original(*args, **kwargs)
            trace.append(_event(_name, result=result))
            return result

        namespace[function_name] = wrapped


def _install_goa_trace(namespace: dict[str, Any], trace: list[dict[str, Any]]) -> None:
    for function_name in _GOA_TRACED_FUNCTIONS:
        original = namespace[function_name]

        def wrapped(*args: Any, _name: str = function_name, _original: Callable[..., Any] = original, **kwargs: Any) -> Any:
            result = _original(*args, **kwargs)
            if isinstance(result, tuple):
                trace.append(_event(_name, **{f"result_{index}": item for index, item in enumerate(result)}))
            else:
                trace.append(_event(_name, result=result))
            return result

        namespace[function_name] = wrapped


def _install_gsa_trace(namespace: dict[str, Any], trace: list[dict[str, Any]]) -> None:
    """Trace the source helpers without changing their arguments or return values."""

    for function_name in _GSA_TRACED_FUNCTIONS:
        original = namespace[function_name]

        def wrapped(*args: Any, _name: str = function_name, _original: Callable[..., Any] = original, **kwargs: Any) -> Any:
            result = _original(*args, **kwargs)
            if isinstance(result, tuple):
                trace.append(_event(_name, **{f"result_{index}": item for index, item in enumerate(result)}))
            else:
                trace.append(_event(_name, result=result))
            return result

        namespace[function_name] = wrapped


def run_abc_archive_oracle(
    archive: Path,
    *,
    seed: int,
    population_size: int,
    dimension: int,
    max_iterations: int,
    lower_bound: float,
    upper_bound: float,
    objective_id: str = "sphere",
) -> dict[str, Any]:
    """Execute the untouched ABC function definitions with deterministic legacy RNGs."""

    namespace, archive_member, source_sha256 = _load_algorithm_namespace(archive, "ABC")
    trace: list[dict[str, Any]] = []
    _install_abc_trace(namespace, trace)
    objective = get_continuous_objective(objective_id).evaluate
    lower_bounds = np.full(dimension, lower_bound, dtype=np.float64)
    upper_bounds = np.full(dimension, upper_bound, dtype=np.float64)
    np.random.seed(seed)
    random.seed(seed)
    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        best_score, best_position, curve = namespace["ABC"](
            population_size,
            dimension,
            lower_bounds,
            upper_bounds,
            max_iterations,
            objective,
        )
    return {
        "schema": "book-continuous-oracle.v1",
        "algorithm": "ABC",
        "archive_member": archive_member,
        "source_sha256": source_sha256,
        "parameters": {
            "seed": seed,
            "population_size": population_size,
            "dimension": dimension,
            "max_iterations": max_iterations,
            "lower_bound": float(lower_bound).hex(),
            "upper_bound": float(upper_bound).hex(),
            "objective_id": objective_id,
        },
        "trace": trace,
        "result": {
            "best_score": _array_record(best_score),
            "best_position": _array_record(best_position),
            "curve": _array_record(curve),
            "numpy_rng_state_sha256": _numpy_rng_state_sha256(),
            "python_rng_state_sha256": _python_rng_state_sha256(),
        },
        "captured_stdout": stdout.getvalue(),
    }


def run_boa_archive_oracle(
    archive: Path,
    *,
    compatibility_profile: str,
    seed: int,
    population_size: int,
    dimension: int,
    max_iterations: int,
    lower_bound: float,
    upper_bound: float,
    objective_id: str = "sphere",
) -> dict[str, Any]:
    """Execute one explicit BOA source profile with both legacy RNGs seeded."""

    try:
        member_suffix = BOA_PROFILE_MEMBER_SUFFIXES[compatibility_profile]
    except KeyError as exc:
        raise ValueError(f"unknown BOA compatibility profile: {compatibility_profile!r}") from exc
    namespace, archive_member, source_sha256 = _load_algorithm_namespace(
        archive,
        "BOA",
        member_suffix=member_suffix,
    )
    trace: list[dict[str, Any]] = []
    _install_boa_trace(namespace, trace)
    raw_objective = get_continuous_objective(objective_id).evaluate

    def traced_objective(candidate: np.ndarray) -> float:
        value = raw_objective(candidate)
        trace.append(_event("objective", candidate=candidate, result=value))
        return value

    lower_bounds = np.full(dimension, lower_bound, dtype=np.float64)
    upper_bounds = np.full(dimension, upper_bound, dtype=np.float64)
    np.random.seed(seed)
    random.seed(seed)
    stdout = io.StringIO()
    with warnings.catch_warnings():
        # ``np.matrix`` belongs to the archived implementation.  Its modern
        # deprecation warning is unrelated to numerical compatibility.
        warnings.simplefilter("ignore", PendingDeprecationWarning)
        with contextlib.redirect_stdout(stdout):
            best_score, best_position, curve = namespace["BOA"](
                population_size,
                dimension,
                lower_bounds,
                upper_bounds,
                max_iterations,
                traced_objective,
            )
    return {
        "schema": "book-continuous-oracle.v1",
        "algorithm": "BOA",
        "compatibility_profile": compatibility_profile,
        "archive_member": archive_member,
        "source_sha256": source_sha256,
        "parameters": {
            "seed": seed,
            "population_size": population_size,
            "dimension": dimension,
            "max_iterations": max_iterations,
            "lower_bound": float(lower_bound).hex(),
            "upper_bound": float(upper_bound).hex(),
            "objective_id": objective_id,
        },
        "trace": trace,
        "result": {
            "best_score": _array_record(best_score),
            "best_position": _array_record(best_position),
            "curve": _array_record(curve),
            "numpy_rng_state_sha256": _numpy_rng_state_sha256(),
            "python_rng_state_sha256": _python_rng_state_sha256(),
        },
        "captured_stdout": stdout.getvalue(),
    }


def run_goa_archive_oracle(
    archive: Path,
    *,
    compatibility_profile: str,
    seed: int,
    population_size: int,
    dimension: int,
    max_iterations: int,
    lower_bound: float,
    upper_bound: float,
    objective_id: str = "sphere",
) -> dict[str, Any]:
    """Execute the GOA source while tracing its inner social-force helpers."""

    try:
        member_suffix = GOA_PROFILE_MEMBER_SUFFIXES[compatibility_profile]
    except KeyError as exc:
        raise ValueError(f"unknown GOA compatibility profile: {compatibility_profile!r}") from exc
    namespace, archive_member, source_sha256 = _load_algorithm_namespace(
        archive,
        "GOA",
        member_suffix=member_suffix,
    )
    trace: list[dict[str, Any]] = []
    _install_goa_trace(namespace, trace)
    raw_objective = get_continuous_objective(objective_id).evaluate

    def traced_objective(candidate: np.ndarray) -> float:
        value = raw_objective(candidate)
        trace.append(_event("objective", candidate=candidate, result=value))
        return value

    lower_bounds = np.full(dimension, lower_bound, dtype=np.float64)
    upper_bounds = np.full(dimension, upper_bound, dtype=np.float64)
    np.random.seed(seed)
    random.seed(seed)
    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        best_score, best_position, curve = namespace["GOA"](
            population_size,
            dimension,
            lower_bounds,
            upper_bounds,
            max_iterations,
            traced_objective,
        )
    return {
        "schema": "book-continuous-oracle.v1",
        "algorithm": "GOA",
        "compatibility_profile": compatibility_profile,
        "archive_member": archive_member,
        "source_sha256": source_sha256,
        "parameters": {
            "seed": seed,
            "population_size": population_size,
            "dimension": dimension,
            "max_iterations": max_iterations,
            "lower_bound": float(lower_bound).hex(),
            "upper_bound": float(upper_bound).hex(),
            "objective_id": objective_id,
        },
        "trace": trace,
        "result": {
            "best_score": _array_record(best_score),
            "best_position": _array_record(best_position),
            "curve": _array_record(curve),
            "numpy_rng_state_sha256": _numpy_rng_state_sha256(),
            "python_rng_state_sha256": _python_rng_state_sha256(),
        },
        "captured_stdout": stdout.getvalue(),
    }


def run_gsa_archive_oracle(
    archive: Path,
    *,
    compatibility_profile: str,
    seed: int,
    population_size: int,
    dimension: int,
    max_iterations: int,
    lower_bound: float,
    upper_bound: float,
    objective_id: str = "sphere",
) -> dict[str, Any]:
    """Execute the archived Golden Sine Algorithm with a bit-oriented trace."""

    try:
        member_suffix = GSA_PROFILE_MEMBER_SUFFIXES[compatibility_profile]
    except KeyError as exc:
        raise ValueError(f"unknown GSA compatibility profile: {compatibility_profile!r}") from exc
    namespace, archive_member, source_sha256 = _load_algorithm_namespace(
        archive,
        "GSA",
        member_suffix=member_suffix,
    )
    trace: list[dict[str, Any]] = []
    _install_gsa_trace(namespace, trace)
    raw_objective = get_continuous_objective(objective_id).evaluate

    def traced_objective(candidate: np.ndarray) -> float:
        value = raw_objective(candidate)
        trace.append(_event("objective", candidate=candidate, result=value))
        return value

    lower_bounds = np.full(dimension, lower_bound, dtype=np.float64)
    upper_bounds = np.full(dimension, upper_bound, dtype=np.float64)
    np.random.seed(seed)
    random.seed(seed)
    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        best_score, best_position, curve = namespace["GSA"](
            population_size,
            dimension,
            lower_bounds,
            upper_bounds,
            max_iterations,
            traced_objective,
        )
    return {
        "schema": "book-continuous-oracle.v1",
        "algorithm": "GSA",
        "compatibility_profile": compatibility_profile,
        "archive_member": archive_member,
        "source_sha256": source_sha256,
        "parameters": {
            "seed": seed,
            "population_size": population_size,
            "dimension": dimension,
            "max_iterations": max_iterations,
            "lower_bound": float(lower_bound).hex(),
            "upper_bound": float(upper_bound).hex(),
            "objective_id": objective_id,
        },
        "trace": trace,
        "result": {
            "best_score": _array_record(best_score),
            "best_position": _array_record(best_position),
            "curve": _array_record(curve),
            "numpy_rng_state_sha256": _numpy_rng_state_sha256(),
            "python_rng_state_sha256": _python_rng_state_sha256(),
        },
        "captured_stdout": stdout.getvalue(),
    }


def load_abc_engineering_archive_objective(
    archive: Path,
    problem_id: str,
) -> tuple[Callable[[np.ndarray], float], str, str]:
    """Return the untouched engineering ``fun`` body from the matching book example."""

    try:
        case = ABC_ENGINEERING_CASES[problem_id]
    except KeyError as exc:
        raise ValueError(f"unknown ABC engineering problem_id: {problem_id!r}") from exc
    objective, member, source_sha256 = _load_archive_function(
        archive,
        member_suffix=case.main_member_suffix,
        function_name="fun",
    )
    return objective, member, source_sha256


def run_abc_engineering_archive_oracle(
    archive: Path,
    *,
    problem_id: str,
    seed: int,
    max_iterations: int | None = None,
) -> dict[str, Any]:
    """Run one engineering example using its original objective and ABC definitions."""

    try:
        case = ABC_ENGINEERING_CASES[problem_id]
    except KeyError as exc:
        raise ValueError(f"unknown ABC engineering problem_id: {problem_id!r}") from exc
    objective, objective_member, objective_source_sha256 = load_abc_engineering_archive_objective(
        archive,
        problem_id,
    )
    namespace, algorithm_member, algorithm_source_sha256 = _load_algorithm_namespace(archive, "ABC")
    iteration_count = case.max_iterations if max_iterations is None else int(max_iterations)
    if iteration_count <= 0:
        raise ValueError("max_iterations must be > 0")

    lower_bounds = np.asarray(case.lower_bounds, dtype=np.float64)
    upper_bounds = np.asarray(case.upper_bounds, dtype=np.float64)
    np.random.seed(seed)
    random.seed(seed)
    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        best_score, best_position, curve = namespace["ABC"](
            case.population_size,
            case.dimension,
            lower_bounds,
            upper_bounds,
            iteration_count,
            objective,
        )
    return {
        "schema": "book-continuous-engineering-oracle.v1",
        "algorithm": "ABC",
        "problem_id": problem_id,
        "algorithm_member": algorithm_member,
        "algorithm_source_sha256": algorithm_source_sha256,
        "objective_member": objective_member,
        "objective_source_sha256": objective_source_sha256,
        "parameters": {
            "seed": seed,
            "population_size": case.population_size,
            "dimension": case.dimension,
            "max_iterations": iteration_count,
            "lower_bounds": [float(value).hex() for value in lower_bounds],
            "upper_bounds": [float(value).hex() for value in upper_bounds],
        },
        "result": {
            "best_score": _array_record(best_score),
            "best_position": _array_record(best_position),
            "curve": _array_record(curve),
            "numpy_rng_state_sha256": _numpy_rng_state_sha256(),
            "python_rng_state_sha256": _python_rng_state_sha256(),
        },
        "captured_stdout": stdout.getvalue(),
    }


def load_boa_engineering_archive_objective(
    archive: Path,
    problem_id: str,
) -> tuple[Callable[[np.ndarray], float], str, str]:
    """Return the untouched BOA chapter engineering objective."""

    try:
        case = BOA_ENGINEERING_CASES[problem_id]
    except KeyError as exc:
        raise ValueError(f"unknown BOA engineering problem_id: {problem_id!r}") from exc
    objective, member, source_sha256 = _load_archive_function(
        archive,
        member_suffix=case.main_member_suffix,
        function_name="fun",
    )
    return objective, member, source_sha256


def run_boa_engineering_archive_oracle(
    archive: Path,
    *,
    problem_id: str,
    seed: int,
    max_iterations: int | None = None,
) -> dict[str, Any]:
    """Run a complete BOA engineering example with its exact source profile."""

    try:
        case = BOA_ENGINEERING_CASES[problem_id]
    except KeyError as exc:
        raise ValueError(f"unknown BOA engineering problem_id: {problem_id!r}") from exc
    objective, objective_member, objective_source_sha256 = load_boa_engineering_archive_objective(
        archive,
        problem_id,
    )
    algorithm_suffix = BOA_PROFILE_MEMBER_SUFFIXES[case.compatibility_profile]
    namespace, algorithm_member, algorithm_source_sha256 = _load_algorithm_namespace(
        archive,
        "BOA",
        member_suffix=algorithm_suffix,
    )
    iteration_count = case.max_iterations if max_iterations is None else int(max_iterations)
    if iteration_count <= 0:
        raise ValueError("max_iterations must be > 0")

    evaluation_count = 0

    def counted_objective(candidate: np.ndarray) -> float:
        nonlocal evaluation_count
        evaluation_count += 1
        return objective(candidate)

    lower_bounds = np.asarray(case.lower_bounds, dtype=np.float64)
    upper_bounds = np.asarray(case.upper_bounds, dtype=np.float64)
    np.random.seed(seed)
    random.seed(seed)
    stdout = io.StringIO()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", PendingDeprecationWarning)
        with contextlib.redirect_stdout(stdout):
            best_score, best_position, curve = namespace["BOA"](
                case.population_size,
                case.dimension,
                lower_bounds,
                upper_bounds,
                iteration_count,
                counted_objective,
            )
    return {
        "schema": "book-continuous-engineering-oracle.v1",
        "algorithm": "BOA",
        "problem_id": problem_id,
        "compatibility_profile": case.compatibility_profile,
        "algorithm_member": algorithm_member,
        "algorithm_source_sha256": algorithm_source_sha256,
        "objective_member": objective_member,
        "objective_source_sha256": objective_source_sha256,
        "parameters": {
            "seed": seed,
            "population_size": case.population_size,
            "dimension": case.dimension,
            "max_iterations": iteration_count,
            "lower_bounds": [float(value).hex() for value in lower_bounds],
            "upper_bounds": [float(value).hex() for value in upper_bounds],
        },
        "result": {
            "best_score": _array_record(best_score),
            "best_position": _array_record(best_position),
            "curve": _array_record(curve),
            "evaluation_count": evaluation_count,
            "numpy_rng_state_sha256": _numpy_rng_state_sha256(),
            "python_rng_state_sha256": _python_rng_state_sha256(),
        },
        "captured_stdout": stdout.getvalue(),
    }


def load_goa_engineering_archive_objective(
    archive: Path,
    problem_id: str,
) -> tuple[Callable[[np.ndarray], float], str, str]:
    """Return the untouched GOA chapter engineering objective."""

    try:
        case = GOA_ENGINEERING_CASES[problem_id]
    except KeyError as exc:
        raise ValueError(f"unknown GOA engineering problem_id: {problem_id!r}") from exc
    objective, member, source_sha256 = _load_archive_function(
        archive,
        member_suffix=case.main_member_suffix,
        function_name="fun",
    )
    return objective, member, source_sha256


def run_goa_engineering_archive_oracle(
    archive: Path,
    *,
    problem_id: str,
    seed: int,
    max_iterations: int | None = None,
) -> dict[str, Any]:
    """Run a complete GOA engineering example from its own chapter directory."""

    try:
        case = GOA_ENGINEERING_CASES[problem_id]
    except KeyError as exc:
        raise ValueError(f"unknown GOA engineering problem_id: {problem_id!r}") from exc
    objective, objective_member, objective_source_sha256 = load_goa_engineering_archive_objective(
        archive,
        problem_id,
    )
    namespace, algorithm_member, algorithm_source_sha256 = _load_algorithm_namespace(
        archive,
        "GOA",
        member_suffix=case.algorithm_member_suffix,
    )
    iteration_count = case.max_iterations if max_iterations is None else int(max_iterations)
    if iteration_count <= 0:
        raise ValueError("max_iterations must be > 0")

    evaluation_count = 0

    def counted_objective(candidate: np.ndarray) -> float:
        nonlocal evaluation_count
        evaluation_count += 1
        return objective(candidate)

    lower_bounds = np.asarray(case.lower_bounds, dtype=np.float64)
    upper_bounds = np.asarray(case.upper_bounds, dtype=np.float64)
    np.random.seed(seed)
    random.seed(seed)
    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        best_score, best_position, curve = namespace["GOA"](
            case.population_size,
            case.dimension,
            lower_bounds,
            upper_bounds,
            iteration_count,
            counted_objective,
        )
    return {
        "schema": "book-continuous-engineering-oracle.v1",
        "algorithm": "GOA",
        "problem_id": problem_id,
        "compatibility_profile": "book_archive_goa_v1",
        "algorithm_member": algorithm_member,
        "algorithm_source_sha256": algorithm_source_sha256,
        "objective_member": objective_member,
        "objective_source_sha256": objective_source_sha256,
        "parameters": {
            "seed": seed,
            "population_size": case.population_size,
            "dimension": case.dimension,
            "max_iterations": iteration_count,
            "lower_bounds": [float(value).hex() for value in lower_bounds],
            "upper_bounds": [float(value).hex() for value in upper_bounds],
        },
        "result": {
            "best_score": _array_record(best_score),
            "best_position": _array_record(best_position),
            "curve": _array_record(curve),
            "evaluation_count": evaluation_count,
            "numpy_rng_state_sha256": _numpy_rng_state_sha256(),
            "python_rng_state_sha256": _python_rng_state_sha256(),
        },
        "captured_stdout": stdout.getvalue(),
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=12345)
    parser.add_argument("--population-size", type=int, default=8)
    parser.add_argument("--dimension", type=int, default=2)
    parser.add_argument("--max-iterations", type=int, default=3)
    parser.add_argument("--lower-bound", type=float, default=-10.0)
    parser.add_argument("--upper-bound", type=float, default=10.0)
    parser.add_argument("--objective-id", default="sphere")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    payload = run_abc_archive_oracle(
        args.archive,
        seed=args.seed,
        population_size=args.population_size,
        dimension=args.dimension,
        max_iterations=args.max_iterations,
        lower_bound=args.lower_bound,
        upper_bound=args.upper_bound,
        objective_id=args.objective_id,
    )
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
