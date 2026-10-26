"""Independent artifact checks and descriptive statistics; no solver runs."""
import collections
import hashlib
import json
from pathlib import Path
import statistics

from perf_reference import canonical, MASK

ROOT = Path(__file__).resolve().parent


def read(name):
    return json.loads((ROOT / name).read_bytes())


def rng_jump(seed, count):
    # Independent affine exponentiation rather than replaying the work loop.
    accumulated_multiplier, accumulated_increment = 1, 0
    multiplier, increment = 6364136223846793005, 1442695040888963407
    while count:
        if count & 1:
            accumulated_multiplier = accumulated_multiplier * multiplier & MASK
            accumulated_increment = (accumulated_increment * multiplier + increment) & MASK
        increment = (multiplier + 1) * increment & MASK
        multiplier = multiplier * multiplier & MASK
        count >>= 1
    return (seed * accumulated_multiplier + accumulated_increment) & MASK


def main():
    raw = read("benchmark_results.json")
    references = read("perf_reference_hashes.json")
    assert references["source_sha256"] == hashlib.sha256((ROOT / "perf_reference.py").read_bytes()).hexdigest()
    expected = {tuple(r["input"]): r["sha256"] for r in references["rows"]}
    assert len(expected) == 48
    groups = collections.defaultdict(list)
    for row in raw["timing_trials"]:
        key = tuple(row[k] for k in ("points", "workers", "workload", "mode", "saver"))
        groups[key].append(row)
        assert len(row["tasks"]) == 8
        assert {r["seed"] for r in row["tasks"]} == set(range(1, 9))
        assert row["batch_s"] > 0
        for task in row["tasks"]:
            assert task["task_s"] >= task["compute_s"] + task["serialize_s"] + task["write_s"] - 0.000001
    assert len(groups) == 48 and all(len(rows) == 5 for rows in groups.values())
    summaries = []
    for key, rows in sorted(groups.items()):
        times = [r["batch_s"] for r in rows]
        summaries.append(dict(zip(("points", "workers", "workload", "mode", "saver"), key),
            samples=len(times), median_s=statistics.median(times), min_s=min(times), max_s=max(times),
            median_sum_compute_s=statistics.median(sum(t["compute_s"] for t in r["tasks"]) for r in rows),
            median_sum_serialize_s=statistics.median(sum(t["serialize_s"] for t in r["tasks"]) for r in rows),
            median_sum_write_s=statistics.median(sum(t["write_s"] for t in r["tasks"]) for r in rows)))
    file_count, total_bytes = 0, 0
    for path in (ROOT / "performance-measured").rglob("seed*.json"):
        data = path.read_bytes()
        parsed = json.loads(data)
        key = (parsed["problem_points"], parsed["seed"], len(parsed["history"]), parsed["steps_per_record"])
        assert hashlib.sha256(data).hexdigest() == expected[key]
        assert parsed["rng_draws"] == len(parsed["history"]) * parsed["steps_per_record"]
        assert parsed["rng_state"] == rng_jump(parsed["seed"], parsed["rng_draws"])
        assert parsed["checksum"] == sum(parsed["history"]) & MASK
        assert data == canonical(parsed)
        file_count += 1
        total_bytes += len(data)
    assert file_count == 2336  # 1920 measured + 384 warmup + 32 memory-run files.
    assert len(raw["memory_trials"]) == 8
    memory_summaries = []
    for row in raw["memory_trials"]:
        assert len(row["tasks"]) == 4 and row["sample_count"] >= 1
        assert row["retained_result_memory"] is not None
        for t in row["tasks"]:
            assert t["bank"]["problem_bytes"] == row["points"] ** 2 * 8
        memory_summaries.append({"points": row["points"], "mode": row["mode"], "saver": row["saver"],
            "workers": 4, "samples": row["sample_count"],
            "ready_pss_mib": row["after_ready_memory"]["pss_kib"] / 1024,
            "held_result_pss_mib": row["retained_result_memory"]["pss_kib"] / 1024,
            "peak_sampled_pss_mib": row["peak_sampled_pss_kib"] / 1024,
            "native_problem_bytes_total": row["points"] ** 2 * 8 * (1 if row["mode"] == "threads" else 4)})
    extra = []
    for label in ("first", "repeat"):
        suite = read(f"extra-{label}/results.json")
        assert suite["passed"] and len(suite["cases"]) == 24
        for case in suite["cases"]:
            assert case["passed"]
            report = json.loads(Path(case["controller_report"]).read_bytes())
            assert report["all_owned_execution_processes_exited"]
            assert report["result_file_reads_by_controller"] == 0
            assert report["automatic_retries"] == 0
            record = report["records"]["target"]
            if case["kind"] == "partial_delivery":
                assert record["final_status"] == "delivery_unconfirmed"
                assert record["facts"] == ["received", "cpp_returned"]
                if case["worker_saved_error_first"]:
                    error_file = json.loads(Path(record["input"]["error_record_path"]).read_bytes())
                    assert error_file["error"]["exception_type"] == "TypeError"
                    assert error_file["error"]["traceback"]
            else:
                assert record["final_status"] == "save_error"
                assert not record["final_report"]["cleanup"]["native_result_owner_released"]
                assert "error" in record["final_report"]["cleanup"]
                assert report["records"]["must-not-reuse-untrusted-lane"]["final_status"] == "not_dispatched"
                lost = sum(r["final_status"] == "delivery_unconfirmed" for r in report["records"].values())
                assert lost == case["other_tasks_lost"]
            extra.append(case)
    assert len(extra) == 48
    real = read("real_cdels_results.json")
    assert real["passed"] and len(real["cases"]) == 8
    assert all(r["passed"] and len(r["checks"]) == 12 for r in real["cases"])
    by_input = collections.defaultdict(set)
    for row in real["cases"]:
        by_input[(row["seed"], row["iterations"])].add(row["process_trace_sha256"])
    assert len(by_input) == 6 and all(len(x) == 1 for x in by_input.values())
    prefork, readonly, rng = read("prefork_results.json"), read("readonly_results.json"), read("legacy_rng_interleave_results.json")
    assert prefork["passed"] and readonly["passed"] and rng["negative_control_detected"]
    assert prefork["complete_reference_matches"] == 5
    assert prefork["matrix_bytes"] == 32000000
    assert 29000 < prefork["matrix_mapping_pss_sum_kib"] < 36000
    assert [c["returncode"] for c in readonly["cases"]] == [0, -11, 0]
    result = {"passed": True, "timing_batches": 240, "timing_configuration_count": 48,
        "repeats_per_timing_configuration": 5, "memory_cases": 8,
        "full_benchmark_files_checked": file_count, "full_benchmark_bytes_checked": total_bytes,
        "extra_failure_and_policy_cases": 48, "real_cdels_runs": 8, "real_cdels_unique_inputs": 6,
        "real_cdels_comparison_fields_per_run": 12, "prefork_reference_checks": 5,
        "readonly_guard_cases": 3, "legacy_rng_negative_control_detected": True,
        "prefork_matrix_mapping_pss_sum_kib": prefork["matrix_mapping_pss_sum_kib"],
        "formal_architecture_selected": False, "formal_policies_changed": False,
        "real_cpp_cdels_thread_safety_verified": False,
        "timing_summary": summaries, "memory_summary": memory_summaries,
        "cleanup_comparisons": [c for c in extra if c["kind"] == "cleanup_policy_comparison"],
        "source_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                           for p in ROOT.iterdir() if p.suffix in (".py", ".cpp", ".md")}}
    (ROOT / "combined_audit.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({k: v for k, v in result.items() if k not in
        ("timing_summary", "memory_summary", "cleanup_comparisons", "source_sha256")}))


if __name__ == "__main__":
    main()
