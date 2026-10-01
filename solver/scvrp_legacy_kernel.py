"""Build and invoke the isolated native SCVRP legacy compatibility kernel."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import platform
import shutil
import subprocess
import tempfile
from typing import Any, Literal

from ..problem.scvrp import SCVRPProblem


PROTOCOL = "SCVRP_LEGACY_RESULT_V1"
_SELF_TEST_OUTPUT = "SCVRP_LEGACY_RUNNER_SELF_TEST_V1"
_COMPILE_FLAGS = ("-std=c++14", "-O2")
_INT32_MAX = 0x7FFF_FFFF
_UINT32_MAX = 0xFFFF_FFFF
_LEGACY_SOURCE_HASHES = {
    "common/dependences.cpp": "ad7fde1a75ad1b51cb1d6b32cf7d562a38bdf88b492e7e98a5ba57dcba3d5194",
    "common/dependences.h": "142de5061173deb217c6c57ee5697c31018baaa479a7a4743f10a0cba274d453",
    "common/io_tools.cpp": "b390cd3df3f0cf6dbab408fa976b415fae5fea01db159fa4d2b539392bd2aae5",
    "common/io_tools.h": "ef650bd8d68514e3baf05d66fe464d80ec60abc5cd3ebb721ffb7ff8d28f083a",
    "common/local_search.cpp": "c4240d1877fdc08d314cec8dcc9557dd1b2f9f561f1a6587fc5e9cb436ede6bb",
    "common/local_search.h": "ec4ece6a59fd136a184cc42056437d3e4201e5289edd2bfb05d4f552fd151952",
    "metaheuristic/differential_evolution.cpp": "7d244e97675779a17a5f2405d6665de6016a65b65cbd2cf059951f63960dbf1a",
    "metaheuristic/differential_evolution.h": "de5853644fa476453248dc5104d364ac64ad0d6a02266533d4d17606a01595f1",
}


class SCVRPLegacyKernelError(RuntimeError):
    """Raised when the compatibility kernel cannot be built or executed."""


@dataclass(frozen=True)
class SCVRPLegacyKernelRequest:
    seed: int
    termination_mode: Literal["fixed_iterations", "legacy_temperature_stagnation"]
    limit: int
    start_temperature: float = 1.0
    cooling_rate: float = 0.95
    iterations_per_temperature: int = 110
    max_transitions: int = 500_000
    trace: bool = False

    def __post_init__(self) -> None:
        _require_request_int(self.seed, name="seed")
        if self.seed <= 0:
            raise ValueError("seed must be > 0 for the legacy compatibility profile")
        if self.seed > _UINT32_MAX:
            raise ValueError("seed must fit in an unsigned 32-bit integer")
        if self.termination_mode not in {
            "fixed_iterations",
            "legacy_temperature_stagnation",
        }:
            raise ValueError("unsupported termination_mode")
        _require_request_int(self.limit, name="limit")
        if self.limit < 0:
            raise ValueError("limit must be >= 0")
        if self.limit > _INT32_MAX:
            raise ValueError("limit must fit in a signed 32-bit integer")
        if (
            isinstance(self.start_temperature, bool)
            or not isinstance(self.start_temperature, (int, float))
            or not math.isfinite(float(self.start_temperature))
            or self.start_temperature <= 0
        ):
            raise ValueError("start_temperature must be > 0")
        if (
            isinstance(self.cooling_rate, bool)
            or not isinstance(self.cooling_rate, (int, float))
            or not math.isfinite(float(self.cooling_rate))
            or not 0 < self.cooling_rate <= 1
        ):
            raise ValueError("cooling_rate must be in (0, 1]")
        _require_request_int(self.iterations_per_temperature, name="iterations_per_temperature")
        if self.iterations_per_temperature <= 0:
            raise ValueError("iterations_per_temperature must be > 0")
        if self.iterations_per_temperature > _INT32_MAX:
            raise ValueError("iterations_per_temperature must fit in a signed 32-bit integer")
        _require_request_int(self.max_transitions, name="max_transitions")
        if self.max_transitions <= 0:
            raise ValueError("max_transitions must be > 0")
        if self.max_transitions >= _INT32_MAX:
            raise ValueError("max_transitions must be < INT32_MAX")
        if not isinstance(self.trace, bool):
            raise ValueError("trace must be a boolean")
        if self.termination_mode == "fixed_iterations" and self.limit > self.max_transitions:
            raise ValueError("fixed iteration limit cannot exceed max_transitions")


def _require_request_int(value: Any, *, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer")


def native_source_root() -> Path:
    return Path(__file__).with_name("native") / "scvrp_legacy"


def verify_legacy_source_hashes(source_root: Path | None = None) -> None:
    root = native_source_root() if source_root is None else Path(source_root)
    for relative, expected in _LEGACY_SOURCE_HASHES.items():
        path = root / relative
        if not path.is_file():
            raise SCVRPLegacyKernelError(f"missing archived SCVRP source: {path}")
        actual = sha256(path.read_bytes()).hexdigest()
        if actual != expected:
            raise SCVRPLegacyKernelError(
                f"archived SCVRP source hash mismatch for {relative}: {actual} != {expected}"
            )


def build_scvrp_legacy_kernel(
    *,
    cache_root: Path | None = None,
    compiler: str = "g++",
) -> Path:
    """Build once into a content-addressed cache and return the executable."""
    source_root = native_source_root()
    verify_legacy_source_hashes(source_root)
    compiler_path = shutil.which(compiler)
    if compiler_path is None:
        raise SCVRPLegacyKernelError(f"C++ compiler was not found: {compiler}")
    compiler_version = _run_checked([compiler_path, "--version"]).stdout
    fingerprint = _kernel_fingerprint(source_root, compiler_version)
    root = (
        Path(tempfile.gettempdir()) / "mkp-scvrp-legacy-kernel"
        if cache_root is None
        else Path(cache_root)
    )
    artifact_dir = root / fingerprint
    executable = artifact_dir / "scvrp_legacy_runner"
    artifact_dir.mkdir(parents=True, exist_ok=True)

    lock_path = artifact_dir / ".build.lock"
    with lock_path.open("a+b") as lock_file:
        try:
            import fcntl
        except ImportError as exc:  # pragma: no cover - the compatibility target is Linux
            raise SCVRPLegacyKernelError("native kernel build requires POSIX file locking") from exc
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        if _passes_self_test(executable):
            return executable

        with tempfile.TemporaryDirectory(prefix="build-", dir=artifact_dir) as temp_dir_text:
            temp_dir = Path(temp_dir_text)
            objects: list[Path] = []
            compat_source = source_root / "compat_rng.cpp"
            compat_object = temp_dir / "compat_rng.o"
            _compile(
                compiler_path,
                compat_source,
                compat_object,
                extra_flags=(),
                source_root=source_root,
            )
            objects.append(compat_object)

            legacy_sources = (
                source_root / "runner.cpp",
                source_root / "common" / "dependences.cpp",
                source_root / "common" / "io_tools.cpp",
                source_root / "common" / "local_search.cpp",
                source_root / "metaheuristic" / "differential_evolution.cpp",
            )
            for index, source in enumerate(legacy_sources):
                object_path = temp_dir / f"legacy_{index}.o"
                _compile(
                    compiler_path,
                    source,
                    object_path,
                    extra_flags=("-include", str(source_root / "compat_rng.h")),
                    source_root=source_root,
                )
                objects.append(object_path)

            candidate = temp_dir / "scvrp_legacy_runner"
            _run_checked(
                [
                    compiler_path,
                    "-O2",
                    *(str(path) for path in objects),
                    "-lm",
                    "-o",
                    str(candidate),
                ]
            )
            if not _passes_self_test(candidate):
                raise SCVRPLegacyKernelError("compiled SCVRP kernel failed its RNG self-test")
            os.replace(candidate, executable)
        return executable


def serialize_scvrp_legacy_request(
    problem: SCVRPProblem,
    request: SCVRPLegacyKernelRequest,
) -> str:
    if not isinstance(problem, SCVRPProblem):
        raise TypeError("SCVRP legacy kernel requires SCVRPProblem")
    best_known = 0 if problem.best_known is None else int(problem.best_known)
    lines = [
        "SCVRP_LEGACY_RUNNER_V1",
        f"customers {problem.n_customers}",
        f"vehicles {problem.vehicle_count}",
        f"capacity {problem.capacity}",
        f"best_known {best_known}",
        f"seed {request.seed}",
        "de_technique 2",
        f"start_temperature {request.start_temperature:.17g}",
        f"cooling_rate {request.cooling_rate:.17g}",
        f"iterations_per_temperature {request.iterations_per_temperature}",
        f"termination {request.termination_mode}",
        f"limit {request.limit}",
        f"max_transitions {request.max_transitions}",
        f"trace {int(request.trace)}",
        "demands " + " ".join(str(int(value)) for value in problem.demands.tolist()),
        "distance_matrix "
        + " ".join(str(int(value)) for value in problem.distance_matrix.reshape(-1).tolist()),
        f"fixed_route_count {len(problem.fixed_routes)}",
    ]
    for route_index, route in enumerate(problem.fixed_routes):
        values = (
            int(problem.fixed_route_capacities[route_index]),
            len(route),
            *route,
        )
        lines.append("fixed_route " + " ".join(str(value) for value in values))
    lines.append("END")
    return "\n".join(lines) + "\n"


def run_scvrp_legacy_kernel(
    problem: SCVRPProblem,
    request: SCVRPLegacyKernelRequest,
    *,
    executable: Path | None = None,
    cache_root: Path | None = None,
    timeout: float = 120.0,
) -> dict[str, Any]:
    binary = build_scvrp_legacy_kernel(cache_root=cache_root) if executable is None else Path(executable)
    payload = serialize_scvrp_legacy_request(problem, request)
    try:
        completed = subprocess.run(
            [str(binary)],
            input=payload,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SCVRPLegacyKernelError(f"SCVRP legacy kernel execution failed: {exc}") from exc
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or "no diagnostic output"
        raise SCVRPLegacyKernelError(
            f"SCVRP legacy kernel exited with {completed.returncode}: {detail}"
        )
    try:
        result = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise SCVRPLegacyKernelError("SCVRP legacy kernel returned invalid JSON") from exc
    if not isinstance(result, dict) or result.get("protocol") != PROTOCOL:
        raise SCVRPLegacyKernelError("SCVRP legacy kernel returned an unsupported protocol")
    return result


def _kernel_fingerprint(source_root: Path, compiler_version: str) -> str:
    digest = sha256()
    digest.update("SCVRP_LEGACY_BUILD_V1\n".encode("ascii"))
    digest.update(platform.platform().encode("utf-8"))
    digest.update(platform.machine().encode("ascii"))
    digest.update(compiler_version.encode("utf-8"))
    digest.update("\0".join(_COMPILE_FLAGS).encode("ascii"))
    for path in sorted(source_root.rglob("*")):
        if path.is_file() and path.suffix in {".cpp", ".h"}:
            digest.update(path.relative_to(source_root).as_posix().encode("utf-8"))
            digest.update(path.read_bytes())
    return digest.hexdigest()


def _compile(
    compiler_path: str,
    source: Path,
    output: Path,
    *,
    extra_flags: tuple[str, ...],
    source_root: Path,
) -> None:
    _run_checked(
        [
            compiler_path,
            *_COMPILE_FLAGS,
            f"-I{source_root}",
            *extra_flags,
            "-c",
            str(source),
            "-o",
            str(output),
        ]
    )


def _passes_self_test(executable: Path) -> bool:
    if not executable.is_file():
        return False
    try:
        completed = subprocess.run(
            [str(executable), "--self-test"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return completed.returncode == 0 and completed.stdout.strip() == _SELF_TEST_OUTPUT


def _run_checked(command: list[str]) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        if isinstance(exc, subprocess.CalledProcessError):
            detail = exc.stderr.strip() or exc.stdout.strip()
        else:
            detail = str(exc)
        raise SCVRPLegacyKernelError(f"native build command failed: {detail}") from exc
