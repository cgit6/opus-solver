"""First increment: verify the native kernel before adding concurrency."""
import copy
import gc
import json
from pathlib import Path
import gate1_kernel as native
from reference import FIXTURES, assert_equal, canonical, make_bank, reference

bank = make_bank(native)
assert_equal(bank.export_problems(), FIXTURES)
baseline = []
held = None
held_bytes = None
negative_checks = 0
for iterations in (0, 32):
    for p in FIXTURES:
        for seed in (1, 2, 3, 4):
            result = bank.solve(p["problem_id"], seed, iterations)
            expected = reference(p["problem_id"], seed, iterations)
            assert_equal(result.to_dict(), expected)
            assert canonical(result.to_dict()) == canonical(expected)
            if held is None:
                held, held_bytes = result, canonical(result.to_dict())
            else:
                assert canonical(held.to_dict()) == held_bytes
            baseline.append({"problem_id": p["problem_id"], "seed": seed,
                             "iterations": iterations, "snapshots": len(expected["history"])})
            if iterations:
                for field, replacement in (("raw_fitness", -999), ("feasible", 1),
                                           ("code", [1] * len(p["values"]))):
                    wrong = copy.deepcopy(expected)
                    wrong["history"][0][field] = replacement
                    try:
                        assert_equal(wrong, expected)
                    except AssertionError:
                        negative_checks += 1
                    else:
                        raise AssertionError("comparator missed a deliberate corruption")
del result
assert bank.diagnostics()["live_results"] == 1
del held
gc.collect()
assert bank.diagnostics()["live_results"] == 0
assert bank.diagnostics()["active"] == 0
assert_equal(bank.export_problems(), FIXTURES)
report = {"passed": True, "native_calls": len(baseline),
          "snapshots_compared": sum(x["snapshots"] for x in baseline),
          "comparator_negative_controls": negative_checks,
          "result_lifetime_and_readonly_contents_passed": True,
          "native_counts_after_release": bank.diagnostics(), "cases": baseline}
Path(__file__).with_name("smoke_results.json").write_text(json.dumps(report, indent=2) + "\n")
print(json.dumps({k: v for k, v in report.items() if k not in ("cases", "native_counts_after_release")}))
