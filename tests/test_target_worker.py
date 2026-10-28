import contextlib
import io
import json
import os
import subprocess
import sys
import time
import unittest
from decimal import Decimal
from pathlib import Path
from unittest import mock

from src.policyproof import target_worker, verification
from src.policyproof.muse_client import replay_proposal
from src.policyproof.target_worker import MAX_TIMEOUT, TargetWorker
from src.policyproof.verification import Implementation, _registry, verify


ROOT = Path(__file__).resolve().parent.parent
POLICY_PATH = ROOT / "examples" / "democo_meal_policy.txt"
POLICY_TEXT = POLICY_PATH.read_text(encoding="utf-8")
FIXTURE_PATH = ROOT / "tests" / "fixtures" / "muse_democo_meal_response.json"
FIXTURE = replay_proposal(FIXTURE_PATH, POLICY_TEXT)
REFERENCES, TARGETS = _registry()
REFERENCE = REFERENCES["democo-meal"]
D = Decimal


def pid_alive(pid):
    """Ask the operating system, not our own bookkeeping, whether a PID exists."""
    if sys.platform == "win32":
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH", "/FO", "CSV"],
                             capture_output=True, text=True).stdout
        return f'"{pid}"' in out
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def worker(name, timeout=0.5, time_limit=60.0, module="tests.isolation_targets"):
    return TargetWorker(f"{module}:{name}", timeout=timeout, time_limit=time_limit)


def isolated(name, module="tests.isolation_targets"):
    return Implementation(name, "isolation test target", lambda case: None, f"{module}:{name}")


class WorkerProtocolTests(unittest.TestCase):
    def test_decisions_round_trip(self):
        with worker("slow") as w:
            self.assertEqual(w.call(D("40.00"), True, "a"), ("APPROVE", None, None))
            self.assertEqual(w.call(D("40.01"), True, "b"), ("REJECT", None, None))
            self.assertEqual(w.call(D("40.01"), False, "c"), ("REVIEW", None, None))
            self.assertEqual(w.stats["starts"], 1)

    def test_timeout_is_bounded_and_the_worker_is_killed(self):
        with worker("hangs_at_forty", timeout=0.5) as w:
            w.call(D("1.00"), True, "warm-up")  # exclude start-up from the measurement
            first_pid = w.pids[-1]
            started = time.monotonic()
            decision, error, failure = w.call(D("40.00"), True, "hang")
            elapsed = time.monotonic() - started
            self.assertEqual((decision, failure), (None, "timeout"))
            self.assertIn("timed out after 0.5 s", error)
            self.assertGreaterEqual(elapsed, 0.5)
            self.assertLess(elapsed, 2.0)
            self.assertFalse(pid_alive(first_pid))
            # The next call gets a fresh worker and a real answer.
            self.assertEqual(w.call(D("39.99"), True, "after"), ("APPROVE", None, None))
            self.assertEqual((w.stats["starts"], w.stats["timeouts"]), (2, 1))
        self.assertFalse(any(pid_alive(pid) for pid in w.pids))

    def test_crash_is_reported_and_the_worker_restarts(self):
        with worker("crashes_at_forty") as w:
            decision, error, failure = w.call(D("40.00"), True, "crash")
            self.assertEqual((decision, failure), (None, "worker_crash"))
            self.assertIn("exited (code 7)", error)
            self.assertEqual(w.call(D("40.01"), True, "after"), ("REJECT", None, None))
            self.assertEqual(w.stats["starts"], 2)

    def test_system_exit_and_exceptions_are_answers_not_crashes(self):
        for name, fragment in [("exits", "raised SystemExit: 0"), ("raises", "raised RuntimeError: ledger offline")]:
            with self.subTest(target=name), worker(name) as w:
                for _ in range(2):
                    self.assertEqual(w.call(D("1.00"), True, "x"), (None, fragment, "exception"))
                self.assertEqual(w.stats["starts"], 1)

    def test_non_string_results(self):
        with worker("returns_none") as w:
            self.assertEqual(w.call(D("1.00"), True, "x")[2], "invalid_output")
        with worker("returns_lowercase") as w:
            self.assertEqual(w.call(D("1.00"), True, "x"), ("approve", None, None))

    def test_printing_cannot_corrupt_the_protocol(self):
        with worker("prints_noise") as w:
            self.assertEqual(w.call(D("1.00"), True, "x"), ("APPROVE", None, None))

    def test_writing_to_the_protocol_stream_is_a_crash(self):
        with worker("corrupts_protocol") as w:
            decision, error, failure = w.call(D("1.00"), True, "x")
            self.assertEqual(failure, "worker_crash")
            self.assertIn("malformed protocol output", error)

    def test_target_keyboard_interrupt_ends_only_the_worker(self):
        with worker("raises_keyboard_interrupt") as w:
            self.assertEqual(w.call(D("1.00"), True, "x")[2], "worker_crash")

    def test_startup_failures_are_reported_once(self):
        cases = [
            ("decide", "tests.isolation_broken", "RuntimeError: this target cannot be imported"),
            ("missing", "tests.isolation_targets", "AttributeError"),
            ("not_callable", "tests.isolation_targets", "is not callable"),
            ("anything", "tests.no_such_module", "ModuleNotFoundError"),
        ]
        for name, module, fragment in cases:
            with self.subTest(target=f"{module}:{name}"), worker(name, module=module) as w:
                for _ in range(3):
                    decision, error, failure = w.call(D("1.00"), True, "x")
                    self.assertEqual((decision, failure), (None, "worker_startup"))
                    self.assertIn(fragment, error)
                self.assertEqual(w.stats["starts"], 1)

    def test_total_time_limit_bounds_a_target_that_always_hangs(self):
        started = time.monotonic()
        with worker("hangs_always", timeout=0.3, time_limit=1.0) as w:
            failures = [w.call(D("1.00"), True, str(i))[2] for i in range(20)]
        elapsed = time.monotonic() - started
        self.assertIn("timeout", failures)
        self.assertEqual(failures[-1], "not_run")
        self.assertEqual(w.stats["not_run"], failures.count("not_run"))
        self.assertLess(elapsed, 1.0 + 0.3 + 3.0)  # limit + one call + start-up slack
        self.assertFalse(any(pid_alive(pid) for pid in w.pids))

    def test_api_key_is_not_passed_to_the_worker(self):
        with mock.patch.dict(os.environ, {"META_MUSE_API_KEY": "test-key-NOT-REAL"}), worker("reports_env") as w:
            self.assertEqual(w.call(D("1.00"), True, "x")[0], "APPROVE")

    def test_invalid_configuration(self):
        for spec in ["", "module", "a.b", "a:b:c", "../x:y", "os.system('x'):y", "a b:c", None]:
            with self.subTest(spec=spec), self.assertRaises(ValueError):
                TargetWorker(spec, timeout=1, time_limit=1)
        for timeout in [0, -1, MAX_TIMEOUT + 1]:
            with self.subTest(timeout=timeout), self.assertRaises(ValueError):
                TargetWorker("a.b:c", timeout=timeout, time_limit=1)

    def test_user_interrupt_propagates_and_kills_the_worker(self):
        real_wait = TargetWorker._wait
        calls = []

        def interrupt_after_start(self, deadline):
            calls.append(1)
            if len(calls) == 2:  # the first wait is the start-up handshake
                raise KeyboardInterrupt
            return real_wait(self, deadline)

        w = worker("slow")
        with mock.patch.object(TargetWorker, "_wait", interrupt_after_start):
            with self.assertRaises(KeyboardInterrupt):
                w.call(D("1.00"), True, "x")
        pid = w.pids[-1]
        w.close()
        self.assertFalse(pid_alive(pid))


class IsolatedVerificationTests(unittest.TestCase):
    def run_isolated(self, target, **kwargs):
        kwargs.setdefault("target_timeout", 0.5)
        return verify(FIXTURE.document, POLICY_TEXT, proposal=FIXTURE, reference=REFERENCE,
                      target=target, **kwargs)

    def test_hanging_target_gives_a_bounded_valid_report(self):
        started = time.monotonic()
        result = self.run_isolated(isolated("hangs_at_forty"), search_budget=200)
        elapsed = time.monotonic() - started
        self.assertFalse([c for c in result.codes() if c.startswith("TARGET_DISCREPANCY")])
        [unfinished] = self.unfinished(result)
        self.assertEqual(unfinished.points, ("point-40.00-dated",))
        self.assertIn("timed out after 0.5 s", unfinished.details["errors"]["point-40.00-dated"])
        point = next(p for p in result.report["points"] if p["id"] == "point-40.00-dated")
        self.assertEqual(point["target"]["failure"], "timeout")
        execution = result.report["target_execution"]
        self.assertEqual((execution["mode"], execution["timeouts"]), ("isolated-worker-process", 1))
        self.assertIn("not a security sandbox", execution["note"])
        limitations = result.report["target_search"]["limitations"]
        self.assertFalse([text for text in limitations if "run in this process" in text])
        self.assertTrue([text for text in limitations if "target_execution" in text])
        json.loads(result.to_json())
        self.assertLess(elapsed, 15)

    def test_always_hanging_target_hits_the_time_limit_without_false_findings(self):
        started = time.monotonic()
        result = self.run_isolated(isolated("hangs_always"), target_timeout=0.3,
                                   target_time_limit=2.0, search_budget=100)
        elapsed = time.monotonic() - started
        self.assertLess(elapsed, 2.0 + 0.3 + 4.0)
        not_evaluated = [f for f in result.findings
                         if f.code == "UNSUPPORTED" and "not evaluated" in f.summary]
        self.assertEqual(len(not_evaluated), 1)
        # Neither timed-out nor skipped calls are judgements of the target.
        timed_out = [p for p in result.report["points"] if (p["target"] or {}).get("failure") == "timeout"]
        skipped = [p for p in result.report["points"] if (p["target"] or {}).get("failure") == "not_run"]
        self.assertTrue(timed_out and skipped)
        self.assertEqual(set(not_evaluated[0].points), {p["id"] for p in timed_out + skipped})
        self.assertFalse([c for c in result.codes() if c.startswith("TARGET_DISCREPANCY")])
        self.assertFalse(any(f.details.get("kind") == "range" for f in result.findings))
        self.assertNotEqual(result.level, "L3")
        self.assertIn("not evaluated", result.report["verification"]["criteria"]["L3"]["detail"])

    def test_time_limit_during_search_is_not_reported_as_agreement(self):
        # Regression (benchmark corpus v1, time-limit-exhausted): a correct
        # but slow target whose search was cut short reached L3 and exit 0
        # while most search calls were skipped.
        result = self.run_isolated(isolated("slow"), target_timeout=2.0, target_time_limit=2.0)
        search = result.report["target_search"]
        self.assertGreater(search["unjudged_evaluations"], 0)
        unjudged = [f for f in result.findings if f.code == "UNSUPPORTED" and "could not be judged" in f.summary]
        self.assertEqual(len(unjudged), 1)
        self.assertIn("target not_run", unjudged[0].details["reasons"])
        self.assertNotEqual(result.level, "L3")
        self.assertEqual(result.report["verification"]["result"]["exit_code"], 3)
        self.assertFalse([c for c in result.codes() if c.startswith("TARGET_DISCREPANCY")])

    def test_target_that_cannot_start_is_not_reported_as_wrong(self):
        result = self.run_isolated(isolated("decide", module="tests.isolation_broken"))
        codes = result.codes()
        self.assertIn("UNSUPPORTED", codes)
        self.assertFalse([c for c in codes if c.startswith("TARGET_DISCREPANCY")])
        self.assertEqual(result.report["target_execution"]["worker_starts"], 1)
        self.assertEqual(result.level, "L2")

    def test_crashing_target_is_an_unfinished_call_at_that_point(self):
        result = self.run_isolated(isolated("crashes_at_forty"), search_budget=100)
        self.assertFalse([c for c in result.codes() if c.startswith("TARGET_DISCREPANCY")])
        [unfinished] = self.unfinished(result)
        self.assertEqual(unfinished.points, ("point-40.00-dated",))
        self.assertEqual(unfinished.details["failures"], {"worker_crash": 1})
        self.assertIn("exited (code 7)", unfinished.details["errors"]["point-40.00-dated"])
        self.assertEqual(result.report["verification"]["result"]["exit_code"], 3)

    def unfinished(self, result):
        return [f for f in result.findings if f.code == "UNSUPPORTED" and "not evaluated" in f.summary]

    def test_slow_correct_target_is_not_accused(self):
        # Regression (benchmark corpus v2, slow-correct-at-threshold): a call
        # that outlasted the timeout was a confirmed discrepancy, so a correct
        # target slower than the timeout was accused of a wrong decision.
        result = self.run_isolated(isolated("slow_at_forty"), search_budget=50)
        self.assertFalse([c for c in result.codes() if c.startswith("TARGET_DISCREPANCY")])
        [finding] = self.unfinished(result)
        self.assertEqual(finding.points, ("point-40.00-dated",))
        self.assertEqual(finding.details["failures"], {"timeout": 1})
        self.assertIn("timed out after 0.5 s", finding.summary)
        self.assertIn("not evidence", finding.summary)
        self.assertNotEqual(result.level, "L3")
        self.assertIn("not evaluated", result.report["verification"]["criteria"]["L3"]["detail"])
        self.assertEqual(result.report["verification"]["result"]["exit_code"], 3)

    def test_a_long_enough_timeout_lets_the_slow_target_reach_l3(self):
        result = self.run_isolated(isolated("slow_at_forty"), target_timeout=2.0, search_budget=50)
        self.assertEqual((result.level, result.report["verification"]["result"]["exit_code"]), ("L3", 0))

    def test_completed_discrepancies_stay_confirmed_next_to_a_timeout(self):
        result = self.run_isolated(isolated("wrong_below_slow_at_forty"), search_budget=50)
        confirmed = [f for f in result.findings if f.code == "TARGET_DISCREPANCY_CONFIRMED"]
        self.assertEqual([f.points for f in confirmed if f.details.get("kind") != "range"],
                         [("point-39.99-dated",)])
        self.assertEqual(self.unfinished(result)[0].points, ("point-40.00-dated",))
        # The unfinished $40.00 call cannot verify the edge between $39.99 and $40.01.
        [found] = [f for f in confirmed if f.details.get("kind") == "range"]
        self.assertEqual((found.details["end"], found.details["agrees_above"]), ("39.99", "40.01"))
        self.assertFalse(found.details["upper_edge_verified"])
        self.assertEqual(result.report["verification"]["result"]["exit_code"], 3)

    def test_search_timeouts_are_unjudged_not_ranges(self):
        result = self.run_isolated(isolated("hangs_at_a_thousand"), search_budget=100)
        self.assertFalse([c for c in result.codes() if c.startswith("TARGET_DISCREPANCY")])
        [unjudged] = [f for f in result.findings if f.code == "UNSUPPORTED" and "could not be judged" in f.summary]
        self.assertEqual(unjudged.details["reasons"], {"target timeout": 1})
        self.assertNotEqual(result.level, "L3")

    def test_isolated_and_in_process_runs_agree(self):
        for name in ("democo-buggy", "democo-fixed", "democo-loophole"):
            with self.subTest(target=name):
                isolated_report = self.run_isolated(TARGETS[name], target_timeout=2.0).report
                in_process_report = self.run_isolated(TARGETS[name], target_timeout=None).report
                for report in (isolated_report, in_process_report):
                    del report["target_execution"]
                self.assertEqual(isolated_report, in_process_report)

    def test_search_budget_is_respected_with_isolation(self):
        for budget in (5, 50):
            with self.subTest(budget=budget):
                result = self.run_isolated(TARGETS["democo-loophole"], target_timeout=2.0, search_budget=budget)
                calls = result.report["target_execution"]["calls"]
                self.assertLessEqual(calls - len(result.points), budget)
                self.assertEqual(calls - len(result.points), result.report["target_search"]["target_calls"])

    def test_isolation_needs_an_import_path(self):
        with self.assertRaises(ValueError):
            verify(FIXTURE.document, POLICY_TEXT, target=Implementation("x", "", lambda c: "APPROVE"),
                   target_timeout=1.0)

    def test_user_interrupt_during_verification_kills_the_worker(self):
        pids = []
        real_start = TargetWorker._start

        def start_and_record(self):
            ok = real_start(self)
            pids.extend(self.pids)
            return ok

        real_call = TargetWorker.call
        count = []

        def interrupt_on_fifth_call(self, *args):
            count.append(1)
            if len(count) == 5:
                raise KeyboardInterrupt
            return real_call(self, *args)

        with mock.patch.object(TargetWorker, "_start", start_and_record), \
                mock.patch.object(TargetWorker, "call", interrupt_on_fifth_call):
            with self.assertRaises(KeyboardInterrupt):
                self.run_isolated(TARGETS["democo-fixed"], target_timeout=2.0)
        self.assertTrue(pids)
        self.assertFalse(any(pid_alive(pid) for pid in pids))


class CommandLineTests(unittest.TestCase):
    def run_main(self, *extra):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = verification.main([str(POLICY_PATH), "--replay", str(FIXTURE_PATH),
                                      "--reference", "democo-meal", *extra])
        return code, out.getvalue()

    def test_cli_isolates_by_default_and_keeps_outcomes(self):
        for target, code, level in [("democo-buggy", 3, "L2"), ("democo-fixed", 0, "L3"), ("democo-loophole", 3, "L2")]:
            with self.subTest(target=target):
                exit_code, out = self.run_main("--target", target)
                self.assertEqual(exit_code, code)
                self.assertIn(f"Verification level: {level}", out)
                self.assertIn("Target execution: isolated worker process, 2 s per call", out)
                self.assertIn("not a security sandbox", out)

    def test_cli_in_process_mode(self):
        exit_code, out = self.run_main("--target", "democo-buggy", "--target-timeout", "0")
        self.assertEqual(exit_code, 3)
        self.assertIn("Target execution: in-process, no timeout.", out)

    def test_cli_rejects_bad_timeouts(self):
        for args in (["--target-timeout", "-1"], ["--target-timeout", str(MAX_TIMEOUT + 1)],
                     ["--target-time-limit", "0"], ["--target-timeout", "soon"]):
            with self.subTest(args=args), self.assertRaises(SystemExit), \
                    contextlib.redirect_stderr(io.StringIO()):
                verification.main([str(POLICY_PATH), "--replay", str(FIXTURE_PATH), *args])


if __name__ == "__main__":
    unittest.main()
