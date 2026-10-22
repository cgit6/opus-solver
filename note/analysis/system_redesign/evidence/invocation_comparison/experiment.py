"""Read-only architecture exploration: temporary native/Python control probes.

Not a production optimizer, output codec, scheduler, or repository change.
All adapters call one synthetic C++ kernel. File I/O is Python-only, after
the entire result is ready. Only summaries/file paths reach the controller.
"""
from __future__ import annotations

import array
import gc
import hashlib
import importlib
import json
import mmap
import multiprocessing as mp
import os
import pickle
from pathlib import Path
import resource
import socket
import statistics
import struct
import subprocess
import sys
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "results"
OUTPUT.mkdir(exist_ok=True)
MODES = ("binding", "ipc_copy", "ipc_shared")
HEADER = struct.Struct("=5Q")
REQUEST = struct.Struct("=3Q")
WORD = struct.Struct("=Q")
MASK = (1 << 64) - 1


def mem(pid):
    try:
        values = {}
        for line in Path(f"/proc/{pid}/smaps_rollup").read_text().splitlines():
            key, _, value = line.partition(":")
            if key in ("Rss", "Pss"):
                values[key.lower() + "_kib"] = int(value.split()[0])
        return values
    except (FileNotFoundError, ProcessLookupError, PermissionError):
        return {"rss_kib": 0, "pss_kib": 0}


class Sampler:
    """Sample sum-PSS, not sum-RSS alone: shared mappings otherwise double count.

    Sampling cannot promise the true maximum; kernel page cache is not process
    PSS and is not included. Parent/control-process baseline is reported apart.
    """
    def __init__(self, pids):
        self.pids = tuple(pids)
        self.peak = {"rss_kib": 0, "pss_kib": 0}
        self.samples = 0
        self.done = threading.Event()
        self.thread = threading.Thread(target=self.loop, daemon=True)

    def sample(self):
        rows = [mem(pid) for pid in self.pids]
        for key in self.peak:
            self.peak[key] = max(self.peak[key], sum(row.get(key, 0) for row in rows))
        self.samples += 1

    def loop(self):
        while not self.done.is_set():
            self.sample()
            self.done.wait(0.005)

    def __enter__(self):
        self.sample()
        self.thread.start()
        return self

    def __exit__(self, *args):
        self.done.set()
        self.thread.join()
        self.sample()


class Payload:
    def __init__(self, owner, view, compute_ns, rng, checksum, native_live=None):
        self.owner, self.view = owner, view
        self.compute_s, self.rng = compute_ns / 1e9, rng
        self.checksum, self.native_live = checksum, native_live

    def close(self):
        self.view.release()
        self.view = None
        owner, self.owner = self.owner, None
        if isinstance(owner, mmap.mmap):
            owner.close()


class Backend:
    def __init__(self, mode, label):
        self.mode, self.native = mode, None
        self.native_live = 0
        if mode == "binding":
            self.module = importlib.import_module("invocation_probe")
            self.native_pid = os.getpid()
        else:
            self.sock, child = socket.socketpair()
            self.log = (OUTPUT / f"{label}_native_stderr.log").open("ab", buffering=0)
            try:
                self.native = subprocess.Popen(
                    [str(ROOT / "native_probe"), str(child.fileno())],
                    pass_fds=(child.fileno(),), stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL, stderr=self.log,
                )
            finally:
                child.close()
            self.native_pid = self.native.pid

    def receive(self, view):
        offset = 0
        while offset < len(view):
            got = self.sock.recv_into(view[offset:])
            if not got:
                # No timeout policy is being implemented: EOF is an observed exit.
                self.native.wait()
                raise RuntimeError(f"native process exited: {self.native.returncode}")
            offset += got

    def read_header(self):
        header = bytearray(HEADER.size)
        self.receive(memoryview(header))
        return HEADER.unpack(header)

    def solve(self, size, seed, action=0):
        if self.mode == "binding":
            result = self.module.run(size, seed, action)
            return Payload(result, memoryview(result), result.compute_ns, result.rng, result.checksum)
        mapping = None
        try:
            if self.mode == "ipc_shared":
                fd = os.memfd_create("invocation-planning-probe", os.MFD_CLOEXEC)
                try:
                    os.ftruncate(fd, size)
                    mapping = mmap.mmap(fd, size)
                    sent = self.sock.sendmsg([REQUEST.pack(size, seed, action)],
                        [(socket.SOL_SOCKET, socket.SCM_RIGHTS, array.array("i", [fd]))])
                    if sent != REQUEST.size:
                        raise RuntimeError("partial planning-probe request")
                finally:
                    os.close(fd)
            else:
                self.sock.sendall(REQUEST.pack(size, seed, action))
            status, nbytes, compute_ns, rng, checksum = self.read_header()
            owner = mapping if mapping is not None else bytearray(nbytes)
            view = memoryview(owner)
            if not status and self.mode == "ipc_copy":
                self.receive(view)
            trailer = bytearray(8)
            self.receive(memoryview(trailer))
            self.native_live = WORD.unpack(trailer)[0]
            if status:
                view.release()
                raise RuntimeError("injected ordinary solver exception (native status=1)")
            if nbytes != size or self.native_live:
                view.release()
                raise RuntimeError("response size / native cleanup mismatch")
            mapping = None # ownership is now held by Payload, not this local cleanup.
            return Payload(owner, view, compute_ns, rng, checksum, self.native_live)
        finally:
            if mapping is not None:
                mapping.close()

    def live(self):
        return self.module.live_bytes() if self.mode == "binding" else self.native_live

    def close(self):
        if self.native is not None:
            if self.native.poll() is None:
                try:
                    self.sock.sendall(REQUEST.pack(0, 0, 9))
                except (BrokenPipeError, ConnectionError):
                    pass
            self.sock.close()
            self.native.wait()
            self.log.close()


def save_python_only(path, payload, sync):
    # One shared Python outputter implementation, all modes. Small memoryview
    # slices are not copies. These are chunks of an already completed result,
    # NOT addAct callbacks, iterative solver responses, or a background writer.
    with open(path, "wb", buffering=0) as fh:
        for start in range(0, len(payload.view), 4 * 1024**2):
            chunk = payload.view[start:start + 4 * 1024**2]
            offset = 0
            while offset < len(chunk):
                wrote = fh.write(chunk[offset:])
                if not wrote:
                    raise RuntimeError("short output write")
                offset += wrote
            chunk.release()
        if sync:
            os.fsync(fh.fileno())


def worker(mode, label, conn):
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    backend = Backend(mode, label)
    # Both paths fully start and execute before announcing readiness. First
    # startup is measured separately and excluded from steady-state trials.
    warm = backend.solve(8, 1)
    warm.close()
    conn.send({"event": "ready", "pid": os.getpid(), "native_pid": backend.native_pid})
    while True:
        command = conn.recv()
        if command["op"] == "close":
            backend.close()
            return
        payload = None
        conn.send({"event": "started", "task": command["task"], "pid": os.getpid()})
        stage = "solve"
        begin = time.perf_counter()
        try:
            payload = backend.solve(command["size"], command["seed"], command.get("action", 0))
            returned = time.perf_counter()
            before_save = {"python": mem(os.getpid()), "native": mem(backend.native_pid)}
            stage = "save"
            save_start = time.perf_counter()
            save_python_only(command["path"], payload, command.get("sync", True))
            saved = time.perf_counter()
            result = {"event": "result", "task": command["task"], "ok": True,
                "mode": mode, "size": command["size"], "seed": command["seed"],
                "path": command["path"], "rng": payload.rng, "checksum": payload.checksum,
                "solve_and_handoff_s": returned-begin, "compute_s": payload.compute_s,
                "boundary_s": returned-begin-payload.compute_s,
                "save_s": saved-save_start, "before_save_mem": before_save}
        except Exception as exc:
            exited = backend.native.poll() if backend.native is not None else None
            result = {"event": "result", "task": command["task"], "ok": False,
                "stage": stage, "error_type": type(exc).__name__, "error": str(exc),
                "path": command["path"], "input": command, "native_exit": exited,
                "traceback": traceback.format_exc()}
            # Python experiment-side error recording, independent of the failed
            # task's chosen target path. Hardware-wide failures aren't covered.
            with (OUTPUT / f"{label}_errors.jsonl").open("a") as fh:
                fh.write(json.dumps(result) + "\n")
            if exited is not None:
                backend.close()
                backend = Backend(mode, label + "_replacement")
        finally:
            if payload is not None:
                payload.close()
                payload = None
        result.update(worker_s=time.perf_counter()-begin, live_bytes=backend.live(),
            pid=os.getpid(), native_pid=backend.native_pid, after_release_mem=mem(os.getpid()))
        conn.send(result)


class Unit:
    def __init__(self, mode, label):
        self.mode, self.label = mode, label
        parent, child = mp.get_context("spawn").Pipe()
        self.conn = parent
        self.process = mp.get_context("spawn").Process(target=worker, args=(mode,label,child))
        begin = time.perf_counter()
        self.process.start()
        child.close()
        self.ready = self.conn.recv()
        assert self.ready["event"] == "ready"
        self.startup_s = time.perf_counter()-begin

    @property
    def pids(self):
        return tuple(set((self.ready["pid"], self.ready["native_pid"])))

    def call(self, task, size, seed=1, action=0, path=None):
        command = dict(op="run", task=task, size=size, seed=seed, action=action,
            path=str(path or OUTPUT / f"{self.label}_{task}.bin"), sync=True)
        # Minimal pre-dispatch input artifact for the fault experiment only.
        (OUTPUT / f"{self.label}_{task}_input.json").write_text(json.dumps(command))
        self.conn.send(command)
        while True:
            try:
                message = self.conn.recv()
            except (EOFError, ConnectionResetError):
                self.process.join()
                return dict(ok=False, task=task, stage="worker_exit", exitcode=self.process.exitcode,
                    input=command, pid=self.process.pid)
            if message["event"] == "result":
                message["summary_message_bytes"] = len(pickle.dumps(message))
                return message

    def close(self):
        if self.process.is_alive():
            self.conn.send({"op": "close"})
        self.process.join()
        self.conn.close()


def file_hash(path):
    with open(path, "rb") as fh:
        return hashlib.file_digest(fh, "sha256").hexdigest()


def reference(size, seed):
    data, state, checksum = bytearray(), seed, 0
    for i in range(size // 8):
        state = (state * 6364136223846793005 + 1442695040888963407) & MASK
        value = state ^ ((i * 0x9e3779b97f4a7c15) & MASK)
        data.extend(WORD.pack(value))
        checksum = (checksum + value) & MASK
    return hashlib.sha256(data).hexdigest(), state, checksum


def correctness():
    report = []
    for mode in MODES:
        unit = Unit(mode, "correct_" + mode)
        try:
            for i, (size, seed) in enumerate(((8,1),(65536,17),(8,1),(131072,99),(65536,17))):
                row = unit.call(f"reference_{i}", size, seed)
                assert row["ok"] and row["live_bytes"] == 0, row
                assert (file_hash(row["path"]), row["rng"], row["checksum"]) == reference(size, seed)
            exception = unit.call("ordinary_exception", 65536, 3, action=1)
            assert not exception["ok"] and exception["stage"] == "solve" and exception["live_bytes"] == 0
            after = unit.call("after_exception", 65536, 17)
            assert after["ok"] and after["pid"] == unit.ready["pid"]
            assert after["native_pid"] == unit.ready["native_pid"]
            assert (file_hash(after["path"]), after["rng"], after["checksum"]) == reference(65536,17)
            save_fail = unit.call("bad_output_path", 65536, 17, path=OUTPUT)
            assert not save_fail["ok"] and save_fail["stage"] == "save"
            assert save_fail["error_type"] == "IsADirectoryError" and save_fail["live_bytes"] == 0
            after_save = unit.call("after_save_failure", 65536, 17)
            assert after_save["ok"] and after_save["pid"] == unit.ready["pid"]
            assert (file_hash(after_save["path"]), after_save["rng"], after_save["checksum"]) == reference(65536,17)
            assert "IsADirectoryError" in (OUTPUT / f"correct_{mode}_errors.jsonl").read_text()
            report.append(dict(mode=mode, checks=9, passed=True, startup_s=unit.startup_s))
        finally:
            unit.close()
        # Hold a previous completed result while performing another solve. A
        # memoryview owns its exporter; native process reuse cannot overwrite it.
        backend = Backend(mode, "lifetime_" + mode)
        first = backend.solve(65536,17)
        digest = hashlib.sha256(first.view).hexdigest()
        second = backend.solve(65536,99)
        assert hashlib.sha256(first.view).hexdigest() == digest
        second.close()
        first.close()
        assert backend.live() == 0
        backend.close()
    return report


def benchmarks():
    units = {mode: Unit(mode, "bench_" + mode) for mode in MODES}
    rows, hashes = [], {}
    try:
        # One discarded warm-up at each size/mode, then five alternating rounds.
        for mib in (4,64,256):
            size = mib * 1024**2
            for mode in MODES:
                assert units[mode].call(f"warm_{mib}",size)["ok"]
            for repeat in range(5):
                order = MODES[repeat % 3:] + MODES[:repeat % 3]
                for mode in order:
                    unit = units[mode]
                    baseline = sum(mem(pid)["pss_kib"] for pid in unit.pids)
                    with Sampler(unit.pids) as sampled:
                        row = unit.call(f"m{mib}_r{repeat}", size)
                    assert row["ok"] and row["live_bytes"] == 0, row
                    digest = file_hash(row["path"])
                    expected = hashes.setdefault(mib, (digest,row["rng"],row["checksum"]))
                    assert expected == (digest,row["rng"],row["checksum"])
                    row.update(repeat=repeat, mib=mib, peak_sampled=sampled.peak,
                        samples=sampled.samples, baseline_pss_kib=baseline, sha256=digest,
                        controller_memory=mem(os.getpid()))
                    rows.append(row)
            print(json.dumps({"stage":"benchmark_size_done", "mib":mib}), flush=True)
    finally:
        for unit in units.values():
            unit.close()
    return rows


def faults():
    report = []
    for mode in MODES:
        units = [Unit(mode,f"fault_{mode}_{i}") for i in range(8)]
        initial = [unit.ready.copy() for unit in units]
        try:
            with ThreadPoolExecutor(max_workers=8) as dispatch:
                futures = [dispatch.submit(unit.call,"overlap",16*1024**2,17,
                    2 if i==3 else 3) for i,unit in enumerate(units)]
                results = [future.result() for future in futures]
            assert len([r for r in results if r["ok"]]) == 7, results
            assert not results[3]["ok"]
            for i, row in enumerate(results):
                assert (OUTPUT / f"fault_{mode}_{i}_overlap_input.json").is_file()
                if i != 3:
                    assert row["pid"] == initial[i]["pid"]
                    assert row["native_pid"] == initial[i]["native_pid"]
                    assert row["live_bytes"] == 0
            hashes = [file_hash(row["path"]) for row in results if row["ok"]]
            assert len(set(hashes)) == 1
            if mode == "binding":
                assert results[3]["exitcode"] == -6
                units[3].close()
                units[3] = Unit(mode,f"fault_{mode}_replacement")
            else:
                assert results[3]["native_exit"] == -6
                assert results[3]["pid"] == initial[3]["pid"]
                assert results[3]["native_pid"] != initial[3]["native_pid"]
            # New tasks, not automatic retries of the failed task.
            with ThreadPoolExecutor(max_workers=8) as dispatch:
                next_results = list(dispatch.map(lambda unit: unit.call("new_task",65536,17),units))
            assert all(row["ok"] and row["live_bytes"]==0 for row in next_results)
            assert all((file_hash(row["path"]),row["rng"],row["checksum"]) == reference(65536,17)
                for row in next_results)
            report.append(dict(mode=mode, concurrent=8, unaffected=7, new_tasks=8,
                failed_result=results[3], passed=True))
            print(json.dumps({"stage":"fault_mode_done","mode":mode}),flush=True)
        finally:
            for unit in units:
                unit.close()
    return report


def concurrent_benchmarks():
    rows, hashes = [], {}
    for repeat in range(3):
        order = MODES[repeat:] + MODES[:repeat]
        for mode in order:
            units = [Unit(mode,f"parallel_{repeat}_{mode}_{i}") for i in range(8)]
            try:
                pids = set(pid for unit in units for pid in unit.pids)
                baseline = sum(mem(pid)["pss_kib"] for pid in pids)
                with Sampler(pids) as sampled:
                    begin = time.perf_counter()
                    with ThreadPoolExecutor(max_workers=8) as dispatch:
                        futures = [dispatch.submit(unit.call,"large",64*1024**2,17)
                            for unit in units]
                        results = [future.result() for future in futures]
                    elapsed = time.perf_counter()-begin
                assert all(row["ok"] and row["live_bytes"]==0 for row in results)
                for row in results:
                    digest = file_hash(row["path"])
                    assert hashes.setdefault(64,digest) == digest
                rows.append(dict(mode=mode,repeat=repeat,workers=8,mib_per_task=64,
                    batch_s=elapsed,peak_sampled=sampled.peak,baseline_pss_kib=baseline,
                    compute_sum_s=sum(row["compute_s"] for row in results),
                    save_sum_s=sum(row["save_s"] for row in results),
                    controller_memory=mem(os.getpid()),
                    max_summary_message_bytes=max(row["summary_message_bytes"] for row in results)))
                print(json.dumps({"stage":"parallel_done","mode":mode,"repeat":repeat}),flush=True)
            finally:
                for unit in units:
                    unit.close()
    return rows


def summary(results):
    report = {"correctness":results.get("correctness"),"faults":results.get("faults")}
    report["single"] = []
    for mib in (4,64,256):
        for mode in MODES:
            rows = [r for r in results.get("benchmarks",[]) if r["mib"]==mib and r["mode"]==mode]
            if rows:
                fields = ("compute_s","boundary_s","save_s","worker_s")
                report["single"].append(dict(mode=mode,mib=mib,repeats=len(rows),
                    **{k:statistics.median(r[k] for r in rows) for k in fields},
                    peak_sampled_pss_mib=max(r["peak_sampled"]["pss_kib"] for r in rows)/1024,
                    median_baseline_pss_mib=statistics.median(r["baseline_pss_kib"] for r in rows)/1024))
    report["parallel"] = []
    for mode in MODES:
        rows = [r for r in results.get("parallel",[]) if r["mode"]==mode]
        if rows:
            report["parallel"].append(dict(mode=mode,median_batch_s=statistics.median(r["batch_s"] for r in rows),
                min_batch_s=min(r["batch_s"] for r in rows),max_batch_s=max(r["batch_s"] for r in rows),
                peak_sampled_pss_mib=max(r["peak_sampled"]["pss_kib"] for r in rows)/1024))
    return report


if __name__ == "__main__":
    stage = sys.argv[1]
    artifact = ROOT / "experiment_results.json"
    results = json.loads(artifact.read_text()) if artifact.exists() else {}
    if stage == "correctness": results[stage] = correctness()
    elif stage == "benchmarks": results[stage] = benchmarks()
    elif stage == "faults": results[stage] = faults()
    elif stage == "parallel": results[stage] = concurrent_benchmarks()
    elif stage != "summary": raise ValueError(stage)
    results["environment"] = dict(python=sys.version,platform=sys.platform,
        cpu_count=os.cpu_count(),root=str(ROOT),pss_sample_interval_s=0.005,
        save_policy="binary, synchronous Python-only writes plus fsync; no compression",
        expected_size_known_before_solve=True,formal_optimizer=False)
    artifact.write_text(json.dumps(results,indent=2))
    print(json.dumps(summary(results),indent=2),flush=True)
