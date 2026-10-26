"""Read-only observer of completed gate-2 evidence. Never calls a solver."""
import argparse
import ast
import collections
import hashlib
import json
from pathlib import Path

from reference import FIXTURES, assert_equal, canonical, reference
from scenarios import KINDS

ROOT = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", required=True)
    parser.add_argument("--expected-rounds", type=int, default=1)
    args = parser.parse_args()
    coverage, states, exits = collections.Counter(), collections.Counter(), collections.Counter()
    file_checks = native_calls = 0
    details = []
    # Independent static check: controller does not read/stat/scan result files.
    tree = ast.parse((ROOT / "controller.py").read_text())
    forbidden = {"read_bytes", "read_text", "glob", "rglob", "exists", "is_file", "stat"}
    assert not any(isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                   and n.func.attr in forbidden for n in ast.walk(tree))
    for suite_path in sorted(ROOT.glob("output-*/results.json")):
        suite = json.loads(suite_path.read_bytes())
        assert suite["passed"] and suite["performance_claim"] is None
        for result in suite["scenarios"]:
            assert result["passed"]
            key = (result["mode"], result["workers"], result["scenario"])
            coverage[key] += 1
            report_path = Path(result["controller_report"])
            report = json.loads(report_path.read_bytes())
            output = report_path.parent
            inputs = json.loads((output / "planned_inputs.json").read_bytes())
            assignments = [json.loads(row) for row in (output / "assignments.jsonl").read_bytes().splitlines()]
            raw_events = [json.loads(row) for row in (output / "events.jsonl").read_bytes().splitlines()]
            assert_equal(raw_events, report["events"])
            assert_equal(inputs["actual_problems"], FIXTURES)
            assert report["controller_survived"] and report["all_owned_execution_processes_exited"]
            assert report["result_file_reads_by_controller"] == report["automatic_retries"] == 0
            assert all(p["pid"] != report["controller_pid"] for p in report["process_exits"])
            assigned_ids = [a["actual_input"]["task_id"] for a in assignments]
            assert len(assigned_ids) == len(set(assigned_ids))
            native_calls += len(assignments)
            for specification in inputs["tasks"]:
                task_id = specification["task_id"]
                record = report["records"][task_id]
                assert_equal(record["input"], specification)
                states[record["final_status"]] += 1
                task_events = [e for e in raw_events if e["kind"] == "worker_message"
                               and e["message"].get("task_id") == task_id]
                assert record["facts"] == [e["message"]["kind"] for e in task_events]
                if task_id in assigned_ids:
                    assignment = next(a for a in assignments if a["actual_input"]["task_id"] == task_id)
                    assert_equal(assignment["actual_input"], specification)
                    assigned_event = next(e for e in raw_events if e["kind"] == "task_assigned" and e["task_id"] == task_id)
                    assert not task_events or assigned_event["sequence"] < task_events[0]["sequence"]
                else:
                    assert record["final_status"] == "not_dispatched"
                if record["final_status"] == "delivered":
                    summary = record["final_report"]
                    data = Path(summary["path"]).read_bytes()
                    expected = reference(specification["problem_id"], specification["seed"], specification["iterations"])
                    assert_equal(json.loads(data), expected)
                    assert data == canonical(expected)
                    assert hashlib.sha256(data).hexdigest() == summary["sha256"]
                    file_checks += 1
                elif record["final_status"] == "delivery_unconfirmed":
                    assert "final_report" not in record and record["root_cause"] == "not_determined"
            target = report["records"]["target"]
            kind = result["scenario"]
            if kind.startswith("save_") and kind != "save_notice_then_exit":
                assert not report["stop_requested"] and target["final_status"] == "save_error"
                assert target["final_report"]["cleanup"]["success"]
                assert target["final_report"]["error"]["message"]
                followup = report["records"]["new-task-after-save-error"]["final_report"]
                failure = target["final_report"]
                assert followup["pid"] == failure["pid"]
                assert followup["telemetry"]["native_tid"] == failure["telemetry"]["native_tid"]
                assert all(info["bank"]["active"] == info["bank"]["live_results"] == 0
                           for info in report["stopped"].values())
            else:
                assert report["stop_requested"]
                stop_event = next(e["sequence"] for e in raw_events if e["kind"] == "whole_experiment_stop_requested")
                assert not any(e["kind"] == "task_assigned" and e["sequence"] > stop_event for e in raw_events)
                for name, record in report["records"].items():
                    if name.startswith("peer-"):
                        assert record["final_status"] == "delivery_unconfirmed"
                        assert record["facts"] == ["received"]
                assert report["records"]["new-task-after-save-error"]["final_status"] == "not_dispatched"
            if kind == "cpp_exception":
                assert target["final_status"] == "algorithm_error"
                assert report["stop_reason"]["kind"] == "reported_algorithm_error"
            elif kind == "native_abort":
                assert target["final_status"] == "delivery_unconfirmed"
                assert any(p["signal"] == "SIGABRT" for p in report["process_exits"])
            elif kind == "lose_final_notice":
                assert target["final_status"] == "delivery_unconfirmed"
                assert target["facts"] == ["received", "cpp_returned"]
                data = Path(target["input"]["path"]).read_bytes()
                specification = target["input"]
                assert data == canonical(reference(specification["problem_id"], specification["seed"], specification["iterations"]))
                # The observer sees a complete file; the recorded outcome MUST
                # remain unconfirmed. Never modify the controller's record.
                file_checks += 1
            elif kind == "save_notice_then_exit":
                assert target["final_status"] == "delivered"
                observed = next(e["sequence"] for e in raw_events if e["kind"] == "process_exit_observed")
                saved = next(e["sequence"] for e in raw_events if e["kind"] == "worker_message"
                             and e["message"].get("task_id") == "target" and e["message"]["kind"] == "saved")
                classified = next(e["sequence"] for e in raw_events if e["kind"] == "process_exit_recorded_after_drain")
                assert observed < saved < classified
            assert report["records"]["already-delivered"]["final_status"] == "delivered"
            for event in report["process_exits"]:
                exits[str(event["exitcode"])] += 1
            details.append({"mode": key[0], "workers": key[1], "scenario": key[2],
                            "controller_report": str(report_path), "passed": True})
    expected = {(m, w, k) for m in ("threads", "processes") for w in (2, 4) for k in KINDS}
    assert set(coverage) == expected
    assert set(coverage.values()) == {args.expected_rounds}
    sources = ("kernel.cpp", "reference.py", "build.py", "smoke.py", "fault_workers.py",
               "controller.py", "scenarios.py", "audit_faults.py", "README.md")
    result = {"passed": True, "scenario_count": len(details), "coverage_combinations": len(coverage),
              "rounds_per_combination": args.expected_rounds, "dispatched_tasks": native_calls,
              "task_status_counts": dict(states), "complete_file_checks": file_checks,
              "snapshots_in_checked_files": 33 * file_checks,
              "observed_execution_exitcodes": dict(exits),
              "actual_inputs_and_event_ledgers_rechecked": True,
              "controller_does_not_read_result_files": True,
              "all_owned_execution_processes_exited": True,
              "cleanup_failure_retirement_tested": False, "performance_claim": None,
              "formal_architecture_selected": False,
              "source_sha256": {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in sources},
              "scenarios": details}
    destination = ROOT / ("audit-" + args.label + ".json")
    with destination.open("xb") as stream:
        stream.write(canonical(result))
    print(json.dumps({k: v for k, v in result.items() if k not in ("scenarios", "source_sha256")}))


if __name__ == "__main__":
    main()
