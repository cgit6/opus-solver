"""Recheck saved evidence independently of the dispatch loop; no solver calls."""
import argparse
import collections
import hashlib
import json
from pathlib import Path
from reference import FIXTURES, assert_equal, canonical, reference

ROOT = Path(__file__).resolve().parent


def read(path):
    return json.loads(path.read_bytes())


def check_no_history(value):
    if isinstance(value, dict):
        assert not ({"history", "code", "best_code", "loads"} & value.keys())
        for nested in value.values():
            check_no_history(nested)
    elif isinstance(value, list):
        for nested in value:
            check_no_history(nested)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--suites", nargs="+", default=["output-serial-check", "output-two-check", "output-four-check"])
    args = parser.parse_args()
    cases = []
    for name in args.suites:
        suite = read(ROOT / name / "results.json")
        assert suite["passed"] and suite["performance_claim"] is None
        assert not suite["formal_architecture_selected"]
        assert_equal(suite["fixtures"], FIXTURES)
        cases.extend(suite["cases"])
    assert {(c["mode"], c["workers"]) for c in cases} == {
        (mode, workers) for mode in ("threads", "processes") for workers in (1, 2, 4)}
    assert len(cases) == 6
    hashes = collections.defaultdict(set)
    counts = collections.Counter()
    summaries = []
    for case in cases:
        assert case["passed"] and len(case["outputs"]) == 48
        workers = case["workers"]
        expected_banks = 1 if case["mode"] == "threads" else workers
        assert case["native_bank_count"] == expected_banks
        assert case["native_problem_object_count"] == 2 * expected_banks
        assert all(event["bank_contents_unchanged"] for event in case["events"] if event["kind"] == "saved")
        for event in case["events"]:
            check_no_history(event)
        ledger_path = Path(case["outputs"][0]["summary"]["path"]).parents[1] / "input_ledger.jsonl"
        ledger = [json.loads(line) for line in ledger_path.read_bytes().splitlines()]
        assert len(ledger) == 48
        records = {(entry["batch_id"], entry["task"]["task_id"]): entry for entry in ledger}
        assert len(records) == 48
        by_batch = collections.defaultdict(list)
        for entry in case["outputs"]:
            task, summary = entry["task"], entry["summary"]
            record = records[(entry["batch_id"], task["task_id"])]
            assert_equal(record["task"], task)
            problem = next(p for p in FIXTURES if p["problem_id"] == task["problem_id"])
            assert_equal(record["actual_problem"], problem)
            data = Path(summary["path"]).read_bytes()
            expected = reference(task["problem_id"], task["seed"], task["iterations"])
            assert_equal(json.loads(data), expected)
            assert data == canonical(expected)
            fingerprint = hashlib.sha256(data).hexdigest()
            assert fingerprint == summary["sha256"] and len(data) == summary["bytes"]
            hashes[task["task_id"]].add(fingerprint)
            counts["saved_tasks"] += 1
            counts["snapshots"] += len(expected["history"])
            counts["output_bytes"] += len(data)
            if task["iterations"]:
                by_batch[entry["batch_id"]].append(summary)
        # Reconstruct waves by their ordered records and lane sequence.
        overlap_waves = 0
        for entries in by_batch.values():
            for start in range(0, len(entries), workers):
                wave = entries[start:start + workers]
                assert len(wave) == workers
                assert max(m["telemetry"]["compute_start_ns"] for m in wave) < min(
                    m["telemetry"]["compute_finish_ns"] for m in wave)
                if workers > 1:
                    overlap_waves += 1
        assert sum(p["phase"] == 1 for p in case["overlap_evidence"]) == 24 // workers
        assert case["snapshots_compared"] == 816
        expected_runs = 48 if case["mode"] == "threads" else 48 // workers
        expected_checks = 816 if case["mode"] == "threads" else 816 // workers
        for stopped in case["stopped"]:
            stat = stopped["bank"]
            assert stat["runs"] == expected_runs
            assert stat["history_fitness_checks"] == expected_checks
            assert stat["active"] == stat["live_results"] == 0
            assert stat["prepared_problems"] == 2
            assert stat["peak_active"] == (workers if case["mode"] == "threads" else 1)
        counts["retained_result_rechecks"] += case["retained_result_rechecks"]
        counts["overlap_waves"] += overlap_waves
        summaries.append({"mode": case["mode"], "workers": workers, "saved_tasks": 48,
                          "snapshots": 816, "native_banks": expected_banks,
                          "native_problem_objects": 2 * expected_banks,
                          "parallel_update_overlap_waves": overlap_waves,
                          "live_native_results_after_release": 0})
    assert len(hashes) == 16 and all(len(value) == 1 for value in hashes.values())
    assert counts["saved_tasks"] == 288 and counts["snapshots"] == 4896
    sources = ("kernel.cpp", "reference.py", "build.py", "smoke.py", "experiment.py", "audit.py", "README.md")
    result = {"passed": True, "case_count": len(cases), **counts,
              "unique_inputs": len(hashes), "same_complete_bytes_across_all_candidates": True,
              "no_histories_in_management_messages": True, "actual_inputs_recorded": True,
              "source_sha256": {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in sources},
              "baseline_smoke": read(ROOT / "smoke_results.json"),
              "cases": summaries, "performance_claim": None,
              "limits": "No fault injection, actual CDELS, large-instance memory or OS readonly validation"}
    (ROOT / "audit_results.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({k: v for k, v in result.items() if k not in ("source_sha256", "baseline_smoke", "cases")}))


if __name__ == "__main__":
    main()
