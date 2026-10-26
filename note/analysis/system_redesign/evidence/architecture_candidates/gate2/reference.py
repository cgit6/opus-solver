"""Independent, deliberately small Python oracle. No project imports."""
import json

FIXTURES = [
    {"problem_id": "tiny4", "values": [10, 7, 12, 8],
     "weights": [[4, 2], [3, 2], [6, 3], [5, 4]], "capacities": [8, 5]},
    {"problem_id": "tiny5", "values": [9, 5, 11, 6, 8],
     "weights": [[3, 1], [2, 2], [5, 3], [4, 1], [3, 2]], "capacities": [9, 5]},
]


def canonical(data):
    return (json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode()


def make_bank(module):
    return module.Bank([p["problem_id"] for p in FIXTURES],
                       [p["values"] for p in FIXTURES],
                       [p["weights"] for p in FIXTURES],
                       [p["capacities"] for p in FIXTURES])


def reference(problem_id, seed, iterations):
    p = next(p for p in FIXTURES if p["problem_id"] == problem_id)
    code = [0] * len(p["values"])
    best = code.copy()
    best_fitness = 0
    state = seed
    frames = []
    for step in range(iterations + 1):
        selected = -1
        if step:
            state = (214013 * state + 2531011) % (2 ** 32)
            # Unlike native code, form the 15-bit output by quotient/remainder.
            output = (state // 65536) % 32768
            selected = output % len(code)
            code[selected] = 1 - code[selected]
        # Recompute from scratch; native code uses incremental updates.
        fitness = sum(value for bit, value in zip(code, p["values"]) if bit)
        loads = [sum(row[d] for bit, row in zip(code, p["weights"]) if bit)
                 for d in range(len(p["capacities"]))]
        feasible = all(load <= cap for load, cap in zip(loads, p["capacities"]))
        if feasible and fitness > best_fitness:
            best, best_fitness = code.copy(), fitness
        frames.append({"iteration": step, "label": "updated" if step else "initialized",
                       "code": code.copy(), "raw_fitness": fitness, "feasible": feasible,
                       "loads": loads,
                       "external": {"rng_state": state, "rng_draws": step,
                                    "selected_item": selected, "best_code": best.copy(),
                                    "best_fitness": best_fitness}})
    return {"problem_id": problem_id, "seed": seed, "completed_iterations": iterations,
            "history": frames, "best_code": best, "best_raw_fitness": best_fitness,
            "best_feasible": True}


def assert_equal(actual, expected, path="result"):
    # Type-sensitive comparison: True and 1 must not silently compare equal.
    if type(actual) is not type(expected):
        raise AssertionError(f"{path}: type {type(actual).__name__} != {type(expected).__name__}")
    if isinstance(expected, dict):
        if actual.keys() != expected.keys():
            raise AssertionError(f"{path}: different keys")
        for key in expected:
            assert_equal(actual[key], expected[key], f"{path}.{key}")
    elif isinstance(expected, list):
        if len(actual) != len(expected):
            raise AssertionError(f"{path}: length {len(actual)} != {len(expected)}")
        for index, (a, e) in enumerate(zip(actual, expected)):
            assert_equal(a, e, f"{path}[{index}]")
    elif actual != expected:
        raise AssertionError(f"{path}: {actual!r} != {expected!r}")
