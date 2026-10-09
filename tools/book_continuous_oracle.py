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
import random
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


def _load_algorithm_namespace(archive: Path, algorithm: str) -> tuple[dict[str, Any], str, str]:
    target_name = f"{algorithm}.py"
    with ZipFile(archive) as zip_file:
        members = [name for name in zip_file.namelist() if Path(name).name == target_name]
        if not members:
            raise FileNotFoundError(f"{target_name} was not found in {archive}")
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
