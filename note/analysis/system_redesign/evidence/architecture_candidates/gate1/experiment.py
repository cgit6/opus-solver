"""Gate 1: correctness, typed-bank sharing and ownership, NOT benchmarking.

All solver calls run in child processes. Threads mode has ONE child containing
a Bank shared by all lanes. Processes mode has one Bank in each child. The
controller receives phases, diagnostics, paths and summaries, never histories.
The independent test observer reads files only AFTER confirmed normal saves.
"""
from concurrent.futures import ThreadPoolExecutor
import gc
import hashlib
import json
import multiprocessing as mp
from multiprocessing.connection import wait
import os
from pathlib import Path
import random
import socket
import sys
import traceback

from reference import FIXTURES, assert_equal, canonical, make_bank, reference

ROOT = Path(__file__).resolve().parent
# A safety bound for a broken TEST harness; not a production task timeout.
HARNESS_WAIT_SECONDS = 30


def digest(data):
    return hashlib.sha256(data).hexdigest()


def save_python(result, path):
    """Same synchronous saver for both candidates, after full native return."""
    payload = canonical(result.to_dict())
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("xb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    return {"path": str(target), "bytes": len(payload), "sha256": digest(payload)}


def bank_digest(bank):
    return digest(canonical(bank.export_problems()))


def lane_loop(lane, connection, gate, bank):
    """A lane cannot accept a new task until its synchronous save has ended."""
    held = {}  # Keep one native Result of EACH iteration setting alive on purpose.
    lifetime_checks = 0
    expected_bank_digest = digest(canonical(FIXTURES))

    def check_held():
        nonlocal lifetime_checks
        for native_owner, original_bytes in held.values():
            # Re-read the OLD C++ Result; do not merely compare old Python copies.
            if canonical(native_owner.to_dict()) != original_bytes:
                raise AssertionError("retained native result changed after another task")
            lifetime_checks += 1

    connection.send({"kind": "ready", "lane": lane, "pid": os.getpid(),
                     "bank_digest": bank_digest(bank), "bank": bank.diagnostics()})
    while True:
        command = connection.recv()
        op = command["op"]
        if op == "run":
            task = command["task"]
            task_id = task["task_id"]
            connection.send({"kind": "received", "lane": lane, "task_id": task_id})
            check_held()
            result = bank.solve(task["problem_id"], task["seed"], task["iterations"], gate.fileno())
            connection.send({"kind": "cpp_returned", "lane": lane, "task_id": task_id})
            check_held()
            if bank_digest(bank) != expected_bank_digest:
                raise AssertionError("native problem contents changed")
            native_data = result.to_dict()
            output = save_python(result, task["path"])
            expected_bytes = canonical(native_data)
            if task["iterations"] not in held:
                held[task["iterations"]] = (result, expected_bytes)
            summary = {"kind": "saved", "lane": lane, "task_id": task_id,
                       "pid": os.getpid(), **output,
                       "snapshot_count": len(native_data["history"]),
                       "best_raw_fitness": native_data["best_raw_fitness"],
                       "best_feasible": native_data["best_feasible"],
                       "telemetry": result.measurements(), "bank": bank.diagnostics(),
                       "lifetime_checks_so_far": lifetime_checks,
                       "bank_contents_unchanged": True}
            # Result memory remains held only by the intentional lifecycle test.
            # Never hand a result/history object to the management process.
            del native_data, expected_bytes, result
            connection.send(summary)
        elif op == "release":
            check_held()
            held.clear()
            gc.collect()
            connection.send({"kind": "released", "lane": lane, "pid": os.getpid(),
                             "bank": bank.diagnostics(), "bank_digest": bank_digest(bank),
                             "lifetime_checks": lifetime_checks})
        elif op == "stop":
            if held or bank.diagnostics()["live_results"]:
                raise AssertionError("native results still retained at test shutdown")
            connection.send({"kind": "stopped", "lane": lane, "pid": os.getpid(),
                             "bank": bank.diagnostics(), "bank_digest": bank_digest(bank)})
            connection.close()
            gate.close()
            return
        else:
            raise AssertionError(f"unknown test command: {op}")


def execute_lane(lane, connection, gate, bank):
    try:
        lane_loop(lane, connection, gate, bank)
    except BaseException:
        # Unexpected TEST failures are surfaced, not classified as production
        # recovery or used to exercise the next gate's fault policies.
        connection.send({"kind": "test_error", "lane": lane, "pid": os.getpid(),
                         "traceback": traceback.format_exc()})
        raise


def thread_host(connections, gates):
    import gate1_kernel as native
    bank = make_bank(native)
    with ThreadPoolExecutor(max_workers=len(connections)) as executor:
        futures = [executor.submit(execute_lane, lane, connection, gates[lane], bank)
                   for lane, connection in enumerate(connections)]
        for future in futures:
            future.result()


def process_host(lane, connection, gate):
    import gate1_kernel as native
    bank = make_bank(native)
    execute_lane(lane, connection, gate, bank)


class Candidate:
    def __init__(self, mode, workers, output):
        self.mode, self.workers, self.output = mode, workers, Path(output)
        self.context = mp.get_context("spawn")
        self.connections, children, self.gates, child_gates = [], [], [], []
        self.processes = []
        self.events = []
        self.phase_proofs = []
        self.outputs = []
        self.current_tasks = {}
        self.output.mkdir(parents=True, exist_ok=False)
        self.ledger = (self.output / "input_ledger.jsonl").open("xb")
        for _ in range(workers):
            parent, child = self.context.Pipe(duplex=True)
            gate_parent, gate_child = socket.socketpair()
            self.connections.append(parent)
            children.append(child)
            self.gates.append(gate_parent)
            child_gates.append(gate_child)
        if mode == "threads":
            process = self.context.Process(target=thread_host, args=(children, child_gates))
            process.start()
            self.processes.append(process)
        elif mode == "processes":
            for lane in range(workers):
                process = self.context.Process(target=process_host,
                    args=(lane, children[lane], child_gates[lane]))
                process.start()
                self.processes.append(process)
        else:
            raise AssertionError("unknown candidate")
        for handle in children + child_gates:
            handle.close()
        try:
            self.ready = self.collect("ready")
            expected_pids = 1 if mode == "threads" else workers
            assert len({m["pid"] for m in self.ready}) == expected_pids
            assert all(m["pid"] != os.getpid() for m in self.ready)
            expected_digest = digest(canonical(FIXTURES))
            assert all(m["bank_digest"] == expected_digest for m in self.ready)
            assert all(m["bank"]["prepared_problems"] == 2 for m in self.ready)
            if mode == "threads":
                assert len({m["bank"]["bank_address"] for m in self.ready}) == 1
        except BaseException:
            self.abort_test()
            raise

    def collect(self, final_kind, iterations=None):
        done, messages = set(), []
        waiting = {}
        expected_phases = [] if iterations is None else ([0, 1, 2] if iterations > 1 else [0, 2])
        phase_index = 0
        stages = {lane: [] for lane in range(self.workers)}
        while len(done) < self.workers:
            active_connections = [c for lane, c in enumerate(self.connections) if lane not in done]
            watches = active_connections + [p.sentinel for p in self.processes]
            if iterations is not None:
                watches += self.gates
            ready = wait(watches, timeout=HARNESS_WAIT_SECONDS)
            if not ready:
                raise TimeoutError("prototype safety watchdog: missing test event")
            # Read already-delivered normal notifications before examining exit.
            for lane, connection in enumerate(self.connections):
                if lane in done or connection not in ready:
                    continue
                message = connection.recv()
                if message.get("lane") != lane:
                    raise AssertionError("wrong lane notification")
                if message["kind"] == "test_error":
                    raise AssertionError(message["traceback"])
                if iterations is not None and message.get("task_id") != self.current_tasks[lane]["task_id"]:
                    raise AssertionError("wrong task notification")
                stages[lane].append(message["kind"])
                self.events.append({"sequence": len(self.events), **message})
                if message["kind"] == final_kind:
                    if final_kind == "saved" and stages[lane] != ["received", "cpp_returned", "saved"]:
                        raise AssertionError("incorrect task phase order")
                    done.add(lane)
                    messages.append(message)
            if iterations is not None:
                for lane, gate in enumerate(self.gates):
                    if gate not in ready:
                        continue
                    token = gate.recv(1)
                    if len(token) != 1 or phase_index >= len(expected_phases):
                        raise AssertionError("unexpected native checkpoint")
                    phase = token[0]
                    if phase != expected_phases[phase_index] or lane in waiting:
                        raise AssertionError("incorrect native checkpoint phase")
                    waiting[lane] = phase
                if len(waiting) == self.workers:
                    phase = expected_phases[phase_index]
                    self.phase_proofs.append({"phase": phase,
                        "participants": [self.current_tasks[lane]["task_id"] for lane in sorted(waiting)]})
                    for lane in waiting:
                        self.gates[lane].sendall(bytes([phase + 16]))
                    waiting.clear()
                    phase_index += 1
            for process in self.processes:
                if process.sentinel in ready:
                    finished = (final_kind == "stopped" and
                        all(lane in done for lane, entry in enumerate(self.ready)
                            if entry["pid"] == process.pid))
                    if not finished:
                        raise AssertionError(f"test child exited unexpectedly: pid={process.pid}")
        if iterations is not None and phase_index != len(expected_phases):
            raise AssertionError("tasks finished without all native checkpoint evidence")
        return sorted(messages, key=lambda m: m["lane"])

    def run_wave(self, tasks, batch_id):
        assert len(tasks) == self.workers
        self.current_tasks = {}
        for lane, base in enumerate(tasks):
            task = dict(base)
            task["path"] = str(self.output / batch_id / (task["task_id"] + ".json"))
            # Actual values are retained before dispatch, not just mutable paths.
            fixture = next(p for p in FIXTURES if p["problem_id"] == task["problem_id"])
            self.ledger.write(canonical({"batch_id": batch_id, "lane": lane, "task": task,
                "actual_problem": fixture, "algorithm_parameters": {"control": "flip-one-bit"},
                "seed": task["seed"], "iterations": task["iterations"]}))
            self.ledger.flush()
            os.fsync(self.ledger.fileno())
            self.current_tasks[lane] = task
        for lane, task in self.current_tasks.items():
            self.connections[lane].send({"op": "run", "task": task})
        messages = self.collect("saved", tasks[0]["iterations"])
        if tasks[0]["iterations"]:
            # Every task passed its update midpoint before any task could finish.
            # These are overlapping instrumented update intervals, NOT CPU speed.
            assert max(m["telemetry"]["compute_start_ns"] for m in messages) < min(
                m["telemetry"]["compute_finish_ns"] for m in messages)
        if self.mode == "threads":
            assert all(m["bank"]["peak_active"] == self.workers for m in messages)
            assert len({m["telemetry"]["native_tid"] for m in messages}) == self.workers
        else:
            assert len({m["pid"] for m in messages}) == self.workers
        for message in messages:
            lane = message["lane"]
            task = self.current_tasks[lane]
            # Independent TEST observer reads a confirmed saved file. This is
            # not a production manager re-evaluating results or salvaging files.
            saved = Path(message["path"]).read_bytes()
            expected = reference(task["problem_id"], task["seed"], task["iterations"])
            assert_equal(json.loads(saved), expected)
            assert saved == canonical(expected)
            assert digest(saved) == message["sha256"]
            assert len(saved) == message["bytes"]
            assert message["snapshot_count"] == len(expected["history"])
            assert message["telemetry"]["bank_address"] == self.ready[lane]["bank"]["bank_address"]
            assert message["telemetry"]["problem_address"] == self.ready[lane]["bank"]["problem_addresses"][task["problem_id"]]
            self.outputs.append({"batch_id": batch_id, "task": task, "summary": message})

    def finish(self):
        for connection in self.connections:
            connection.send({"op": "release"})
        released = self.collect("released")
        assert min(m["bank"]["live_results"] for m in released) == 0
        assert all(m["bank"]["active"] == 0 for m in released)
        assert all(m["lifetime_checks"] > 0 for m in released)
        expected_digest = digest(canonical(FIXTURES))
        assert all(m["bank_digest"] == expected_digest for m in released)
        for connection in self.connections:
            connection.send({"op": "stop"})
        stopped = self.collect("stopped")
        for process in self.processes:
            process.join(timeout=HARNESS_WAIT_SECONDS)
            assert not process.is_alive() and process.exitcode == 0
        assert all(m["bank"]["live_results"] == 0 for m in stopped)
        assert all(m["bank_digest"] == expected_digest for m in stopped)
        expected_runs = len(self.outputs) if self.mode == "threads" else len(self.outputs) // self.workers
        for message in stopped:
            assert message["bank"]["runs"] == expected_runs
        unique_banks = {(m["pid"], m["bank"]["bank_address"]) for m in self.ready}
        result = {"mode": self.mode, "workers": self.workers, "passed": True,
                  "task_count": len(self.outputs),
                  "snapshots_compared": sum(m["summary"]["snapshot_count"] for m in self.outputs),
                  "native_bank_count": len(unique_banks),
                  "native_problem_object_count": 2 * len(unique_banks),
                  "native_checkpoint_phases": len(self.phase_proofs),
                  "retained_result_rechecks": sum(m["lifetime_checks"] for m in released),
                  "ready": self.ready, "released": released, "stopped": stopped,
                  "overlap_evidence": self.phase_proofs,
                  "events": self.events, "outputs": self.outputs}
        self.close_handles()
        return result

    def close_handles(self):
        self.ledger.close()
        for handle in self.connections + self.gates:
            handle.close()

    def abort_test(self):
        # Harness failure cleanup only; not a production supervision mechanism.
        for process in self.processes:
            if process.is_alive():
                process.terminate()
        for process in self.processes:
            process.join(timeout=5)
            if process.is_alive():
                process.kill()
                process.join(timeout=5)
        self.close_handles()


def tasks_for(iterations):
    return [{"task_id": f"{p['problem_id']}-seed{seed}-i{iterations}",
             "problem_id": p["problem_id"], "seed": seed, "iterations": iterations}
            for p in FIXTURES for seed in (1, 2, 3, 4)]


def run_case(mode, workers, suite):
    candidate = Candidate(mode, workers, suite / f"{mode}-{workers}")
    try:
        for order in ("forward", "reverse", "permuted"):
            for iterations in (0, 32):
                tasks = tasks_for(iterations)
                if order == "reverse":
                    tasks.reverse()
                elif order == "permuted":
                    # Scheduling RNG is local to the test controller, unrelated
                    # to native per-task RNG state or seed generation policies.
                    random.Random(20261024).shuffle(tasks)
                for start in range(0, len(tasks), workers):
                    candidate.run_wave(tasks[start:start + workers], f"{order}-i{iterations}")
        return candidate.finish()
    except BaseException:
        candidate.abort_test()
        raise


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, nargs="+", choices=(1, 2, 4), default=[1, 2, 4])
    parser.add_argument("--mode", nargs="+", choices=("threads", "processes"), default=["threads", "processes"])
    parser.add_argument("--label", default="full")
    args = parser.parse_args()
    suite = ROOT / ("output-" + args.label)
    suite.mkdir(exist_ok=False)
    cases = []
    for workers in args.workers:
        for mode in args.mode:
            case = run_case(mode, workers, suite)
            cases.append(case)
            print(json.dumps({k: case[k] for k in ("mode", "workers", "passed", "task_count",
                                                  "snapshots_compared", "retained_result_rechecks")}), flush=True)
    hashes = {}
    for case in cases:
        for entry in case["outputs"]:
            key = entry["task"]["task_id"]
            hashes.setdefault(key, set()).add(entry["summary"]["sha256"])
    assert len(hashes) == 16 and all(len(value) == 1 for value in hashes.values())
    result = {"passed": True, "controller_pid": os.getpid(), "case_count": len(cases),
              "tasks_compared": sum(c["task_count"] for c in cases),
              "snapshots_compared": sum(c["snapshots_compared"] for c in cases),
              "unique_inputs": len(hashes), "semantic_hashes_identical": True,
              "performance_claim": None, "formal_architecture_selected": False,
              "fixtures": FIXTURES, "environment": json.loads((ROOT / "environment.json").read_text()),
              "limits": ["Synthetic control algorithm, not CDELS or algorithm quality evidence",
                         "Checkpoint rendezvous proves overlapping instrumented task intervals, not speedup",
                         "Only const/native-content integrity tested, not OS readonly protection",
                         "No fault injection, delivery-loss, save-failure or formal IPC acceptance",
                         "Test observer reads confirmed files; management IPC contains no histories",
                         "Prototype safety watchdog is not a production task timeout",
                         "No shared memory is used for problem transport in either candidate",
                         "Snapshots use exact integers; cross-platform floating point is untested"],
              "cases": cases}
    (suite / "results.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({k: v for k, v in result.items() if k not in ("cases", "environment", "fixtures", "limits")}))


if __name__ == "__main__":
    main()
