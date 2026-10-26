"""Controlled topology x saver measurements. No project imports or JIT."""
from concurrent.futures import ThreadPoolExecutor
import gc
import hashlib
import json
import multiprocessing as mp
from multiprocessing.connection import wait
import os
from pathlib import Path
import random
import statistics
import threading
import time

from perf_reference import canonical, reference

ROOT = Path(__file__).resolve().parent
WORKLOADS = {"short": (256, 4), "compute_heavy": (8192, 256), "history_heavy": (65536, 2)}
SEEDS = tuple(range(1, 9))
CPUS = tuple(sorted(os.sched_getaffinity(0))[:4])


def memory(pids):
    totals = {"pss_kib": 0, "rss_kib": 0, "private_kib": 0}
    for pid in pids:
        try:
            lines = Path(f"/proc/{pid}/smaps_rollup").read_text().splitlines()
        except FileNotFoundError:
            continue
        wanted = {"Rss", "Pss", "Private_Clean", "Private_Dirty"}
        fields = {line.split(":", 1)[0]: int(line.split()[1]) for line in lines
                  if line.split(":", 1)[0] in wanted}
        totals["pss_kib"] += fields.get("Pss", 0)
        totals["rss_kib"] += fields.get("Rss", 0)
        totals["private_kib"] += fields.get("Private_Clean", 0) + fields.get("Private_Dirty", 0)
    return totals


class Sampler:
    def __init__(self, pids):
        self.pids, self.samples, self.done = pids, [], threading.Event()
        self.thread = threading.Thread(target=self.run, daemon=True)
    def run(self):
        while not self.done.is_set():
            self.samples.append({"time_ns": time.monotonic_ns(), **memory(self.pids)})
            self.done.wait(0.005)
    def __enter__(self):
        self.thread.start()
        return self
    def __exit__(self, *_):
        self.done.set()
        self.thread.join()


def save_python(result, path):
    begin = time.perf_counter()
    payload = canonical(result.to_dict())
    serialized = time.perf_counter()
    with Path(path).open("xb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    end = time.perf_counter()
    return {"serialize_s": serialized - begin, "write_s": end - serialized, "bytes": len(payload)}


def lane_loop(index, connection, bank):
    import perf_kernel as native
    connection.send({"kind": "ready", "lane": index, "pid": os.getpid(), "bank": bank.diagnostics()})
    while True:
        command = connection.recv()
        if command["op"] == "stop":
            connection.send({"kind": "stopped", "lane": index, "pid": os.getpid(), "bank": bank.diagnostics()})
            return
        begin = time.perf_counter()
        result = bank.run(command["seed"], command["records"], command["work"])
        compute_s = result.compute_ns / 1e9
        if command.get("hold"):
            connection.send({"kind": "result_ready", "lane": index, "bank": bank.diagnostics()})
            assert connection.recv()["op"] == "save"
        if command["saver"] == "python":
            saved = save_python(result, command["path"])
        else:
            times = native.save_native(result, command["path"])
            saved = {"serialize_s": times.serialize_ns / 1e9, "write_s": times.write_ns / 1e9, "bytes": times.bytes}
        del result
        connection.send({"kind": "saved", "lane": index, "seed": command["seed"],
                         "pid": os.getpid(), "path": command["path"], "compute_s": compute_s,
                         "task_s": time.perf_counter() - begin, **saved, "bank": bank.diagnostics()})


def thread_host(connections, points):
    os.sched_setaffinity(0, CPUS)
    import perf_kernel as native
    before = memory([os.getpid()])
    start = time.perf_counter()
    bank = native.Bank(points)
    preparation = time.perf_counter() - start
    connections[0].send({"kind": "prepared", "pid": os.getpid(), "before_bank": before,
                         "preparation_s": preparation, "after_bank": memory([os.getpid()])})
    with ThreadPoolExecutor(max_workers=len(connections)) as pool:
        futures = [pool.submit(lane_loop, i, c, bank) for i, c in enumerate(connections)]
        for future in futures:
            future.result()


def process_host(lane, connection, points):
    os.sched_setaffinity(0, CPUS)
    import perf_kernel as native
    before = memory([os.getpid()])
    start = time.perf_counter()
    bank = native.Bank(points)
    connection.send({"kind": "prepared", "pid": os.getpid(), "before_bank": before,
                     "preparation_s": time.perf_counter() - start, "after_bank": memory([os.getpid()])})
    lane_loop(lane, connection, bank)


class Runner:
    def __init__(self, mode, workers, points):
        self.mode, self.workers, self.points = mode, workers, points
        self.context, self.processes, self.connections = mp.get_context("spawn"), [], []
        children = []
        self.prepared, self.ready = [], {}
        begin = time.perf_counter()
        for _ in range(workers):
            parent, child = self.context.Pipe()
            self.connections.append(parent)
            children.append(child)
        if mode == "threads":
            p = self.context.Process(target=thread_host, args=(children, points))
            p.start()
            self.processes.append(p)
        else:
            for i, child in enumerate(children):
                p = self.context.Process(target=process_host, args=(i, child, points))
                p.start()
                self.processes.append(p)
        for child in children:
            child.close()
        while len(self.ready) < workers:
            for connection in self.wait():
                entry = connection.recv()
                if entry["kind"] == "prepared":
                    self.prepared.append(entry)
                else:
                    assert entry["kind"] == "ready"
                    self.ready[entry["lane"]] = entry
        self.setup_s = time.perf_counter() - begin
        self.pids = [os.getpid()] + [p.pid for p in self.processes]
        self.after_ready_memory = memory(self.pids)

    def wait(self):
        ready = wait(self.connections + [p.sentinel for p in self.processes], timeout=45)
        if not ready:
            raise TimeoutError("test harness wait limit, not a solver time limit")
        for p in self.processes:
            if p.sentinel in ready:
                raise AssertionError(f"benchmark child unexpectedly exited {p.pid}")
        return [c for c in self.connections if c in ready]

    def batch(self, workload, saver, directory, hold=False, seeds=SEEDS):
        directory.mkdir(parents=True, exist_ok=False)
        records, work = WORKLOADS[workload]
        commands = [{"op": "run", "seed": seed, "records": records, "work": work,
                     "saver": saver, "path": str(directory / f"seed{seed}.json"), "hold": hold}
                    for seed in seeds]
        next_task, completed, held = 0, [], set()
        begin = time.perf_counter()
        for lane in range(min(self.workers, len(commands))):
            self.connections[lane].send(commands[next_task])
            next_task += 1
        retained_memory = None
        while len(completed) < len(commands):
            for connection in self.wait():
                row = connection.recv()
                lane = row["lane"]
                if row["kind"] == "result_ready":
                    held.add(lane)
                    if len(held) == self.workers:
                        retained_memory = memory(self.pids)
                        for item in held:
                            self.connections[item].send({"op": "save"})
                    continue
                assert row["kind"] == "saved"
                completed.append(row)
                if next_task < len(commands):
                    connection.send(commands[next_task])
                    next_task += 1
        end = time.perf_counter()
        return {"mode": self.mode, "workers": self.workers, "points": self.points,
                "workload": workload, "saver": saver, "batch_s": end - begin,
                "records_per_task": records, "work_per_record": work,
                "load_average": list(os.getloadavg()), "retained_result_memory": retained_memory,
                "tasks": completed}

    def close(self):
        for c in self.connections:
            c.send({"op": "stop"})
        pending = set(range(self.workers))
        while pending:
            ready = wait([self.connections[i] for i in pending], timeout=15)
            if not ready:
                raise TimeoutError("benchmark shutdown watchdog")
            for i in list(pending):
                if self.connections[i] in ready:
                    row = self.connections[i].recv()
                    assert row["kind"] == "stopped" and row["bank"]["live_history_bytes"] == 0
                    pending.remove(i)
        for p in self.processes:
            p.join(timeout=15)
            assert not p.is_alive() and p.exitcode == 0
        for c in self.connections:
            c.close()

    def abort(self):
        for p in self.processes:
            if p.is_alive():
                p.kill()
        for p in self.processes:
            p.join(timeout=2)


def check_batch(batch, expected):
    for task in batch["tasks"]:
        data = Path(task["path"]).read_bytes()
        key = (batch["points"], task["seed"], batch["records_per_task"], batch["work_per_record"])
        assert hashlib.sha256(data).hexdigest() == expected[key]


def main():
    output = ROOT / "performance-measured"
    output.mkdir(exist_ok=False)
    reference_path = ROOT / "perf_reference_hashes.json"
    source_hash = hashlib.sha256((ROOT / "perf_reference.py").read_bytes()).hexdigest()
    if reference_path.exists():
        cached = json.loads(reference_path.read_bytes())
        assert cached["source_sha256"] == source_hash
        expected = {tuple(row["input"]): row["sha256"] for row in cached["rows"]}
    else:
        expected = {}
        for points in (64, 2000):
            for seed in SEEDS:
                for name, (records, work) in WORKLOADS.items():
                    expected[(points, seed, records, work)] = hashlib.sha256(canonical(reference(points, seed, records, work))).hexdigest()
            print(json.dumps({"stage": "independent_reference_ready", "points": points}), flush=True)
        reference_path.write_text(json.dumps({"source_sha256": source_hash,
            "rows": [{"input": list(key), "sha256": value} for key, value in expected.items()]}, indent=2) + "\n")
    trials, startup, memories = [], [], []
    def persist():
        (ROOT / "benchmark_results.json").write_text(json.dumps({"passed_so_far": True, "cpus": CPUS,
            "timing_trials": trials, "startup": startup, "memory_trials": memories,
            "reference_input_count": len(expected), "note": "Synthetic; timing and memory are separate runs"}, indent=2) + "\n")
    for points in (64, 2000):
        for workers in (1, 4):
            runners = {mode: Runner(mode, workers, points) for mode in ("threads", "processes")}
            try:
                for mode, runner in runners.items():
                    startup.append({"mode": mode, "workers": workers, "points": points,
                                    "setup_s": runner.setup_s, "prepared": runner.prepared})
                for workload in WORKLOADS:
                    configurations = [(mode, saver) for mode in runners for saver in ("python", "cpp")]
                    for mode, saver in configurations:
                        row = runners[mode].batch(workload, saver, output / f"warm-n{points}-p{workers}-{workload}-{mode}-{saver}")
                        check_batch(row, expected)
                    for repeat in range(5):
                        order = configurations.copy()
                        random.Random(20261024 + repeat).shuffle(order)
                        for mode, saver in order:
                            row = runners[mode].batch(workload, saver,
                                output / f"trial-n{points}-p{workers}-{workload}-r{repeat}-{mode}-{saver}")
                            # Content verification is explicitly outside timing.
                            check_batch(row, expected)
                            row["repeat"] = repeat
                            trials.append(row)
                        persist()
                    print(json.dumps({"stage": "timing_done", "points": points, "workers": workers,
                                      "workload": workload, "trials_so_far": len(trials)}), flush=True)
            finally:
                for runner in runners.values():
                    runner.close()
    # Memory runs have only ONE candidate alive, unlike timing interleaving.
    for points in (64, 2000):
        for mode in ("threads", "processes"):
            for saver in ("python", "cpp"):
                runner = Runner(mode, 4, points)
                try:
                    ready_memory = memory(runner.pids)
                    with Sampler(runner.pids) as sampler:
                        row = runner.batch("history_heavy", saver,
                            output / f"memory-n{points}-{mode}-{saver}", hold=True, seeds=SEEDS[:4])
                    check_batch(row, expected)
                    row["after_ready_memory"] = ready_memory
                    row["peak_sampled_pss_kib"] = max(x["pss_kib"] for x in sampler.samples)
                    row["sample_count"] = len(sampler.samples)
                    row["samples"] = sampler.samples
                    row["prepared"] = runner.prepared
                    memories.append(row)
                    persist()
                finally:
                    runner.close()
    persist()
    print(json.dumps({"passed": True, "timing_trials": len(trials), "memory_trials": len(memories),
                      "all_complete_files_match_independent_reference": True}), flush=True)


if __name__ == "__main__":
    main()
