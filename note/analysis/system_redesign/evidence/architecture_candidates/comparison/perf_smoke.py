import json
from pathlib import Path
import perf_kernel as native
from perf_reference import canonical, reference

root = Path(__file__).resolve().parent
output = root / "perf-smoke-files"
output.mkdir(exist_ok=False)
count = 0
for points in (8, 64, 2000):
    bank = native.Bank(points)
    for seed in (1, 2):
        for records in (1, 17):
            for work in (1, 3):
                result = bank.run(seed, records, work)
                expected = canonical(reference(points, seed, records, work))
                assert canonical(result.to_dict()) == expected
                path = output / f"n{points}-s{seed}-r{records}-w{work}.json"
                native.save_native(result, str(path))
                assert path.read_bytes() == expected
                del result
                count += 1
    assert bank.diagnostics()["live_history_bytes"] == 0
(root / "perf_smoke_results.json").write_text(json.dumps({"passed": True,
    "independent_reference_cases": count, "native_and_python_json_bytes_equal": True}) + "\n")
print("passed", count, "independent exact-content checks")
