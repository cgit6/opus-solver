"""Independent exact-integer workload oracle. No native module imports."""
import json

MASK = (1 << 64) - 1


def canonical(data):
    return (json.dumps(data, sort_keys=True, separators=(",", ":")) + "\n").encode()


def reference(points, seed, records, work):
    state, total, value = seed, 0, 0
    scratch, history = [0] * 1024, []
    for _ in range(records):
        for _ in range(work):
            state = (state * 6364136223846793005 + 1442695040888963407) & MASK
            slot = (state >> 32) % 1024
            matrix_value = ((state % (points * points)) * 7 + 13) % 100003
            scratch[slot] = (scratch[slot] + (matrix_value ^ state)) & MASK
            value = scratch[slot] ^ state
        history.append(value)
        total = (total + value) & MASK
    return {"checksum": total, "history": history, "problem_points": points,
            "rng_draws": records * work, "rng_state": state, "seed": seed,
            "steps_per_record": work, "workspace_checksum": sum(scratch) & MASK}
