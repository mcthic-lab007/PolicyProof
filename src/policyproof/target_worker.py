"""Run a target in a separate worker process with a per-call timeout.

The verifier never runs an isolated target in its own process. It starts
``python -m src.policyproof.target_worker MODULE:FUNCTION`` and exchanges one
JSON object per line:

    parent -> worker  {"id": 7, "amount": "40.00", "has_service_date": true, "case": "point-40.00-dated"}
    worker -> parent  {"ready": true}                                 (once, after import)
                      {"id": 7, "decision": "APPROVE"}                (a string result)
                      {"id": 7, "returned": "None"}                   (a non-string result)
                      {"id": 7, "raised": "RuntimeError: ..."}        (any exception, SystemExit too)

Amounts travel as decimal strings and nothing is unpickled. The worker
points sys.stdout at stderr while the target runs, so a target that prints
cannot corrupt the protocol; stderr is discarded.

What this gives, and what it does not:
  - Process isolation with a timeout: a call that does not answer in time
    is abandoned and the worker is killed and restarted, so the verifier
    cannot hang. A crash, os._exit() or garbage on the protocol stream ends
    the worker the same way.
  - It is NOT a security sandbox. The worker runs with the user's
    permissions and can read files, use the network and spawn processes.
    Only trusted, locally selected code should be run. The Muse API key
    environment variable is removed from the worker's environment.

Failure kinds reported on an Outcome (see verification.Outcome):
  timeout        no answer within the per-call timeout; worker killed
  worker_crash   the worker exited, or wrote malformed protocol output
  worker_startup the target could not be imported or the worker did not
                 start; the worker is not restarted, so this costs one start
  not_run        the run's total target-time limit was reached; skipped
A user's Ctrl+C (KeyboardInterrupt in the verifier) stops the run and kills
the worker. A target that itself raises KeyboardInterrupt ends its worker,
which is reported as worker_crash.
"""

import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
from decimal import Decimal
from pathlib import Path
from typing import Any


SPEC = re.compile(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*:[A-Za-z_]\w*")
ROOT = Path(__file__).resolve().parents[2]
STARTUP_TIMEOUT = 20.0
MAX_TIMEOUT = 60.0
MAX_TIME_LIMIT = 3600.0
WAIT_SLICE = 0.05  # keep waits short so Ctrl+C is delivered promptly on every platform
REMOVED_ENV = ("META_MUSE_API_KEY",)


class TargetWorker:
    """Parent side: one live worker process at a time, restarted after a
    timeout or crash. ``call`` returns (decision, error, failure)."""

    def __init__(self, spec: str, *, timeout: float, time_limit: float):
        if not isinstance(spec, str) or not SPEC.fullmatch(spec):
            raise ValueError(f"target import path must look like 'package.module:function', got {spec!r}")
        if not 0 < timeout <= MAX_TIMEOUT:
            raise ValueError(f"timeout must be in (0, {MAX_TIMEOUT}] seconds")
        if not 0 < time_limit <= MAX_TIME_LIMIT:
            raise ValueError(f"time limit must be in (0, {MAX_TIME_LIMIT}] seconds")
        self.spec = spec
        self.timeout = float(timeout)
        self.time_limit = float(time_limit)
        self._process: subprocess.Popen | None = None
        self._lines: queue.Queue | None = None
        self._deadline: float | None = None
        self._startup_error: str | None = None
        self._next_id = 0
        self.stats = {"calls": 0, "starts": 0, "timeouts": 0, "crashes": 0, "not_run": 0}
        self.pids: list[int] = []

    def __enter__(self) -> "TargetWorker":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def call(self, amount: Decimal, has_service_date: bool, case_id: str) -> tuple[str | None, str | None, str | None]:
        if self._deadline is None:
            self._deadline = time.monotonic() + self.time_limit
        if self._startup_error is not None:
            return None, self._startup_error, "worker_startup"
        if time.monotonic() >= self._deadline:
            self.stats["not_run"] += 1
            return None, f"not run: the target time limit of {self.time_limit:g} s was reached", "not_run"
        if self._process is None and not self._start():
            return None, self._startup_error, "worker_startup"

        self.stats["calls"] += 1
        self._next_id += 1
        request = {"id": self._next_id, "amount": str(amount),
                   "has_service_date": bool(has_service_date), "case": str(case_id)}
        try:
            self._process.stdin.write(json.dumps(request) + "\n")
            self._process.stdin.flush()
        except OSError:
            return self._crashed("the worker stopped accepting requests")

        reply = self._wait(time.monotonic() + self.timeout)
        if reply is _TIMED_OUT:
            self.stats["timeouts"] += 1
            self._kill()
            return None, f"timed out after {self.timeout:g} s; the worker process was killed", "timeout"
        if reply is None:
            return self._crashed(f"the worker exited (code {self._exit_code()})")
        try:
            message = json.loads(reply)
        except ValueError:
            return self._crashed("the worker wrote malformed protocol output")
        if not isinstance(message, dict) or message.get("id") != self._next_id:
            return self._crashed("the worker answered out of protocol")
        if isinstance(message.get("decision"), str):
            return message["decision"], None, None
        if isinstance(message.get("raised"), str):
            return None, f"raised {message['raised'][:200]}", "exception"
        if isinstance(message.get("returned"), str):
            return None, f"returned {message['returned'][:80]}, which is not a decision", "invalid_output"
        return self._crashed("the worker answered out of protocol")

    def close(self) -> None:
        self._kill()

    # ------------------------------------------------------------- internal

    def _start(self) -> bool:
        env = {k: v for k, v in os.environ.items() if k not in REMOVED_ENV}
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        self.stats["starts"] += 1
        try:
            process = subprocess.Popen(
                [sys.executable, "-B", "-m", "src.policyproof.target_worker", self.spec],
                cwd=ROOT, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, text=True, encoding="utf-8", bufsize=1,
            )
        except OSError as exc:
            self._startup_error = f"the target worker could not be started: {exc}"
            return False
        self._process = process
        self.pids.append(process.pid)
        self._lines = queue.Queue()
        threading.Thread(target=_pump, args=(process.stdout, self._lines), daemon=True).start()

        reply = self._wait(time.monotonic() + STARTUP_TIMEOUT)
        message = None
        if isinstance(reply, str):
            try:
                message = json.loads(reply)
            except ValueError:
                message = None
        if isinstance(message, dict) and message.get("ready") is True:
            return True
        detail = message.get("startup_error") if isinstance(message, dict) else None
        self._startup_error = "the target could not be started: " + (
            str(detail)[:300] if detail else
            "no answer within the startup timeout" if reply is _TIMED_OUT else
            f"the worker exited (code {self._exit_code()})"
        )
        self._kill()
        return False

    def _wait(self, deadline: float):
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return _TIMED_OUT
            try:
                return self._lines.get(timeout=min(WAIT_SLICE, remaining))
            except queue.Empty:
                continue

    def _crashed(self, reason: str):
        self.stats["crashes"] += 1
        self._kill()
        return None, reason, "worker_crash"

    def _exit_code(self):
        if self._process is None:
            return None
        try:
            return self._process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            return None

    def _kill(self) -> None:
        process, self._process = self._process, None
        if process is None:
            return
        if process.poll() is None:
            process.kill()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:  # pragma: no cover - the OS did not reap it in time
            pass
        for stream in (process.stdin, process.stdout):
            try:
                stream.close()
            except OSError:
                pass


_TIMED_OUT = object()


def _pump(stream, lines: queue.Queue) -> None:
    """Move the worker's output lines into a queue; None marks the end."""
    try:
        for line in stream:
            lines.put(line)
    except (OSError, ValueError):
        pass
    lines.put(None)


# ------------------------------------------------------------- worker side


def _serve(spec: str) -> int:
    protocol = sys.stdout
    sys.stdout = sys.stderr  # the target's prints must not reach the protocol stream

    def send(message: dict) -> None:
        protocol.write(json.dumps(message) + "\n")
        protocol.flush()

    try:
        if not SPEC.fullmatch(spec):
            raise ValueError(f"invalid target import path {spec!r}")
        import importlib

        module_name, function_name = spec.split(":")
        function = getattr(importlib.import_module(module_name), function_name)
        if not callable(function):
            raise TypeError(f"{spec} is not callable")
        from src.policyproof.models import TestCase
    except BaseException as exc:  # noqa: BLE001 - report every startup failure to the parent
        send({"startup_error": f"{type(exc).__name__}: {exc}"})
        return 3
    send({"ready": True})

    for line in sys.stdin:
        request = json.loads(line)
        case = TestCase(Decimal(request["amount"]), request["has_service_date"] is True, str(request["case"]))
        try:
            value = function(case)
        except KeyboardInterrupt:
            return 130
        except BaseException as exc:  # noqa: BLE001 - SystemExit included: report, keep serving
            send({"id": request["id"], "raised": f"{type(exc).__name__}: {str(exc)[:200]}"})
            continue
        if isinstance(value, str) and len(value) <= 100:
            send({"id": request["id"], "decision": value})
        else:
            send({"id": request["id"], "returned": repr(value)[:80]})
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: python -m src.policyproof.target_worker package.module:function", file=sys.stderr)
        sys.exit(2)
    sys.exit(_serve(sys.argv[1]))
