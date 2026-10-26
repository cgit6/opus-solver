"""Fault-injection worker shell. Used ONLY in isolated gate-2 children."""
from concurrent.futures import ThreadPoolExecutor
import gc
import hashlib
import os
from pathlib import Path
import resource
import traceback
import weakref

from reference import FIXTURES, canonical, make_bank


def fingerprint(bank):
    return hashlib.sha256(canonical(bank.export_problems())).hexdigest()


class SaveFailure(Exception):
    def __init__(self, details):
        super().__init__(details["message"])
        self.details = details


def save_python(result, task):
    """Same saver and format as gate 1, with precise software-error context."""
    operation = "serialize"
    try:
        data = result.to_dict()
        if task["behavior"] == "save_serialization_error":
            # The real JSON serializer rejects a set; no simulated error text.
            data["injected_non_json_value"] = {1, 2}
        payload = canonical(data)
        operation = "prepare_output_directory"
        path = Path(task["path"])
        path.parent.mkdir(parents=True, exist_ok=True)
        operation = "open_output"
        with path.open("xb") as stream:
            operation = "write_output"
            stream.write(payload)
            operation = "flush_output"
            stream.flush()
            os.fsync(stream.fileno())
        operation = "close_output"
        return {"path": str(path), "bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest()}
    except Exception as error:
        # Store strings/numbers, not an exception/traceback object that could
        # keep the native Result alive through references to stack frames.
        raise SaveFailure({"operation": operation, "path": task["path"],
            "exception_type": type(error).__name__, "errno": getattr(error, "errno", None),
            "message": str(error), "traceback": traceback.format_exc()}) from None


def lane(lane_id, connection, gate, bank):
    expected_digest = hashlib.sha256(canonical(FIXTURES)).hexdigest()
    connection.send({"kind": "ready", "lane": lane_id, "pid": os.getpid(),
                     "bank_digest": fingerprint(bank), "bank": bank.diagnostics()})
    while True:
        command = connection.recv()
        if command["op"] == "stop":
            connection.send({"kind": "stopped", "lane": lane_id, "pid": os.getpid(),
                             "bank": bank.diagnostics(), "bank_digest": fingerprint(bank)})
            connection.close()
            gate.close()
            return
        if command["op"] != "run":
            raise AssertionError("unknown test command")
        task = command["task"]
        common = {"lane": lane_id, "pid": os.getpid(), "task_id": task["task_id"]}
        connection.send({"kind": "received", **common})
        fault = {"cpp_exception": 1, "native_abort": 2}.get(task["behavior"], 0)
        try:
            result = bank.solve(task["problem_id"], task["seed"], task["iterations"], gate.fileno(), fault)
        except Exception as error:
            connection.send({"kind": "algorithm_error", **common,
                "error": {"exception_type": type(error).__name__, "message": str(error),
                          "traceback": traceback.format_exc()}, "bank": bank.diagnostics()})
            # Quarantine immediately. Do not accept another task after an
            # algorithm error while the controller initiates whole-run stop.
            connection.recv()
            return
        connection.send({"kind": "cpp_returned", **common})
        telemetry = result.measurements()
        owner = weakref.ref(result)
        save_error = None
        output = None
        try:
            output = save_python(result, task)
        except SaveFailure as error:
            save_error = error.details
        finally:
            del result
        gc.collect()
        cleanup = {"native_result_owner_released": owner() is None,
                   "bank_contents_unchanged": fingerprint(bank) == expected_digest,
                   "bank": bank.diagnostics()}
        cleanup["success"] = cleanup["native_result_owner_released"] and cleanup["bank_contents_unchanged"]
        if save_error is not None:
            connection.send({"kind": "save_error", **common, "error": save_error,
                             "cleanup": cleanup, "telemetry": telemetry})
            if not cleanup["success"]:
                # Retirement scope for an untrusted lane in a shared process is
                # NOT decided here. Do not silently reuse or replace the host.
                connection.recv()
                return
            continue
        if not cleanup["success"]:
            raise AssertionError("unexpected cleanup failure in a normal test save")
        if task["behavior"] == "lose_final_notice":
            # Actual file is flushed/closed; no final message is delivered.
            # Deliberately exits the host, not a C++ fault or inferred root cause.
            os._exit(0)
        connection.send({"kind": "saved", **common, **output,
                         "cleanup": cleanup, "telemetry": telemetry})
        if task["behavior"] == "save_notice_then_exit":
            os._exit(0)


def wrap_lane(lane_id, connection, gate, bank):
    try:
        lane(lane_id, connection, gate, bank)
    except BaseException:
        connection.send({"kind": "harness_error", "lane": lane_id,
                         "pid": os.getpid(), "traceback": traceback.format_exc()})
        raise


def thread_host(connections, gates):
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    import gate1_kernel as native
    bank = make_bank(native)
    with ThreadPoolExecutor(max_workers=len(connections)) as executor:
        futures = [executor.submit(wrap_lane, i, connection, gates[i], bank)
                   for i, connection in enumerate(connections)]
        for future in futures:
            future.result()


def process_host(lane_id, connection, gate):
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    import gate1_kernel as native
    wrap_lane(lane_id, connection, gate, make_bank(native))
