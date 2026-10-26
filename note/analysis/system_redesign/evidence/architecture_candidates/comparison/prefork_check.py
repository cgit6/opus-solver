"""Linux-only typed-bank CoW feasibility, isolated from the project runtime.

This lab supervisor is intentionally single-threaded before every fork. It is
NOT permission to switch the existing Python/NumPy application to fork.
"""
import hashlib
import json
import multiprocessing as mp
from multiprocessing.connection import wait
import os
from pathlib import Path
import time

import perf_kernel as native
from perf_reference import canonical, reference

ROOT = Path(__file__).resolve().parent
BANK = None


def mapping_memory(pid, pointer):
    selected, result = False, {}
    for line in Path(f"/proc/{pid}/smaps").read_text().splitlines():
        first = line.split()[0]
        if "-" in first:
            low, high = [int(x, 16) for x in first.split("-")]
            if selected:
                break
            selected = low <= pointer < high
        elif selected and line.split(":", 1)[0] in ("Pss", "Rss", "Shared_Clean", "Shared_Dirty", "Private_Clean", "Private_Dirty"):
            result[line.split(":", 1)[0]] = int(line.split()[1])
    assert result
    return result


def child(connection, cpus):
    os.sched_setaffinity(0, cpus)
    connection.send({"kind": "ready", "pid": os.getpid(), "bank": BANK.diagnostics()})
    while True:
        task = connection.recv()
        if task["op"] == "stop":
            connection.send({"kind": "stopped", "bank": BANK.diagnostics()})
            return
        result = BANK.run(task["seed"], 65536, 2)
        connection.send({"kind": "result_ready", "pid": os.getpid(), "bank": BANK.diagnostics()})
        assert connection.recv()["op"] == "save"
        native.save_native(result, task["path"])
        del result
        connection.send({"kind": "saved", "pid": os.getpid(), "path": task["path"], "bank": BANK.diagnostics()})


def main():
    global BANK
    root = ROOT / "prefork-output"
    root.mkdir(exist_ok=False)
    cpus = tuple(sorted(os.sched_getaffinity(0))[:4])
    assert len(list(Path("/proc/self/task").iterdir())) == 1
    BANK = native.Bank(2000)
    address = BANK.diagnostics()["matrix_address"]
    context, processes, connections = mp.get_context("fork"), [], []
    def start_child():
        assert len(list(Path("/proc/self/task").iterdir())) == 1
        parent, copied = context.Pipe()
        p = context.Process(target=child, args=(copied, cpus))
        p.start()
        copied.close()
        assert wait([parent], timeout=15)
        ready = parent.recv()
        assert ready["kind"] == "ready" and ready["bank"]["matrix_address"] == address
        return p, parent
    try:
        for _ in range(4):
            p, connection = start_child()
            processes.append(p)
            connections.append(connection)
        for seed, connection in enumerate(connections, 1):
            connection.send({"op": "run", "seed": seed, "path": str(root / f"seed{seed}.json")})
        for connection in connections:
            assert wait([connection], timeout=15)
            assert connection.recv()["kind"] == "result_ready"
        mappings = {str(pid): mapping_memory(pid, address) for pid in [os.getpid()] + [p.pid for p in processes]}
        # Each process sees the mapping, but proportional physical ownership
        # across supervisor + children is near ONE matrix, not five matrices.
        sum_pss = sum(d["Pss"] for d in mappings.values())
        assert 29000 < sum_pss < 36000
        for connection in connections:
            connection.send({"op": "save"})
        for seed, connection in enumerate(connections, 1):
            assert connection.recv()["kind"] == "saved"
            assert (root / f"seed{seed}.json").read_bytes() == canonical(reference(2000, seed, 65536, 2))
        # Planned worker retirement, NOT an algorithm-error continuation policy.
        old_pid = processes[0].pid
        connections[0].send({"op": "stop"})
        assert connections[0].recv()["kind"] == "stopped"
        processes[0].join(timeout=5)
        assert processes[0].exitcode == 0
        connections[0].close()
        p, connection = start_child()
        processes[0], connections[0] = p, connection
        assert p.pid != old_pid
        connection.send({"op": "run", "seed": 5, "path": str(root / "seed5.json")})
        assert connection.recv()["kind"] == "result_ready"
        connection.send({"op": "save"})
        assert connection.recv()["kind"] == "saved"
        assert (root / "seed5.json").read_bytes() == canonical(reference(2000, 5, 65536, 2))
        assert BANK.diagnostics()["live_history_bytes"] == 0
        for connection in connections:
            connection.send({"op": "stop"})
        for connection in connections:
            assert connection.recv()["kind"] == "stopped"
        for p in processes:
            p.join(timeout=5)
            assert p.exitcode == 0 and not p.is_alive()
        report = {"passed": True, "points": 2000, "workers": 4,
            "matrix_bytes": 32000000, "matrix_mapping_pss_sum_kib": sum_pss,
            "matrix_mapping_memory": mappings, "new_worker_reused_prepared_native_bank": True,
            "complete_reference_matches": 5, "single_threaded_before_every_fork": True,
            "formal_architecture_selected": False,
            "limitations": ["Linux-only, clean single-threaded lab, no NumPy/ML runtime",
                "Does not establish safe fork after arbitrary third-party library initialization",
                "Lab supervisor executes preprocessing; a production design still needs external management isolation",
                "Only planned worker retirement; not continuation after algorithm failure",
                "No timing ranking against other topologies"]}
        (ROOT / "prefork_results.json").write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps({k: v for k, v in report.items() if k not in ("matrix_mapping_memory", "limitations")}))
    finally:
        for p in processes:
            if p.is_alive():
                p.kill()
                p.join(timeout=5)
        for connection in connections:
            connection.close()


if __name__ == "__main__":
    main()
