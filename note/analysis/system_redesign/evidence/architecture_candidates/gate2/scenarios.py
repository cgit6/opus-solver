"""Incremental gate-2 fault scenarios; no project imports or performance tests."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import signal

from controller import Controller
from reference import FIXTURES, assert_equal, canonical, reference

ROOT = Path(__file__).resolve().parent
KINDS = ("cpp_exception", "native_abort", "save_path_error", "save_serialization_error",
         "lose_final_notice", "save_notice_then_exit")


def task(output, name, problem_id, seed, behavior="normal", algorithm="control-A"):
    return {"task_id": name, "problem_id": problem_id, "seed": seed, "iterations": 32,
            "algorithm_label": algorithm, "behavior": behavior,
            "path": str(output / "results" / (name + ".json"))}


def observer_check(path, specification):
    # TEST observer only, never called by the experiment Controller.
    data = Path(path).read_bytes()
    expected = reference(specification["problem_id"], specification["seed"], specification["iterations"])
    assert_equal(json.loads(data), expected)
    assert data == canonical(expected)
    return {"path": str(path), "sha256": hashlib.sha256(data).hexdigest(),
            "snapshot_count": len(expected["history"])}


def run_scenario(mode, workers, kind, suite):
    output = suite / f"{mode}-{workers}-{kind}"
    baseline = task(output, "already-delivered", "tiny4", 4)
    target = task(output, "target", "tiny4", 1, kind)
    peers = [task(output, f"peer-{i}", "tiny5", i, algorithm="control-B") for i in range(1, workers)]
    followup = task(output, "new-task-after-save-error", "tiny4", 2)
    pending = task(output, "must-not-be-auto-dispatched", "tiny4", 3)
    if kind == "save_path_error":
        target["path"] = str(output / "software-path-blocker" / "target.json")
    controller = Controller(mode, workers, output, [baseline, target, *peers, followup, pending])
    try:
        if kind == "save_path_error":
            # A real software path conflict, not a full disk or hardware fault.
            (output / "software-path-blocker").write_bytes(b"regular file, not a directory\n")
        controller.run_single(0, baseline)
        assert controller.records[baseline["task_id"]]["final_status"] == "delivered"
        before = observer_check(baseline["path"], baseline)
        controller.assign(0, target)
        for lane, peer in enumerate(peers, start=1):
            controller.assign(lane, peer)
        all_lanes = list(range(workers))
        controller.wait_checkpoint(all_lanes, 0)
        controller.release(all_lanes, 0)
        controller.wait_checkpoint(all_lanes, 1)

        if kind in ("cpp_exception", "native_abort"):
            # Leave all OTHER tasks at the native midpoint and release only
            # the target into its injected throw/abort.
            controller.release([0], 1)
            controller.until(lambda: controller.stopping)
        else:
            controller.release(all_lanes, 1)
            controller.wait_checkpoint(all_lanes, 2)
            # Peers are still in their native calls; only target reaches saver.
            controller.release([0], 2)
            if kind in ("lose_final_notice", "save_notice_then_exit"):
                # Deliberately notice exit before reading buffered final events.
                controller.observe_exit_before_draining_messages(0)
            else:
                controller.until(lambda: controller.records[target["task_id"]]["final_status"] == "save_error")

        if kind in ("save_path_error", "save_serialization_error"):
            assert not controller.stopping
            failure = controller.records[target["task_id"]]["final_report"]
            assert failure["cleanup"]["success"]
            assert failure["cleanup"]["native_result_owner_released"]
            assert failure["error"]["path"] == target["path"]
            assert failure["error"]["message"] and failure["error"]["traceback"]
            if kind == "save_path_error":
                assert failure["error"]["operation"] == "prepare_output_directory"
                assert failure["error"]["exception_type"] in ("FileExistsError", "NotADirectoryError")
                assert failure["error"]["errno"] in (17, 20)
            else:
                assert failure["error"]["operation"] == "serialize"
                assert failure["error"]["exception_type"] == "TypeError"
                assert failure["error"]["errno"] is None
            controller.run_single(0, followup)
            reused = controller.records[followup["task_id"]]["final_report"]
            assert reused["pid"] == failure["pid"]
            assert reused["telemetry"]["native_tid"] == failure["telemetry"]["native_tid"]
            # Successful recovery on lane 0 did not cancel the blocked peers.
            controller.release(list(range(1, workers)), 2)
            controller.until(lambda: all(controller.records[p["task_id"]]["final_status"] == "delivered" for p in peers))
            controller.graceful_close()
        else:
            assert controller.stopping
            try:
                controller.assign(0, pending)
            except RuntimeError:
                pass
            else:
                raise AssertionError("task started after whole-run stop")
            controller.stop_all()

        report = controller.report
        records = report["records"]
        assert report["controller_survived"] and report["controller_pid"] == os.getpid()
        assert report["result_file_reads_by_controller"] == 0
        assert report["automatic_retries"] == 0 and report["all_owned_execution_processes_exited"]
        assert records[baseline["task_id"]]["final_status"] == "delivered"
        after = observer_check(baseline["path"], baseline)
        assert before == after
        observations = [after]
        for specification in [baseline, target, *peers, followup, pending]:
            record = records[specification["task_id"]]
            assert_equal(record["input"], specification)
            if record["final_status"] == "delivered" and specification is not baseline:
                observations.append(observer_check(specification["path"], specification))
        assert records[pending["task_id"]]["final_status"] == "not_dispatched"
        if kind in ("cpp_exception", "native_abort", "lose_final_notice", "save_notice_then_exit"):
            assert records[followup["task_id"]]["final_status"] == "not_dispatched"
            assert all(records[p["task_id"]]["final_status"] == "delivery_unconfirmed" for p in peers)
            assert all(records[p["task_id"]]["root_cause"] == "not_determined" for p in peers)
            assert all(records[p["task_id"]]["facts"] == ["received"] for p in peers)
        if kind == "cpp_exception":
            assert records[target["task_id"]]["final_status"] == "algorithm_error"
            assert records[target["task_id"]]["facts"] == ["received", "algorithm_error"]
            assert records[target["task_id"]]["final_report"]["error"]["exception_type"] == "RuntimeError"
            assert report["stop_reason"]["kind"] == "reported_algorithm_error"
        elif kind == "native_abort":
            assert records[target["task_id"]]["final_status"] == "delivery_unconfirmed"
            assert records[target["task_id"]]["facts"] == ["received"]
            assert any(p["exitcode"] == -signal.SIGABRT for p in report["process_exits"])
            assert all(p["root_cause"] == "not_determined" for p in report["process_exits"])
        elif kind == "lose_final_notice":
            assert records[target["task_id"]]["final_status"] == "delivery_unconfirmed"
            assert records[target["task_id"]]["facts"] == ["received", "cpp_returned"]
            observations.append(observer_check(target["path"], target))
        elif kind == "save_notice_then_exit":
            assert records[target["task_id"]]["final_status"] == "delivered"
            events = report["events"]
            first_exit = next(e["sequence"] for e in events if e["kind"] == "process_exit_observed")
            target_saved = next(e["sequence"] for e in events if e["kind"] == "worker_message"
                and e["message"].get("task_id") == target["task_id"] and e["message"]["kind"] == "saved")
            classified = next(e["sequence"] for e in events if e["kind"] == "process_exit_recorded_after_drain")
            assert first_exit < target_saved < classified
        # Persist separate observer findings, never backfill controller statuses.
        result = {"passed": True, "mode": mode, "workers": workers, "scenario": kind,
                  "controller_report": str(output / "controller_report.json"),
                  "known_statuses": {k: v["final_status"] for k, v in records.items()},
                  "observer_file_checks": observations,
                  "controller_did_not_read_result_files": True,
                  "already_delivered_file_preserved": True,
                  "all_execution_processes_exited": True,
                  "core_dump_disabled_in_children": True,
                  "cleanup_failure_retirement_tested": False,
                  "formal_architecture_selected": False}
        (output / "observer_results.json").write_bytes(canonical(result))
        return result
    except BaseException:
        # Do not label a harness bug as a successful fault scenario.
        controller.emergency_test_cleanup()
        raise


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", nargs="+", choices=("threads", "processes"), default=["threads", "processes"])
    parser.add_argument("--workers", type=int, nargs="+", choices=(2, 4), default=[2, 4])
    parser.add_argument("--scenario", nargs="+", choices=KINDS, default=list(KINDS))
    parser.add_argument("--label", required=True)
    args = parser.parse_args()
    suite = ROOT / ("output-" + args.label)
    suite.mkdir(exist_ok=False)
    passed = []
    for kind in args.scenario:
        for workers in args.workers:
            for mode in args.mode:
                result = run_scenario(mode, workers, kind, suite)
                passed.append(result)
                print(json.dumps({key: result[key] for key in ("passed", "mode", "workers", "scenario", "known_statuses")}), flush=True)
                (suite / "results.json").write_bytes(canonical({"passed": True, "scenarios": passed,
                    "performance_claim": None, "note": "Incremental results, not formal fault recovery acceptance"}))
    print(json.dumps({"passed": True, "scenario_count": len(passed), "suite": str(suite)}))


if __name__ == "__main__":
    main()
