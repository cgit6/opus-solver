"""Experimental event-driven controller, not the project's formal scheduler.

It never inspects result files to infer completion and never receives histories.
Native checkpoints exist only to control test ordering. Their facts do not
replace the two production-style stage notifications.
"""
import json
import multiprocessing as mp
from multiprocessing.connection import wait
import os
from pathlib import Path
import signal
import socket

from fault_workers import process_host, thread_host
from reference import FIXTURES, canonical

TEST_WATCHDOG = 20  # Test safety only, not a production task timeout.
FINAL = {"delivered", "algorithm_error", "save_error", "delivery_unconfirmed", "not_dispatched"}


class Controller:
    def __init__(self, mode, workers, output, tasks):
        self.mode, self.workers, self.output = mode, workers, Path(output)
        self.output.mkdir(parents=True, exist_ok=False)
        self.records = {t["task_id"]: {"input": t, "facts": [], "final_status": None} for t in tasks}
        self.planned = list(self.records)
        # All actual values are retained before any child starts or task runs.
        (self.output / "planned_inputs.json").write_bytes(canonical({
            "actual_problems": FIXTURES, "tasks": tasks,
            "control_algorithm": "flip one bit per update, private MSVC-compatible RNG",
            "note": "fault actions are test-only inputs, not inferred root causes"}))
        self.event_stream = (self.output / "events.jsonl").open("xb")
        self.assignment_stream = (self.output / "assignments.jsonl").open("xb")
        self.events, self.ready, self.stopped = [], {}, {}
        self.current = {i: None for i in range(workers)}
        self.checkpoints, self.closed_connections, self.closed_gates = {}, set(), set()
        self.processes, self.connections, self.gates = [], [], []
        self.exits = {}
        self.quarantined = set()
        self.expected_retirement_pids = set()  # Competing TEST policies only.
        self.stopping, self.closing, self.stop_reason = False, False, None
        self.result_file_reads = 0
        context = mp.get_context("spawn")
        children, child_gates = [], []
        for _ in range(workers):
            parent, child = context.Pipe(duplex=True)
            gate, child_gate = socket.socketpair()
            self.connections.append(parent)
            children.append(child)
            self.gates.append(gate)
            child_gates.append(child_gate)
        if mode == "threads":
            p = context.Process(target=thread_host, args=(children, child_gates))
            p.start()
            self.processes.append(p)
        else:
            for i in range(workers):
                p = context.Process(target=process_host, args=(i, children[i], child_gates[i]))
                p.start()
                self.processes.append(p)
        for handle in children + child_gates:
            handle.close()
        self.until(lambda: len(self.ready) == workers)

    def log(self, kind, **data):
        entry = {"sequence": len(self.events), "kind": kind, **data}
        self.events.append(entry)
        self.event_stream.write(canonical(entry))
        self.event_stream.flush()
        os.fsync(self.event_stream.fileno())
        return entry

    def request_stop(self, reason):
        if not self.stopping:
            self.stopping, self.stop_reason = True, reason
            self.log("whole_experiment_stop_requested", reason=reason)

    def on_message(self, lane, message):
        if message["lane"] != lane:
            raise AssertionError("foreign lane message")
        kind = message["kind"]
        self.log("worker_message", lane=lane, message=message)
        if kind == "harness_error":
            raise AssertionError(message["traceback"])
        if kind == "ready":
            self.ready[lane] = message
            return
        if kind == "stopped":
            self.stopped[lane] = message
            return
        task_id = message["task_id"]
        if task_id != self.current[lane]:
            raise AssertionError("message does not match assigned task")
        record = self.records[task_id]
        record["facts"].append(kind)
        if kind == "received":
            return
        if kind == "cpp_returned":
            if record["facts"] != ["received", "cpp_returned"]:
                raise AssertionError("incorrect C++ return phase")
            return
        if kind not in ("saved", "save_error", "algorithm_error"):
            raise AssertionError("unknown test worker message")
        if record["final_status"] is not None:
            raise AssertionError("duplicate terminal report")
        record["final_status"] = {"saved": "delivered", "save_error": "save_error",
                                  "algorithm_error": "algorithm_error"}[kind]
        record["final_report"] = message
        self.current[lane] = None
        if kind == "save_error" and not message["cleanup"]["success"]:
            self.quarantined.add(lane)
        if kind == "algorithm_error":
            self.request_stop({"kind": "reported_algorithm_error", "task_id": task_id})

    def drain_lane(self, lane):
        if lane in self.closed_connections:
            return
        connection = self.connections[lane]
        while connection.poll(0):
            try:
                message = connection.recv()
            except (EOFError, OSError) as error:
                self.closed_connections.add(lane)
                self.log("connection_closed", lane=lane, exception_type=type(error).__name__,
                         message=str(error), errno=getattr(error, "errno", None))
                return
            self.on_message(lane, message)

    def on_exit(self, process):
        if process.pid in self.exits:
            return
        process.join(timeout=0)
        code = process.exitcode
        if code is None:
            raise AssertionError("ready process sentinel has no exitcode")
        # Log that exit was observed, but defer task classification until all
        # already-delivered normal reports from that process have been drained.
        self.log("process_exit_observed", pid=process.pid, exitcode=code)
        lanes = [lane for lane, info in self.ready.items() if info["pid"] == process.pid]
        for lane in lanes:
            self.drain_lane(lane)
        self.exits[process.pid] = {"pid": process.pid, "exitcode": code,
            "signal": signal.Signals(-code).name if code < 0 else None,
            "unconfirmed_task_inputs": [self.records[self.current[lane]]["input"]
                                         for lane in lanes if self.current[lane] is not None],
            "root_cause": "not_determined"}
        self.log("process_exit_recorded_after_drain", **self.exits[process.pid])
        if not self.closing and process.pid not in self.expected_retirement_pids:
            # Prototype safety disposition for a lost execution host. This is
            # not a claim that the exit proves a particular algorithm root cause.
            self.request_stop({"kind": "unexpected_execution_process_exit", "pid": process.pid,
                               "exitcode": code, "root_cause": "not_determined"})

    def pump(self):
        watches = [c for lane, c in enumerate(self.connections) if lane not in self.closed_connections]
        watches += [g for lane, g in enumerate(self.gates) if lane not in self.closed_gates]
        watches += [p.sentinel for p in self.processes if p.pid not in self.exits]
        if not watches:
            raise AssertionError("no remaining test event source")
        ready = wait(watches, timeout=TEST_WATCHDOG)
        if not ready:
            raise TimeoutError("test-only watchdog: expected event not received")
        for lane, connection in enumerate(self.connections):
            if connection in ready:
                self.drain_lane(lane)
        for lane, gate in enumerate(self.gates):
            if gate in ready:
                token = gate.recv(1)
                if not token:
                    self.closed_gates.add(lane)
                    continue
                if lane in self.checkpoints:
                    raise AssertionError("duplicate unreleased checkpoint")
                self.checkpoints[lane] = token[0]
                self.log("native_test_checkpoint", lane=lane, phase=token[0],
                         task_id=self.current[lane])
        for process in self.processes:
            if process.sentinel in ready:
                self.on_exit(process)

    def until(self, predicate):
        while not predicate():
            self.pump()

    def assign(self, lane, task):
        if lane in self.quarantined or self.ready[lane]["pid"] in self.exits:
            raise RuntimeError("dispatch forbidden to quarantined/exited execution lane")
        if self.stopping or self.closing:
            raise RuntimeError("dispatch forbidden after experiment stop")
        if self.current[lane] is not None:
            raise AssertionError("lane is occupied")
        record = self.records[task["task_id"]]
        if record.get("assignment") is not None:
            raise AssertionError("no automatic retry in this prototype")
        assignment = {"lane": lane, "pid": self.ready[lane]["pid"], "actual_input": task}
        record["assignment"] = assignment
        self.assignment_stream.write(canonical(assignment))
        self.assignment_stream.flush()
        os.fsync(self.assignment_stream.fileno())
        self.log("task_assigned", task_id=task["task_id"], lane=lane, pid=assignment["pid"])
        self.current[lane] = task["task_id"]
        self.connections[lane].send({"op": "run", "task": task})

    def wait_checkpoint(self, lanes, phase):
        self.until(lambda: all(self.checkpoints.get(lane) == phase for lane in lanes))

    def release(self, lanes, phase):
        for lane in lanes:
            if self.checkpoints.pop(lane) != phase:
                raise AssertionError("incorrect checkpoint release")
            self.gates[lane].sendall(bytes([phase + 16]))

    def run_single(self, lane, task):
        self.assign(lane, task)
        for phase in (0, 1, 2):
            self.wait_checkpoint([lane], phase)
            self.release([lane], phase)
        self.until(lambda: self.records[task["task_id"]]["final_status"] is not None)

    def observe_exit_before_draining_messages(self, lane):
        process = next(p for p in self.processes if p.pid == self.ready[lane]["pid"])
        if not wait([process.sentinel], timeout=TEST_WATCHDOG):
            raise TimeoutError("test-only watchdog: expected deliberate host exit")
        # Deliberately observe the exit FIRST to exercise the difficult order.
        self.on_exit(process)

    def stop_all(self):
        if not self.stopping:
            raise AssertionError("whole-run stop requires an observed reason")
        # Stop all owned hosts, not just the host that reported the error.
        for process in self.processes:
            if process.is_alive():
                self.log("terminate_owned_execution_process", pid=process.pid)
                process.terminate()
        for process in self.processes:
            process.join(timeout=2)
            if process.is_alive():
                self.log("kill_owned_execution_process", pid=process.pid)
                process.kill()
                process.join(timeout=2)
            if process.is_alive():
                raise AssertionError("owned test process survived cleanup")
            self.on_exit(process)
        self.finalize()

    def graceful_close(self):
        if self.stopping or any(task is not None for task in self.current.values()):
            raise AssertionError("cannot normally close active/stopping execution")
        self.closing = True
        for connection in self.connections:
            connection.send({"op": "stop"})
        self.until(lambda: len(self.stopped) == self.workers)
        for process in self.processes:
            process.join(timeout=TEST_WATCHDOG)
            if process.is_alive() or process.exitcode != 0:
                raise AssertionError("unexpected normal shutdown")
            self.on_exit(process)
        self.finalize()

    def finalize(self):
        for task_id, record in self.records.items():
            if record["final_status"] is not None:
                continue
            if "assignment" not in record:
                record["final_status"] = "not_dispatched"
            else:
                record["final_status"] = "delivery_unconfirmed"
                record["relation"] = "execution_ended_without_complete_report"
                record["root_cause"] = "not_determined"
        self.log("controller_finalized", statuses={key: value["final_status"] for key, value in self.records.items()})
        self.report = {"controller_pid": os.getpid(), "controller_survived": True,
            "mode": self.mode, "workers": self.workers, "stop_requested": self.stopping,
            "stop_reason": self.stop_reason, "records": self.records,
            "process_exits": list(self.exits.values()), "events": self.events,
            "ready": self.ready, "stopped": self.stopped, "result_file_reads_by_controller": self.result_file_reads,
            "automatic_retries": 0, "all_owned_execution_processes_exited":
                all(not process.is_alive() for process in self.processes)}
        (self.output / "controller_report.json").write_bytes(canonical(self.report))
        self.close_handles()

    def close_handles(self):
        self.assignment_stream.close()
        self.event_stream.close()
        for handle in self.connections + self.gates:
            handle.close()

    def emergency_test_cleanup(self):
        # Harness bug cleanup, not a production task policy or claimed pass.
        for process in self.processes:
            if process.is_alive():
                process.kill()
        for process in self.processes:
            process.join(timeout=2)
        self.close_handles()
