# Architecture comparison laboratory

Date: 2026-10-24. Read [REPORT.md](REPORT.md) for the discussion summary. This directory is a temporary experimental artifact, not production code or an accepted architecture.

## Scope and previous evidence

The latest request authorized continuing small verified experiments automatically until evidence was sufficient for discussion. It did not authorize selecting unresolved policies or changing production code, dependencies, registries, configuration, or earlier evidence.

- Gate 1 remains at `/tmp/solver-architecture-gate1-vOJPeS`: exact MKP control-algorithm states, private RNG, overlap, immutable problem data and retained result ownership.
- Gate 2 remains at `/tmp/solver-architecture-gate2-wE6cmX`: 72 fault scenarios, preserved dispatched input, algorithm-error global stop, ordinary output errors, notification ordering and no automatic reconciliation/retry.
- This directory adds performance comparisons, unresolved cleanup alternatives, partial delivery, selected real CDELS replay and additional feasibility/negative probes. Neither earlier evidence tree was modified.

Injected crashes are intentional test outcomes. The managers survive and collect facts; unconfirmed delivery is not converted into success by reading result files.

## Environment and implementations

Python 3.12.3; g++ 13.3.0; pybind11 3.1.0 headers in local `pydeps/`; Linux/WSL2 x86-64. Exact compiler invocation is in [perf_environment.json](perf_environment.json). No project package was installed or changed.

`perf_kernel.cpp` uses typed immutable native problem data, private task RNG/scratch/result, releases the GIL during computation and native serialization/writing, and tracks live history ownership. `benchmark.py` compares:

- One spawned execution host with a Python ThreadPoolExecutor calling the C++ core; native computation overlaps, and threads share one native Bank.
- Independent spawned execution hosts, each with its own Bank; no shared-memory input transport in this comparison.
- Python conversion/JSON output versus an independent C++ output function. Both create identical canonical JSON bytes, use exclusive file creation, flush/fsync/close and return only small status/path records to the manager. The algorithm itself does not write files.

This is NOT a C++ task scheduler implementation. No conclusion about the benefit of replacing Python scheduling with a C++ queue is justified.

## Measurement design

Problem matrices: 64 or 2,000 points, uint64 elements, `n*n*8` bytes. Elements are deterministically filled and accessed. Each task owns 8 KiB scratch and its full vector of history values. The synthetic LCG is a private uint64 affine recurrence; it is not the original CDELS RNG.

| Workload | Records per task | Inner steps per record |
| --- | ---: | ---: |
| short | 256 | 4 |
| compute_heavy | 8,192 | 256 |
| history_heavy | 65,536 | 2 |

Two matrix sizes × two unit counts (1/4) × three workloads × two process topologies × two savers = 48 groups. One warmup and five timed batches per group; eight tasks, seeds 1–8, per batch. Configuration order is deterministically shuffled between repetitions. CPU affinity restricts execution hosts to the first four available logical CPUs; recorded CPU IDs are in `benchmark_results.json`.

Batch timing includes dispatch, native compute, conversion/serialization, synchronous fsync save and small final messages. It excludes reference computation, process startup/preparation, compilation and post-run full-file checking. Host preparation is separately recorded, with only one startup observation per topology/size/unit configuration. There is no JIT.

Both candidate topologies remain alive but idle when the other is being timed. Memory measurement is separate and has only one candidate alive at a time. Memory runs use four tasks and intentionally hold all four native results before saving; this barrier is absent in timed batches.

Memory is controller-plus-owned-execution-process PSS, sampled through `/proc/*/smaps_rollup` every approximately 5 ms, plus explicit checkpoints. There are only 10–16 samples per memory case and one run per configuration. A sampled maximum is not an exact peak. The small Python runtime is not the full current application. Per-task CDELS population growth and arbitrarily large histories are not modeled.

Timing distributions overlap, fsync varies, and the small sample does not support a universal speed ranking. Sum of task phase times is not elapsed batch time.

The first benchmark invocation failed during startup memory parsing, before timed trials: the parser treated the smaps header as a numeric field. It was corrected to parse named memory fields only, checked independently, and rerun into `performance-measured/`. The unused `performance-output/` directory is retained. No timing samples from the failed invocation are included.

## Correctness checks and limitations

`perf_reference.py` independently produces canonical full output; its source SHA binds the cached reference fingerprints. `audit_and_analyze.py` checks all 2,336 saved benchmark files (1,920 measured + 384 warmup + 32 memory), their complete bytes, metadata and checksums. Final RNG is additionally checked using independent affine exponentiation, not the native work loop. Descriptive statistics and source hashes are in [combined_audit.json](combined_audit.json).

The full history in this performance kernel is a vector of uint64 samples, not a full CDELS population snapshot. Full MKP encoding/fitness/feasibility/best-state comparison is supplied by gate 1 and the supplementary fault kernel, not by pretending these uint64 samples are actual solver states.

### Additional failure cases

`extra_checks.py` has 24 cases per invocation, run twice. It extends isolated copies of the prior controller/workers, not the original gate 2 files.

- A complete saved file followed by a truncated IPC frame leaves delivery unconfirmed.
- A truncated result file followed by exit remains partial and unconfirmed.
- A real serialization TypeError followed by a truncated error notification cannot be recovered from that notification alone.
- An alternative worker-first error artifact retains that actual TypeError/traceback even when notification is truncated; manager still does not read files or backfill completion.
- Cleanup failure is a raised software cleanup-hook exception plus a deliberately retained native-result strong owner, verified by weak reference. It is not arbitrary heap corruption.
- Both immediate affected-host retirement and draining known-healthy peers before retirement were tested. These are competing proposals, not selected policy. A replacement handles a new input; failed tasks are not automatically retried.

Partial IPC tests close the writer after the partial frame. They do not establish bounded reads for a writer that remains alive after sending an incomplete frame, malformed arbitrary frames, a formal IPC schema, or a production supervisor. Harness watchdogs prevent the experiment from hanging; they are not a proposed per-task timeout.

### Real CDELS and negative control

`real_cdels_check.py` uses existing project Python CDELS and the original C++ oracle on P-n16-k8 (route capacity 2, transfer 1), seeds 1/2 and update limits 0/3/111, plus two repeated short inputs. All twelve existing comparison fields match on eight runs, including trace digest, generation digests, result, temperature bits and RNG checkpoints. This is six unique inputs, not the whole 112-configuration library. The oracle still launches a fresh process per request. Generation count includes initialization; this does not redefine the formal update-count policy.

`legacy_rng_interleave.py` compiles the unchanged original `compat_rng.cpp` into an isolated library and demonstrates deterministic cross-task interference by sequential interleaving. There is no undefined concurrent C++ data race in this test. It exposes invalid shared-task wiring, not a defect in the currently process-isolated oracle. Existing NP and generation-id globals also require redesign before a threaded CDELS port.

### Prefork and page protection

`prefork_check.py` prepares one native bank in a clean, single-threaded Linux laboratory supervisor, forks four children, checks five complete outputs and proves replacement after planned normal retirement can inherit the already prepared bank. Matrix-mapping PSS across supervisor plus four children is 31,250 KiB in this run. It is not a timing comparison, not continuation after an algorithm failure, not a solution for production manager isolation, and not proof that fork is safe after NumPy/ML/threaded native libraries have initialized.

`readonly_check.py` compiles `readonly_probe.cpp`: a standalone page-aligned mmap arena is filled and changed to read-only. Read/write/read cases return 0/SIGSEGV/0, with normal reads summing to 2016. This is feasibility only, not production Bank layout or complete read-only ownership acceptance.

For runtime constraints, see the official [pybind11 GIL documentation](https://pybind11.readthedocs.io/en/stable/advanced/misc.html#global-interpreter-lock-gil), [Python process termination documentation](https://docs.python.org/3.12/library/multiprocessing.html#multiprocessing.Process.terminate), [Linux fork semantics](https://man7.org/linux/man-pages/man2/fork.2.html) and [Python 3.12 fork warnings](https://docs.python.org/3.12/library/os.html#os.fork). These explain constraints; empirical outcomes come from this directory's artifacts.

## Files

- `perf_kernel.cpp`, `build_perf.py`, `perf_smoke.py`, `perf_reference.py`, `benchmark.py`: controlled performance comparison.
- `perf_reference_hashes.json`, `perf_smoke_results.json`, `benchmark_results.json`, `performance-measured/`: corresponding raw evidence.
- `kernel.cpp`, `build.py`, `reference.py`, `fault_workers.py`, `controller.py`, `extra_checks.py`: controlled fault probes.
- `extra-first/`, `extra-repeat/`: complete independent case records, preserved task inputs and result/error artifacts.
- `real_cdels_check.py`, `real_cdels_results.json`, `real-cpp-build/`: selected regression using existing project functions.
- `legacy_rng_interleave.py`, `legacy_rng_interleave_results.json`: original-RNG negative control.
- `prefork_check.py`, `prefork_results.json`, `prefork-output/`: clean Linux typed-bank sharing feasibility.
- `readonly_probe.cpp`, `readonly_check.py`, `readonly_results.json`: standalone protection feasibility.
- `audit_and_analyze.py`, `combined_audit.json`: independent artifact audit and all descriptive statistics.

## Reproduction without overwriting evidence

Run the following only when another full experiment is wanted. The commands copy sources/temporary headers into a NEW temporary directory, rebuild there and generate a separate set of evidence. They do not install dependencies or modify project source. They require the current project's editable Python environment, installed compiler/Python headers, Linux `/proc`, and enough free space for more than 1.2 GiB of output. Fault probes intentionally terminate only their owned children; native core dumps are disabled in those probes.

```bash
PROBE_ORIGINAL=/tmp/solver-architecture-comparison-F5nHlQ
PROBE_PYTHON=/home/sean/optiforge-optimization-solver/.venv/bin/python
PROBE_FRESH=$(mktemp -d /tmp/solver-architecture-repeat-XXXXXX)
cp "$PROBE_ORIGINAL/"*.py "$PROBE_ORIGINAL/"*.cpp "$PROBE_FRESH/"
cp -a "$PROBE_ORIGINAL/pydeps" "$PROBE_FRESH/pydeps"
cd "$PROBE_FRESH"
"$PROBE_PYTHON" build.py
"$PROBE_PYTHON" build_perf.py
"$PROBE_PYTHON" perf_smoke.py
"$PROBE_PYTHON" benchmark.py
"$PROBE_PYTHON" extra_checks.py --label first
"$PROBE_PYTHON" extra_checks.py --label repeat
"$PROBE_PYTHON" real_cdels_check.py
"$PROBE_PYTHON" legacy_rng_interleave.py
"$PROBE_PYTHON" prefork_check.py
"$PROBE_PYTHON" readonly_check.py
"$PROBE_PYTHON" audit_and_analyze.py
```

To recheck this run's existing artifacts without running solvers again:

```bash
cd /tmp/solver-architecture-comparison-F5nHlQ
/home/sean/optiforge-optimization-solver/.venv/bin/python audit_and_analyze.py
```

No result path in the reproduction commands points to an existing project output tree. Sources contain some absolute project imports for the real CDELS checks; relocating the project requires updating those references in the fresh copy. Temp files may be cleaned by the environment; this is not a durable archival location.
