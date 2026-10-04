"""Inventory、匯入並用 CDELS 驗證封存的 SA-lineage SCVRP 題庫。

昂貴的 CDELS／C++ oracle 回放刻意與一般 experiment CLI 分開；沒有明確傳入
execution flag 時，本模組不會啟動 solver。
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import struct
import sys
import tempfile
import time
from typing import Any, Sequence

import numpy as np
from ruamel.yaml import YAML

from ..engine.repository import ProblemRepository
from ..problem import buildProblemRegistry, problemBuilders
from ..problem.scvrp import (
    SCVRPProblem,
    load_legacy_scvrp_problem,
    parse_legacy_cvrp_instance,
)
from ..solver.CDELS import CDELS, CDELSSnapshot
from .scvrp_native_oracle import (
    SCVRPLegacyKernelRequest,
    build_scvrp_legacy_kernel,
    run_scvrp_legacy_kernel,
)


SCHEMA = "optiforge.scvrp-dataset-manifest/v1"
VALIDATION_PLAN_SCHEMA = "optiforge.scvrp-validation-plan/v1"
VALIDATION_ROW_SCHEMA = "optiforge.scvrp-validation-row/v2"
ARCHIVE_SHA256 = "b08c4699186796b39ca4ca081da18f005bf847afda86543573b9d440c9e1fd73"
LINEAGE = "sa"
BASE_INSTANCES = (
    "A-n32-k5",
    "A-n48-k7",
    "A-n64-k9",
    "A-n80-k10",
    "P-n16-k8",
    "P-n19-k2",
    "P-n23-k8",
)
PARAMETER_COMBINATIONS = (
    (2, 1),
    (3, 1),
    (4, 1),
    (4, 2),
    (5, 1),
    (5, 2),
    (6, 1),
    (6, 2),
    (6, 3),
    (7, 1),
    (7, 2),
    (7, 3),
    (8, 1),
    (8, 2),
    (8, 3),
    (8, 4),
)
FIXED_ROUTE_PATTERN = re.compile(
    r"^(?P<base>.+)_RouteCap_(?P<route_cap>\d+)\.txt_"
    r"WithSpareCapacity_MaxTransfer_(?P<max_transfer>\d+)_Gurobi\.txt$"
)
KNOWN_BEST = {"P-n16-k8-routecap2-transfer1": 350}
VALID_STATUS = "valid"
LEGACY_OWNER_ZERO_STATUS = "legacy_compatible_missing_owner_zero"
RUNNABLE_STATUSES = frozenset({VALID_STATUS, LEGACY_OWNER_ZERO_STATUS})


@dataclass(frozen=True)
class DatasetRecord:
    dataset: str
    base_instance: str
    route_cap: int
    max_transfer: int
    problem_id: str
    instance_path: str
    fixed_route_path: str
    instance_size: int
    fixed_route_size: int
    instance_sha256: str
    fixed_route_sha256: str
    status: str
    issues: tuple[str, ...]
    missing_customers: tuple[int, ...]
    legacy_missing_owner: int | None


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _default_source_root() -> Path:
    return _repo_root() / "note/study/scvrp/dataset/legacy_sa/instances"


def _default_manifest_path() -> Path:
    return _repo_root() / "note/study/scvrp/dataset_manifest.json"


def _default_problem_root() -> Path:
    return _repo_root() / "configs/problems"


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _problem_id(base: str, route_cap: int, max_transfer: int) -> str:
    return f"{base}-routecap{route_cap}-transfer{max_transfer}"


def _read_fixed_route_components(
    path: Path,
) -> tuple[list[list[int]], list[int]]:
    lines = [
        line.strip()
        for line in path.read_text(encoding="ascii").splitlines()
        if line.strip()
    ]
    if not lines:
        raise ValueError(f"Fixed-route source is empty: {path}")
    try:
        route_count = int(lines[0])
    except ValueError as exc:
        raise ValueError(f"Invalid fixed-route count: {path}") from exc
    if route_count <= 0 or len(lines) != 1 + route_count * 2:
        raise ValueError(f"Invalid fixed-route structure: {path}")
    routes: list[list[int]] = []
    for line in lines[1 : route_count + 1]:
        values = [int(token) for token in line.split()]
        if len(values) < 2 or values[0] != 0 or values[-1] != 0:
            raise ValueError(f"Invalid fixed-route depot sentinels: {path}")
        routes.append(values[1:-1])
    capacities = [int(line) for line in lines[route_count + 1 :]]
    return routes, capacities


def _inspect_fixed_route(
    path: Path,
    *,
    n_customers: int,
) -> tuple[tuple[str, ...], tuple[int, ...]]:
    lines = [
        line.strip()
        for line in path.read_text(encoding="ascii").splitlines()
        if line.strip()
    ]
    issues: list[str] = []
    if not lines:
        return ("empty_file",), ()
    try:
        route_count = int(lines[0])
    except ValueError:
        return ("invalid_route_count",), ()
    if route_count <= 0:
        issues.append(f"route_count:{route_count}")
        return tuple(issues), ()
    if len(lines) != 1 + route_count * 2:
        issues.append(f"line_count:{len(lines)}!={1 + route_count * 2}")
        return tuple(issues), ()

    customers: list[int] = []
    for route_index, line in enumerate(lines[1 : route_count + 1], start=1):
        try:
            values = [int(token) for token in line.split()]
        except ValueError:
            issues.append(f"route_{route_index}:non_integer")
            continue
        if len(values) < 2 or values[0] != 0 or values[-1] != 0:
            issues.append(f"route_{route_index}:missing_depot_sentinels")
            continue
        customers.extend(values[1:-1])

    expected = set(range(1, n_customers))
    actual = set(customers)
    missing = sorted(expected - actual)
    invalid = sorted(actual - expected)
    duplicates = sorted(
        customer for customer in actual if customers.count(customer) > 1
    )
    if missing:
        issues.append("missing_customers:" + ",".join(map(str, missing)))
    if invalid:
        issues.append("invalid_customers:" + ",".join(map(str, invalid)))
    if duplicates:
        issues.append("duplicate_customers:" + ",".join(map(str, duplicates)))
    for capacity_index, line in enumerate(lines[route_count + 1 :], start=1):
        try:
            capacity = int(line)
        except ValueError:
            issues.append(f"capacity_{capacity_index}:non_integer")
            continue
        if capacity < 0:
            issues.append(f"capacity_{capacity_index}:negative")
    return tuple(issues), tuple(missing)


def inventory(source_root: Path) -> dict[str, Any]:
    root = Path(source_root).resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"SCVRP source root not found: {root}")

    records: list[DatasetRecord] = []
    found_keys: set[tuple[str, int, int]] = set()
    for fixed_path in sorted(root.rglob("*_Gurobi.txt")):
        match = FIXED_ROUTE_PATTERN.fullmatch(fixed_path.name)
        if match is None:
            raise ValueError(f"Unsupported fixed-route filename: {fixed_path}")
        base = match.group("base")
        route_cap = int(match.group("route_cap"))
        max_transfer = int(match.group("max_transfer"))
        dataset = fixed_path.parent.name
        key = (base, route_cap, max_transfer)
        if key in found_keys:
            raise ValueError(f"Duplicate SCVRP source combination: {key}")
        found_keys.add(key)
        instance_path = fixed_path.with_name(f"{base}.vrp")
        if not instance_path.is_file():
            raise FileNotFoundError(
                f"Missing CVRP instance for {fixed_path.name}: {instance_path}"
            )
        instance = parse_legacy_cvrp_instance(instance_path)
        issues, missing_customers = _inspect_fixed_route(
            fixed_path,
            n_customers=instance.n_customers,
        )
        legacy_owner_zero = (
            dataset == "A"
            and route_cap == 8
            and len(missing_customers) == 1
            and issues
            == ("missing_customers:" + ",".join(map(str, missing_customers)),)
        )
        status = (
            VALID_STATUS
            if not issues
            else LEGACY_OWNER_ZERO_STATUS
            if legacy_owner_zero
            else "blocked_invalid_fixed_route"
        )
        records.append(
            DatasetRecord(
                dataset=dataset,
                base_instance=base,
                route_cap=route_cap,
                max_transfer=max_transfer,
                problem_id=_problem_id(base, route_cap, max_transfer),
                instance_path=instance_path.relative_to(root).as_posix(),
                fixed_route_path=fixed_path.relative_to(root).as_posix(),
                instance_size=instance_path.stat().st_size,
                fixed_route_size=fixed_path.stat().st_size,
                instance_sha256=_sha256_file(instance_path),
                fixed_route_sha256=_sha256_file(fixed_path),
                status=status,
                issues=issues,
                missing_customers=missing_customers,
                legacy_missing_owner=0 if legacy_owner_zero else None,
            )
        )

    expected_keys = {
        (base, route_cap, max_transfer)
        for base in BASE_INSTANCES
        for route_cap, max_transfer in PARAMETER_COMBINATIONS
    }
    missing_keys = sorted(expected_keys - found_keys)
    extra_keys = sorted(found_keys - expected_keys)
    if missing_keys or extra_keys:
        raise ValueError(
            "SCVRP source matrix mismatch: "
            f"missing={missing_keys}, extra={extra_keys}"
        )

    valid_count = sum(record.status == VALID_STATUS for record in records)
    legacy_compatible_count = sum(
        record.status == LEGACY_OWNER_ZERO_STATUS for record in records
    )
    runnable_count = valid_count + legacy_compatible_count
    blocked_count = len(records) - runnable_count
    return {
        "schema": SCHEMA,
        "lineage": LINEAGE,
        "archive": {
            "path": "note/study/SCRP.rar",
            "sha256": ARCHIVE_SHA256,
            "status": "truncated_tail_required_members_crc_verified",
        },
        "source_root": "note/study/scvrp/dataset/legacy_sa/instances",
        "expected_base_instances": list(BASE_INSTANCES),
        "expected_parameter_combinations": [
            {"route_cap": route_cap, "max_transfer": max_transfer}
            for route_cap, max_transfer in PARAMETER_COMBINATIONS
        ],
        "summary": {
            "total": len(records),
            "valid": valid_count,
            "legacy_compatible": legacy_compatible_count,
            "runnable": runnable_count,
            "blocked": blocked_count,
        },
        "records": [asdict(record) for record in records],
    }


def _canonical_json_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def _pretty_json_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        dir=path.parent,
    )
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, path)
    except BaseException:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def write_manifest(manifest: dict[str, Any], path: Path) -> None:
    _atomic_write_bytes(path, _pretty_json_bytes(manifest))


def load_manifest(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("schema") != SCHEMA:
        raise ValueError(f"Unsupported SCVRP dataset manifest: {path}")
    return data


def _model_data(
    problem: SCVRPProblem,
    *,
    best_known: int | None,
    record: dict[str, Any],
) -> dict[str, Any]:
    def scalar(value: float) -> int | float:
        return int(value) if float(value).is_integer() else float(value)

    data: dict[str, Any] = {
        "problem_id": problem.problem_id,
        "dataset": problem.dataset,
        "problem_type": "scvrp",
        "n_customers": problem.n_customers,
        "vehicle_count": problem.vehicle_count,
        "capacity": problem.capacity,
        "best_known": best_known,
        "coords": [
            [scalar(float(x)), scalar(float(y))]
            for x, y in problem.coords.tolist()
        ],
        "demands": [int(value) for value in problem.demands.tolist()],
        "fixed_routes": [list(route) for route in problem.fixed_routes],
        "fixed_route_capacities": [
            int(value) for value in problem.fixed_route_capacities.tolist()
        ],
    }
    if record["status"] == LEGACY_OWNER_ZERO_STATUS:
        data["legacy_compatibility"] = {
            "profile": "missing_fixed_route_owner_zero",
            "missing_customers": [
                int(value) for value in record["missing_customers"]
            ],
            "synthetic_fixed_route_owner": int(record["legacy_missing_owner"]),
            "fixed_route_capacities_changed": False,
            "meaning": (
                "emulate the archived C++ heap value; "
                "do not treat as repaired source data"
            ),
        }
    return data


def _dump_yaml(data: dict[str, Any]) -> bytes:
    yaml = YAML()
    yaml.default_flow_style = False
    yaml.indent(mapping=2, sequence=4, offset=2)
    with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as stream:
        yaml.dump(data, stream)
        stream.seek(0)
        return stream.read().encode("utf-8")


def _model_fingerprint(problem: SCVRPProblem) -> tuple[Any, ...]:
    return (
        problem.problem_id,
        problem.dataset,
        problem.n_customers,
        problem.vehicle_count,
        problem.capacity,
        tuple(map(tuple, problem.coords.tolist())),
        tuple(int(value) for value in problem.demands.tolist()),
        problem.fixed_routes,
        tuple(int(value) for value in problem.fixed_route_capacities.tolist()),
    )


def _repository(problem_root: Path) -> ProblemRepository:
    return ProblemRepository(
        problem_root=problem_root,
        registry=buildProblemRegistry(problemBuilders()),
    )


def _load_record_problem(
    *,
    record: dict[str, Any],
    source_root: Path,
    best_known: int | None,
) -> SCVRPProblem:
    problem_id = str(record["problem_id"])
    dataset = str(record["dataset"])
    instance_path = source_root / record["instance_path"]
    fixed_route_path = source_root / record["fixed_route_path"]
    if record["status"] == VALID_STATUS:
        return load_legacy_scvrp_problem(
            instance_path,
            fixed_route_path,
            dataset=dataset,
            problem_id=problem_id,
            best_known=best_known,
        )
    if record["status"] != LEGACY_OWNER_ZERO_STATUS:
        raise ValueError(f"SCVRP source record is not runnable: {problem_id}")

    instance = parse_legacy_cvrp_instance(instance_path)
    routes, capacities = _read_fixed_route_components(fixed_route_path)
    owner = int(record["legacy_missing_owner"])
    if owner != 0 or not 0 <= owner < len(routes):
        raise ValueError(f"Unsupported legacy missing-customer owner for {problem_id}")
    missing_customers = tuple(int(value) for value in record["missing_customers"])
    if not missing_customers:
        raise ValueError(
            f"Legacy compatibility record has no missing customer: {problem_id}"
        )
    routes[owner].extend(missing_customers)
    return SCVRPProblem(
        problem_id=problem_id,
        dataset=dataset,
        best_known=best_known,
        n_customers=instance.n_customers,
        vehicle_count=instance.vehicle_count,
        capacity=instance.capacity,
        coords=instance.coords,
        demands=instance.demands,
        fixed_routes=tuple(tuple(route) for route in routes),
        fixed_route_capacities=np.asarray(capacities, dtype=np.int64),
    )


def import_configs(
    *,
    manifest: dict[str, Any],
    source_root: Path,
    problem_root: Path,
    write: bool,
) -> dict[str, Any]:
    repository = _repository(problem_root)
    created = 0
    identical = 0
    planned = 0
    blocked = 0
    legacy_compatible = 0
    for record in manifest["records"]:
        if record["status"] not in RUNNABLE_STATUSES:
            blocked += 1
            continue
        if record["status"] == LEGACY_OWNER_ZERO_STATUS:
            legacy_compatible += 1
        problem_id = str(record["problem_id"])
        dataset = str(record["dataset"])
        best_known = KNOWN_BEST.get(problem_id)
        raw_problem = _load_record_problem(
            record=record,
            source_root=source_root,
            best_known=best_known,
        )
        destination = problem_root / "scvrp" / dataset / f"{problem_id}.yaml"
        if destination.exists():
            existing = repository.load(dataset, problem_id, "scvrp")
            if not isinstance(existing, SCVRPProblem):
                raise TypeError(f"Unexpected model type for {destination}")
            if _model_fingerprint(existing) != _model_fingerprint(raw_problem):
                raise ValueError(
                    f"Existing SCVRP config differs from archived source: {destination}"
                )
            identical += 1
            continue
        planned += 1
        if write:
            data = _model_data(
                raw_problem,
                best_known=best_known,
                record=record,
            )
            _atomic_write_bytes(destination, _dump_yaml(data))
            created += 1
    return {
        "mode": "write" if write else "dry-run",
        "total": int(manifest["summary"]["total"]),
        "blocked": blocked,
        "legacy_compatible": legacy_compatible,
        "already_identical": identical,
        "planned_new": planned,
        "created": created,
    }


def static_validate(
    *,
    manifest: dict[str, Any],
    source_root: Path,
    problem_root: Path,
) -> dict[str, Any]:
    repository = _repository(problem_root)
    loaded = 0
    missing: list[str] = []
    mismatched: list[str] = []
    blocked = 0
    legacy_compatible = 0
    expected_paths: set[Path] = set()
    for record in manifest["records"]:
        if record["status"] not in RUNNABLE_STATUSES:
            blocked += 1
            continue
        if record["status"] == LEGACY_OWNER_ZERO_STATUS:
            legacy_compatible += 1
        problem_id = str(record["problem_id"])
        dataset = str(record["dataset"])
        destination = problem_root / "scvrp" / dataset / f"{problem_id}.yaml"
        expected_paths.add(destination.resolve())
        if not destination.is_file():
            missing.append(problem_id)
            continue
        canonical = repository.load(dataset, problem_id, "scvrp")
        raw = _load_record_problem(
            record=record,
            source_root=source_root,
            best_known=KNOWN_BEST.get(problem_id),
        )
        if not isinstance(canonical, SCVRPProblem) or (
            _model_fingerprint(canonical) != _model_fingerprint(raw)
        ):
            mismatched.append(problem_id)
            continue
        loaded += 1

    actual_paths = {
        path.resolve()
        for path in (problem_root / "scvrp").glob("*/*.yaml")
    }
    extras = sorted(path.as_posix() for path in actual_paths - expected_paths)
    result = {
        "total_manifest_records": int(manifest["summary"]["total"]),
        "loaded_and_matched": loaded,
        "blocked": blocked,
        "legacy_compatible": legacy_compatible,
        "missing": missing,
        "mismatched": mismatched,
        "extra_configs": extras,
        "ok": not missing and not mismatched and not extras,
    }
    if not result["ok"]:
        raise ValueError(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return result


def _parse_seeds(raw: str) -> tuple[int, ...]:
    try:
        seeds = tuple(int(token.strip()) for token in raw.split(",") if token.strip())
    except ValueError as exc:
        raise ValueError("--seeds must be a comma-separated list of integers") from exc
    if not seeds or any(seed <= 0 or seed > 0xFFFF_FFFF for seed in seeds):
        raise ValueError("--seeds values must be in [1, 4294967295]")
    if len(seeds) != len(set(seeds)):
        raise ValueError("--seeds must not contain duplicates")
    return seeds


def _solver_contract_sha256() -> str:
    root = _repo_root()
    paths = sorted(
        {
            root / "problem/scvrp.py",
            root / "solver/CDELS.py",
            root / "tools/scvrp_native_oracle.py",
            *root.glob("solver/native/scvrp_legacy/**/*.cpp"),
            *root.glob("solver/native/scvrp_legacy/**/*.h"),
        }
    )
    digest = sha256(b"SCVRP_SOLVER_CONTRACT_V1\0")
    for path in paths:
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def build_validation_plan(
    *,
    manifest: dict[str, Any],
    manifest_path: Path,
    problem_root: Path,
    seeds: tuple[int, ...],
    iterations: int,
    selected_problem_ids: tuple[str, ...] = (),
) -> dict[str, Any]:
    if iterations < 0:
        raise ValueError("--iterations must be >= 0")
    selected = set(selected_problem_ids)
    known_ids = {str(record["problem_id"]) for record in manifest["records"]}
    unknown = sorted(selected - known_ids)
    if unknown:
        raise ValueError(f"Unknown --problem values: {unknown}")

    tasks: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    legacy_compatible: list[dict[str, Any]] = []
    for record in manifest["records"]:
        problem_id = str(record["problem_id"])
        if selected and problem_id not in selected:
            continue
        if record["status"] not in RUNNABLE_STATUSES:
            blocked.append(
                {
                    "problem_id": problem_id,
                    "issues": list(record["issues"]),
                }
            )
            continue
        if record["status"] == LEGACY_OWNER_ZERO_STATUS:
            legacy_compatible.append(
                {
                    "problem_id": problem_id,
                    "missing_customers": list(record["missing_customers"]),
                    "synthetic_fixed_route_owner": int(
                        record["legacy_missing_owner"]
                    ),
                }
            )
        config_path = (
            problem_root
            / "scvrp"
            / str(record["dataset"])
            / f"{problem_id}.yaml"
        )
        if not config_path.is_file():
            raise FileNotFoundError(f"Missing SCVRP config: {config_path}")
        config_sha256 = _sha256_file(config_path)
        for seed in seeds:
            tasks.append(
                {
                    "task_key": f"{record['dataset']}:{problem_id}:seed{seed}:iter{iterations}",
                    "dataset": str(record["dataset"]),
                    "problem_id": problem_id,
                    "seed": seed,
                    "iterations": iterations,
                    "config_sha256": config_sha256,
                }
            )
    plan = {
        "schema": VALIDATION_PLAN_SCHEMA,
        "oracle_lineage": LINEAGE,
        "comparison": "cdels_python_vs_archived_sa_cpp_oracle",
        "manifest_sha256": _sha256_file(manifest_path),
        "solver_contract_sha256": _solver_contract_sha256(),
        "termination_mode": "fixed_iterations",
        "iterations_per_temperature": 110,
        "start_temperature_hex": float(1.0).hex(),
        "cooling_rate_hex": float(0.95).hex(),
        "deep_process_trace": True,
        "seeds": list(seeds),
        "iterations": iterations,
        "blocked": blocked,
        "legacy_compatible": legacy_compatible,
        "tasks": tasks,
    }
    plan["plan_sha256"] = sha256(_canonical_json_bytes(plan)).hexdigest()
    return plan


def _snapshot_dict(snapshot: CDELSSnapshot) -> dict[str, Any]:
    return {
        "generation": snapshot.generation,
        "objective": snapshot.objective,
        "feasible_solutions": snapshot.feasible_solutions,
        "feasible": snapshot.feasible,
        "transfer_vehicle_count": snapshot.transfer_vehicle_count,
        "routes": [list(route) for route in snapshot.routes],
        "transferred_customers": list(snapshot.transferred_customers),
    }


def _comparison_fields(python_result: Any, native: dict[str, Any]) -> dict[str, Any]:
    native_process = native.get("process_trace")
    if not isinstance(native_process, dict):
        raise ValueError("native oracle omitted the deep process trace")
    return {
        "termination": (
            python_result.termination,
            native.get("termination"),
        ),
        "stop_cause": (
            python_result.stop_cause,
            native.get("stop_cause"),
        ),
        "generation_count": (
            python_result.generation_count,
            native.get("generation_count"),
        ),
        "transition_count": (
            python_result.transition_count,
            native.get("transition_count"),
        ),
        "temperature_stagnation": (
            python_result.temperature_stagnation,
            native.get("temperature_stagnation"),
        ),
        "final_temperature_ieee754": (
            struct.pack("<d", python_result.final_temperature).hex(),
            struct.pack(
                "<d",
                float.fromhex(str(native.get("final_temperature_hex"))),
            ).hex(),
        ),
        "rng_state": (
            python_result.rng_state,
            native.get("rng_state"),
        ),
        "rng_draw_count": (
            python_result.rng_draw_count,
            native.get("rng_draw_count"),
        ),
        "result": (
            _snapshot_dict(python_result.result),
            native.get("result"),
        ),
        "process_trace_sha256": (
            python_result.process_trace_sha256,
            native_process.get("trace_sha256"),
        ),
        "process_generation_digests": (
            [entry.canonical_digest for entry in python_result.process_trace],
            native_process.get("generation_digests"),
        ),
        "process_rng_checkpoints": (
            [
                {
                    "generation": entry.generation,
                    "rng_state": entry.rng_state,
                    "rng_draw_count": entry.rng_draw_count,
                }
                for entry in python_result.process_trace
            ],
            [
                {
                    "generation": entry["generation"],
                    "rng_state": entry["rng_state"],
                    "rng_draw_count": entry["rng_draw_count"],
                }
                for entry in native_process.get("generations", [])
            ],
        ),
    }


def _load_completed_rows(path: Path) -> set[str]:
    if not path.exists():
        return set()
    completed: set[str] = set()
    with path.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"Malformed validation JSONL at {path}:{line_number}"
                ) from exc
            if row.get("schema") != VALIDATION_ROW_SCHEMA:
                raise ValueError(
                    f"Unsupported validation row at {path}:{line_number}"
                )
            if row.get("status") == "exact_match":
                completed.add(str(row["task_key"]))
    return completed


def _append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(_canonical_json_bytes(row).decode("utf-8"))
        stream.flush()
        os.fsync(stream.fileno())


def _ensure_plan(
    output_dir: Path,
    plan: dict[str, Any],
    *,
    start_task: int = 1,
) -> None:
    plan_name = (
        "plan.json"
        if start_task == 1
        else f"plan.from-task-{start_task}.json"
    )
    plan_path = output_dir / plan_name
    if plan_path.exists():
        existing = json.loads(plan_path.read_text(encoding="utf-8"))
        if existing != plan:
            raise ValueError(
                f"Validation plan mismatch in {plan_path}; use a new output directory"
            )
        return
    output_dir.mkdir(parents=True, exist_ok=True)
    _atomic_write_bytes(plan_path, _canonical_json_bytes(plan))


def execute_validation_plan(
    *,
    plan: dict[str, Any],
    problem_root: Path,
    output_dir: Path,
    max_new_runs: int | None,
    native_timeout: float,
    start_task: int = 1,
) -> dict[str, Any]:
    _ensure_plan(output_dir, plan, start_task=start_task)
    runs_path = output_dir / "runs.jsonl"
    completed = _load_completed_rows(runs_path)
    selected_tasks = plan["tasks"][start_task - 1 :]
    selected_keys = {str(task["task_key"]) for task in selected_tasks}
    pending = [task for task in selected_tasks if task["task_key"] not in completed]
    if max_new_runs is not None:
        pending = pending[:max_new_runs]
    repository = _repository(problem_root)
    native_executable = build_scvrp_legacy_kernel()
    executed = 0
    for task in pending:
        started = time.perf_counter()
        problem = repository.load(task["dataset"], task["problem_id"], "scvrp")
        if not isinstance(problem, SCVRPProblem):
            raise TypeError(f"Unexpected model for {task['problem_id']}")
        request = SCVRPLegacyKernelRequest(
            seed=int(task["seed"]),
            termination_mode="fixed_iterations",
            limit=int(task["iterations"]),
            max_transitions=max(1, int(task["iterations"])),
            trace=False,
            process_trace=True,
        )
        python_result = CDELS(problem, seed=int(task["seed"])).solve(
            termination_mode="fixed_iterations",
            limit=int(task["iterations"]),
            max_transitions=max(1, int(task["iterations"])),
            trace=False,
            process_trace=True,
        )
        native = run_scvrp_legacy_kernel(
            problem,
            request,
            executable=native_executable,
            timeout=native_timeout,
        )
        comparisons = _comparison_fields(python_result, native)
        final_evaluation = problem.evaluate(
            python_result.result.routes,
            python_result.result.transferred_customers,
        )
        mismatches = [
            field for field, (python_value, native_value) in comparisons.items()
            if python_value != native_value
        ]
        if python_result.result.objective != final_evaluation.legacy_search_score:
            mismatches.append("python_evaluator_legacy_search_score")
        if python_result.result.feasible != final_evaluation.legacy_feasible:
            mismatches.append("python_evaluator_legacy_feasibility")
        if (
            python_result.result.transfer_vehicle_count
            != final_evaluation.transfer_vehicle_count
        ):
            mismatches.append("python_evaluator_transfer_vehicle_count")
        mismatches.sort()
        row = {
            "schema": VALIDATION_ROW_SCHEMA,
            "plan_sha256": plan["plan_sha256"],
            "task_key": task["task_key"],
            "dataset": task["dataset"],
            "problem_id": task["problem_id"],
            "seed": task["seed"],
            "iterations": task["iterations"],
            "config_sha256": task["config_sha256"],
            "status": "exact_match" if not mismatches else "mismatch",
            "mismatches": mismatches,
            "objective": python_result.result.objective,
            "raw_objective": final_evaluation.objective,
            "legacy_penalty": final_evaluation.legacy_penalty,
            "legacy_search_score": final_evaluation.legacy_search_score,
            "feasible": python_result.result.feasible,
            "routes": [list(route) for route in python_result.result.routes],
            "transferred_customers": list(
                python_result.result.transferred_customers
            ),
            "rng_state": python_result.rng_state,
            "rng_draw_count": python_result.rng_draw_count,
            "process_trace_sha256": python_result.process_trace_sha256,
            "wall_runtime_seconds": time.perf_counter() - started,
        }
        _append_jsonl(runs_path, row)
        if mismatches:
            raise ValueError(
                f"CDELS/native-oracle mismatch for {task['task_key']}: {mismatches}"
            )
        completed.add(str(task["task_key"]))
        executed += 1
        task_number = plan["tasks"].index(task) + 1
        print(
            f"PASS {task['task_key']} "
            f"({task_number}/{len(plan['tasks'])})",
            flush=True,
        )
    completed_plan_keys = {
        str(task["task_key"])
        for task in plan["tasks"]
        if str(task["task_key"]) in completed
    }
    completed_selected_keys = completed_plan_keys & selected_keys
    summary = {
        "plan_sha256": plan["plan_sha256"],
        "expected": len(plan["tasks"]),
        "start_task": start_task,
        "selected_tasks": len(selected_tasks),
        "completed": len(completed_plan_keys),
        "completed_selected": len(completed_selected_keys),
        "pending": len(selected_tasks) - len(completed_selected_keys),
        "executed_this_invocation": executed,
        "blocked_source_configs": len(plan["blocked"]),
        "legacy_compatible_source_configs": len(plan["legacy_compatible"]),
    }
    _atomic_write_bytes(output_dir / "summary.json", _canonical_json_bytes(summary))
    return summary


def _print_json(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m mkp.tools.scvrp_dataset",
        description="Prepare and validate the archived SA-lineage SCVRP dataset.",
    )
    subparsers = parser.add_subparsers(dest="command")

    inventory_parser = subparsers.add_parser(
        "inventory",
        help="Inspect all 112 source combinations without running a solver.",
    )
    inventory_parser.add_argument("--source-root", type=Path, default=_default_source_root())
    inventory_parser.add_argument("--manifest", type=Path, default=_default_manifest_path())
    inventory_parser.add_argument(
        "--write-manifest",
        action="store_true",
        help="Atomically write the deterministic manifest after inspection.",
    )

    import_parser = subparsers.add_parser(
        "import-configs",
        help="Create canonical YAML configs for structurally valid sources.",
    )
    import_parser.add_argument("--source-root", type=Path, default=_default_source_root())
    import_parser.add_argument("--manifest", type=Path, default=_default_manifest_path())
    import_parser.add_argument("--problem-root", type=Path, default=_default_problem_root())
    import_parser.add_argument(
        "--write",
        action="store_true",
        help="Write new configs; without this flag the command is a dry run.",
    )

    validate_parser = subparsers.add_parser(
        "static-validate",
        help="Compare canonical YAML configs to raw inputs without solving.",
    )
    validate_parser.add_argument("--source-root", type=Path, default=_default_source_root())
    validate_parser.add_argument("--manifest", type=Path, default=_default_manifest_path())
    validate_parser.add_argument("--problem-root", type=Path, default=_default_problem_root())

    run_parser = subparsers.add_parser(
        "validate-run",
        help="Plan or execute resumable exact CDELS/native-oracle comparisons.",
    )
    run_parser.add_argument("--manifest", type=Path, default=_default_manifest_path())
    run_parser.add_argument("--problem-root", type=Path, default=_default_problem_root())
    run_parser.add_argument("--seeds", default="1")
    run_parser.add_argument("--iterations", type=int, default=111)
    run_parser.add_argument(
        "--problem",
        action="append",
        default=[],
        help="Limit to one problem_id; repeat for more than one.",
    )
    run_parser.add_argument(
        "--output",
        type=Path,
        default=_repo_root() / "output/scvrp-validation",
    )
    run_parser.add_argument(
        "--execute-expensive",
        action="store_true",
        help="Actually run solvers; without this flag only print the plan.",
    )
    run_parser.add_argument(
        "--skip-blocked",
        action="store_true",
        help="Acknowledge and skip any source configs that remain non-runnable.",
    )
    run_parser.add_argument(
        "--max-new-runs",
        type=int,
        help="Execute at most this many pending tasks, then stop cleanly.",
    )
    run_parser.add_argument(
        "--start-task",
        type=int,
        default=1,
        help="Start from this 1-based task number in the deterministic plan.",
    )
    run_parser.add_argument("--native-timeout", type=float, default=900.0)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0
    try:
        if args.command == "inventory":
            result = inventory(args.source_root)
            if args.write_manifest:
                write_manifest(result, args.manifest)
            _print_json(result["summary"])
            return 0
        if args.command == "import-configs":
            result = import_configs(
                manifest=load_manifest(args.manifest),
                source_root=args.source_root,
                problem_root=args.problem_root,
                write=bool(args.write),
            )
            _print_json(result)
            return 0
        if args.command == "static-validate":
            result = static_validate(
                manifest=load_manifest(args.manifest),
                source_root=args.source_root,
                problem_root=args.problem_root,
            )
            _print_json(result)
            return 0
        if args.command == "validate-run":
            if args.max_new_runs is not None and args.max_new_runs <= 0:
                raise ValueError("--max-new-runs must be > 0")
            if args.start_task <= 0:
                raise ValueError("--start-task must be > 0")
            if args.native_timeout <= 0:
                raise ValueError("--native-timeout must be > 0")
            manifest = load_manifest(args.manifest)
            plan = build_validation_plan(
                manifest=manifest,
                manifest_path=args.manifest,
                problem_root=args.problem_root,
                seeds=_parse_seeds(args.seeds),
                iterations=args.iterations,
                selected_problem_ids=tuple(args.problem),
            )
            if args.start_task > len(plan["tasks"]):
                raise ValueError(
                    f"--start-task must be <= {len(plan['tasks'])}"
                )
            preview = {
                "plan_sha256": plan["plan_sha256"],
                "tasks": len(plan["tasks"]),
                "start_task": args.start_task,
                "selected_tasks": len(plan["tasks"]) - args.start_task + 1,
                "blocked_source_configs": len(plan["blocked"]),
                "legacy_compatible_source_configs": len(
                    plan["legacy_compatible"]
                ),
                "seeds": plan["seeds"],
                "iterations": plan["iterations"],
                "will_execute": bool(args.execute_expensive),
            }
            _print_json(preview)
            if not args.execute_expensive:
                return 0
            if plan["blocked"] and not args.skip_blocked:
                raise ValueError(
                    "source inventory contains blocked configs; inspect the plan and "
                    "pass --skip-blocked to run only structurally valid configs"
                )
            result = execute_validation_plan(
                plan=plan,
                problem_root=args.problem_root,
                output_dir=args.output,
                max_new_runs=args.max_new_runs,
                native_timeout=float(args.native_timeout),
                start_task=int(args.start_task),
            )
            _print_json(result)
            return 0
    except (FileNotFoundError, TypeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    parser.error(f"unsupported command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
