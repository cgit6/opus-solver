"""Deterministic negative control: no C++ data race, no algorithm edits."""
import ctypes
import json
from pathlib import Path
import subprocess

root = Path(__file__).resolve().parent
source = Path("/home/sean/optiforge-optimization-solver/solver/native/scvrp_legacy/compat_rng.cpp")
library = root / "original_compat_rng.so"
subprocess.run(["g++", "-std=c++17", "-O2", "-shared", "-fPIC", str(source), "-o", str(library)], check=True)
native = ctypes.CDLL(str(library))
native.scvrp_msvc_srand.argtypes = [ctypes.c_uint]
native.scvrp_msvc_srand.restype = None
native.scvrp_msvc_rand.argtypes = []
native.scvrp_msvc_rand.restype = ctypes.c_int
native.scvrp_msvc_srand(1)
expected_a = [native.scvrp_msvc_rand(), native.scvrp_msvc_rand()]
native.scvrp_msvc_srand(2)
expected_b = [native.scvrp_msvc_rand(), native.scvrp_msvc_rand()]
native.scvrp_msvc_srand(1)
a_first = native.scvrp_msvc_rand()
native.scvrp_msvc_srand(2)
b_first = native.scvrp_msvc_rand()
a_second = native.scvrp_msvc_rand()
assert a_first == expected_a[0] and b_first == expected_b[0]
assert a_second != expected_a[1]
report = {"passed": True, "negative_control_detected": True,
    "baseline_task_A_seed1": expected_a, "baseline_task_B_seed2": expected_b,
    "interleaved_task_A": [a_first, a_second],
    "finding": "Per-task seeding alone does not isolate the original process-global RNG",
    "not_a_current_solver_bug": "Original oracle uses fresh processes; this tests an invalid shared-task wiring",
    "limits": "Sequential interleaving only, no undefined C++ concurrent access and no algorithm modification"}
(root / "legacy_rng_interleave_results.json").write_text(json.dumps(report, indent=2) + "\n")
print(json.dumps(report))
