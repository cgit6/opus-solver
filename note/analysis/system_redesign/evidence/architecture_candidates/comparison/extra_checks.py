"""Probe unresolved policies as alternatives; do not select a formal policy."""
import json
from pathlib import Path

from controller import Controller
from reference import canonical, reference

ROOT = Path(__file__).resolve().parent


def task(output, name, seed, behavior="normal", **extra):
    return {"task_id": name, "problem_id": "tiny4", "seed": seed, "iterations": 32,
            "behavior": behavior, "path": str(output / "results" / (name + ".json")), **extra}


def check_file(specification):
    data = Path(specification["path"]).read_bytes()
    expected = canonical(reference("tiny4", specification["seed"], 32))
    assert data == expected


def start_wave(controller, target, peers):
    controller.assign(0, target)
    for i, peer in enumerate(peers, 1):
        controller.assign(i, peer)
    lanes = list(range(controller.workers))
    controller.wait_checkpoint(lanes, 0)
    controller.release(lanes, 0)
    controller.wait_checkpoint(lanes, 1)
    controller.release(lanes, 1)
    controller.wait_checkpoint(lanes, 2)
    controller.release([0], 2)


def partial_case(mode, workers, behavior, retain_error, root):
    name = f"{mode}-{workers}-{behavior}-errorfile{int(retain_error)}"
    output = root / name
    target = task(output, "target", 1, behavior)
    if retain_error:
        target["error_record_path"] = str(output / "errors" / "target.json")
    peers = [task(output, f"peer-{i}", i + 1) for i in range(1, workers)]
    c = Controller(mode, workers, output, [target, *peers])
    try:
        start_wave(c, target, peers)
        c.until(lambda: c.stopping)
        c.stop_all()
        record = c.report["records"]["target"]
        assert record["final_status"] == "delivery_unconfirmed"
        assert record["facts"] == ["received", "cpp_returned"]
        assert c.report["result_file_reads_by_controller"] == 0
        if behavior == "partial_saved_frame":
            check_file(target)
        elif behavior == "partial_file_exit":
            data = Path(target["path"]).read_bytes()
            expected = canonical(reference("tiny4", 1, 32))
            assert data == expected[:len(expected) // 2] and data != expected
        if behavior.endswith("frame"):
            assert any(e["kind"] == "connection_closed" and e["exception_type"] == "OSError"
                       for e in c.report["events"])
        if retain_error:
            error = json.loads(Path(target["error_record_path"]).read_bytes())
            assert error["error"]["exception_type"] == "TypeError"
            assert error["error"]["operation"] == "serialize"
            assert error["error"]["traceback"]
        return {"passed": True, "kind": "partial_delivery", "mode": mode, "workers": workers,
                "behavior": behavior, "worker_saved_error_first": retain_error,
                "manager_status": record["final_status"],
                "error_detail_available_after_lost_notification": retain_error,
                "controller_report": str(output / "controller_report.json")}
    except BaseException:
        c.emergency_test_cleanup()
        raise


def finish_live_processes(c):
    live_lanes = [i for i, info in c.ready.items() if info["pid"] not in c.exits]
    c.closing = True
    for i in live_lanes:
        c.connections[i].send({"op": "stop"})
    c.until(lambda: all(i in c.stopped for i in live_lanes))
    for p in c.processes:
        p.join(timeout=5)
        assert not p.is_alive()
        c.on_exit(p)
    c.finalize()


def cleanup_case(mode, workers, policy, root):
    output = root / f"{mode}-{workers}-cleanup-{policy}"
    target = task(output, "target", 1, "save_serialization_error", force_cleanup_failure=True)
    peers = [task(output, f"peer-{i}", i + 1) for i in range(1, workers)]
    blocked = task(output, "must-not-reuse-untrusted-lane", 4)
    c = Controller(mode, workers, output, [target, *peers, blocked])
    try:
        start_wave(c, target, peers)
        c.until(lambda: c.records["target"]["final_status"] == "save_error")
        failure = c.records["target"]["final_report"]
        assert not failure["cleanup"]["success"]
        assert not failure["cleanup"]["native_result_owner_released"]
        assert failure["cleanup"]["error"]["exception_type"] == "RuntimeError"
        try:
            c.assign(0, blocked)
        except RuntimeError:
            pass
        else:
            raise AssertionError("untrusted lane reused")
        if policy == "retire_host_now":
            pid = c.ready[0]["pid"]
            c.expected_retirement_pids.add(pid)
            p = next(p for p in c.processes if p.pid == pid)
            c.log("TEST_POLICY_retire_affected_host", pid=pid)
            p.terminate()
            p.join(timeout=5)
            assert not p.is_alive()
            c.on_exit(p)
            if mode == "processes":
                c.release(list(range(1, workers)), 2)
                c.until(lambda: all(c.records[t["task_id"]]["final_status"] == "delivered" for t in peers))
            finish_live_processes(c)
        else:
            # Proposed graceful retirement: stop admission to this host, wait
            # for its known healthy tasks, then retire. No timeout guarantee.
            c.log("TEST_POLICY_drain_healthy_tasks_then_retire_host")
            c.release(list(range(1, workers)), 2)
            c.until(lambda: all(c.records[t["task_id"]]["final_status"] == "delivered" for t in peers))
            c.graceful_close()
        affected = sum(r["final_status"] == "delivery_unconfirmed" for r in c.report["records"].values())
        expected_affected = workers - 1 if mode == "threads" and policy == "retire_host_now" else 0
        assert affected == expected_affected
        assert c.report["records"]["target"]["final_status"] == "save_error"
        for t in peers:
            if c.report["records"][t["task_id"]]["final_status"] == "delivered":
                check_file(t)
        # A separate fresh host demonstrates reconstruction, not resumption or
        # automatic retry of the failed task. Processes mode replaces one host.
        replacement_task = task(output / "replacement", "new-input-not-a-retry", 4)
        replacement = Controller(mode, workers if mode == "threads" else 1,
                                 output / "replacement", [replacement_task])
        replacement.run_single(0, replacement_task)
        replacement.graceful_close()
        check_file(replacement_task)
        assert all(info["bank"]["prepared_problems"] == 2 for info in replacement.ready.values())
        assert not {p["pid"] for p in c.report["process_exits"]} & {p["pid"] for p in replacement.report["process_exits"]}
        return {"passed": True, "kind": "cleanup_policy_comparison", "mode": mode, "workers": workers,
                "TEST_POLICY": policy, "other_tasks_lost": affected,
                "new_host_reconstructed_problem_bank": True,
                "formal_policy_selected": False,
                "controller_report": str(output / "controller_report.json")}
    except BaseException:
        c.emergency_test_cleanup()
        raise


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", required=True)
    args = parser.parse_args()
    root = ROOT / ("extra-" + args.label)
    root.mkdir(exist_ok=False)
    rows = []
    for mode in ("threads", "processes"):
        for workers in (2, 4):
            for behavior in ("partial_saved_frame", "partial_file_exit", "partial_error_frame"):
                for retain_error in ((False, True) if behavior == "partial_error_frame" else (False,)):
                    row = partial_case(mode, workers, behavior, retain_error, root)
                    rows.append(row)
                    print(json.dumps(row), flush=True)
            for policy in ("retire_host_now", "finish_peers_then_retire"):
                row = cleanup_case(mode, workers, policy, root)
                rows.append(row)
                print(json.dumps(row), flush=True)
    (root / "results.json").write_text(json.dumps({"passed": True, "cases": rows,
        "note": "Competing proposals tested; no formal policy selected"}, indent=2) + "\n")
    print(json.dumps({"passed": True, "case_count": len(rows)}), flush=True)


if __name__ == "__main__":
    main()
