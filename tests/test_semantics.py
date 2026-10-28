"""Confirmation semantics and the run verdict / CLI exit codes."""

import contextlib
import copy
import io
import json
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from src.policyproof import verification
from src.policyproof.muse_client import replay_proposal
from src.policyproof.reference import evaluate_meal_claim as reference_engine
from src.policyproof.schema import parse_rule_document
from src.policyproof.verification import Finding, Implementation, _registry, verdict, verify


ROOT = Path(__file__).resolve().parent.parent
POLICY_PATH = ROOT / "examples" / "democo_meal_policy.txt"
POLICY_TEXT = POLICY_PATH.read_text(encoding="utf-8")
FIXTURE_PATH = ROOT / "tests" / "fixtures" / "muse_democo_meal_response.json"
FIXTURE = replay_proposal(FIXTURE_PATH, POLICY_TEXT)
RULES = json.loads((ROOT / "examples" / "democo_meal_rules.json").read_text(encoding="utf-8"))
REFERENCES, TARGETS = _registry()
REFERENCE = REFERENCES["democo-meal"]
D = Decimal


def validated(mutate):
    payload = copy.deepcopy(RULES)
    mutate(payload)
    return parse_rule_document(json.dumps(payload), POLICY_TEXT)


def add_case(payload, case_id, amount, dated, expected):
    payload["test_cases"].append({"id": case_id, "inputs": {"amount": amount, "has_service_date": dated},
                                  "expected_decision": expected})


def target(decide):
    return Implementation("t", "test target", decide)


def findings(result, code, point=None):
    return [f for f in result.findings if f.code == code and (point is None or point in f.points)]


def check(document, decide=None, reference=REFERENCE, **kwargs):
    return verify(document, POLICY_TEXT, reference=reference,
                  target=target(decide) if decide else None, **kwargs)


class ConfirmationSemanticsTests(unittest.TestCase):
    def test_shared_misreading_against_a_correct_target_is_disputed_not_confirmed(self):
        """The reference and the rules share a misreading ("< $40.00"); the
        proposal's own test case at $40.00 expects APPROVE, which agrees with
        the correct target. That must not be reported as a confirmed bug."""
        def misread(p):
            p["rules"][1]["conditions"][1]["operator"] = "<"
            p["rules"][2]["conditions"][1]["operator"] = ">="

        misreading_reference = Implementation("misreading", "", TARGETS["democo-buggy"].decide)
        result = check(validated(misread), TARGETS["democo-fixed"].decide, reference=misreading_reference)
        self.assertEqual(findings(result, "TARGET_DISCREPANCY_CONFIRMED"), [])
        (disputed,) = findings(result, "TARGET_DISCREPANCY_DISPUTED", "point-40.00-dated")
        details = disputed.details
        self.assertEqual((details["target"], details["reference"], details["interpreted"]),
                         ("APPROVE", "REJECT", "REJECT"))
        self.assertEqual(details["model_expectations"], ["APPROVE"])
        self.assertEqual(details["disputed_because"],
                         ["the proposal's own expected decision (APPROVE) contradicts the reference"])
        self.assertIn("Not confirmed", disputed.summary)
        # The model's self-contradiction is still reported on its own.
        self.assertTrue(findings(result, "SELF_INCONSISTENT", "point-40.00-dated"))

    def test_consistent_expectations_keep_the_buggy_target_confirmed(self):
        result = verify(FIXTURE.document, POLICY_TEXT, reference=REFERENCE, target=TARGETS["democo-buggy"])
        (confirmed,) = findings(result, "TARGET_DISCREPANCY_CONFIRMED")
        self.assertEqual(confirmed.details["disputed_because"], [])
        self.assertEqual(confirmed.details["model_expectations"], ["APPROVE"])

    def test_a_contradiction_only_affects_its_own_point(self):
        document = validated(lambda p: add_case(p, "odd-expectation", 39.99, True, "REJECT"))
        rejects_up_to_forty = lambda c: "REJECT" if c.has_service_date and c.amount <= 40 and c.amount >= D("39.99") else reference_engine(c)
        result = check(document, rejects_up_to_forty, search_budget=0)
        self.assertEqual([f.points for f in findings(result, "TARGET_DISCREPANCY_DISPUTED")], [("point-39.99-dated",)])
        self.assertEqual([f.points for f in findings(result, "TARGET_DISCREPANCY_CONFIRMED")], [("point-40.00-dated",)])

    def test_a_contradicting_expectation_never_creates_a_target_finding(self):
        document = validated(lambda p: add_case(p, "odd-expectation", 39.99, True, "REJECT"))
        result = check(document, TARGETS["democo-fixed"].decide)
        self.assertFalse([f for f in result.findings if f.code.startswith("TARGET_DISCREPANCY")])
        self.assertTrue(findings(result, "SELF_INCONSISTENT", "point-39.99-dated"))

    def test_range_with_a_contradicted_point_is_disputed(self):
        def approves_90_to_150(c):
            if c.has_service_date and D("90.00") <= c.amount <= D("150.00"):
                return "APPROVE"
            return reference_engine(c)

        consistent = validated(lambda p: add_case(p, "hundred", 100.00, True, "REJECT"))
        contradicted = validated(lambda p: add_case(p, "hundred", 100.00, True, "APPROVE"))
        for document, code in ((consistent, "TARGET_DISCREPANCY_CONFIRMED"), (contradicted, "TARGET_DISCREPANCY_DISPUTED")):
            with self.subTest(code=code):
                result = check(document, approves_90_to_150)
                ranges = [f for f in result.findings if f.details.get("kind") == "range"]
                self.assertEqual([(f.code, f.details["start"], f.details["end"]) for f in ranges],
                                 [(code, "90.00", "150.00")])
                expected_reasons = [] if code.endswith("CONFIRMED") else [
                    "the proposal's own expected decision (APPROVE) contradicts the reference"]
                self.assertEqual(ranges[0].details["disputed_because"], expected_reasons)

    def test_loophole_range_and_boundaries_are_unchanged(self):
        result = verify(FIXTURE.document, POLICY_TEXT, reference=REFERENCE, target=TARGETS["democo-loophole"])
        (found,) = [f for f in result.findings if f.details.get("kind") == "range"]
        self.assertEqual((found.code, found.details["start"], found.details["end"],
                          found.details["agrees_below"], found.details["agrees_above"]),
                         ("TARGET_DISCREPANCY_CONFIRMED", "1000.00", "4999.99", "999.99", "5000.00"))

    def test_reports_with_disputes_are_reproducible(self):
        document = validated(lambda p: add_case(p, "odd-expectation", 39.99, True, "REJECT"))
        decide = lambda c: "REJECT" if c.has_service_date and c.amount <= 40 else reference_engine(c)
        self.assertEqual(check(document, decide).to_json(), check(document, decide).to_json())


def finding(code, severity):
    return Finding(code, severity, "s")


class VerdictTests(unittest.TestCase):
    def test_precedence(self):
        cases = [
            ([], 0, "OK"),
            ([finding("CHECKED", "info")], 0, "OK"),
            ([finding("PRECEDENCE_DEPENDENT", "warning"), finding("UNREACHABLE_RULE", "warning")], 0, "OK"),
            ([finding("TARGET_DISCREPANCY_MODEL_ONLY", "warning")], 4, "INCONCLUSIVE"),
            ([finding("TARGET_DISCREPANCY_DISPUTED", "warning")], 4, "INCONCLUSIVE"),
            ([finding("REFERENCE_DISAGREEMENT", "warning")], 4, "INCONCLUSIVE"),
            ([finding("TARGET_DISCREPANCY_DISPUTED", "warning"), finding("TARGET_DISCREPANCY_CONFIRMED", "error")], 3, "FAILED"),
            ([finding("TARGET_DISCREPANCY_DISPUTED", "warning"), finding("UNSUPPORTED", "error")], 3, "FAILED"),
            ([finding("COVERAGE_GAP", "error"), finding("TARGET_DISCREPANCY_MODEL_ONLY", "warning")], 3, "FAILED"),
            ([finding("VALIDATION_REJECTED", "error")], 2, "REJECTED"),
        ]
        for items, code, label in cases:
            with self.subTest(codes=[f.code for f in items]):
                result = verdict(items)
                self.assertEqual((result["exit_code"], result["label"]), (code, label))

    def test_inconclusive_is_not_described_as_a_wrong_target(self):
        self.assertIn("not evidence that the target is wrong", verdict([finding("TARGET_DISCREPANCY_DISPUTED", "warning")])["meaning"])

    def test_isolated_failures_map_to_the_documented_codes(self):
        hang = Implementation("hang", "", lambda c: None, "tests.isolation_targets:hangs_at_forty")
        crash = Implementation("crash", "", lambda c: None, "tests.isolation_targets:crashes_at_forty")
        broken = Implementation("broken", "", lambda c: None, "tests.isolation_broken:decide")
        cases = [
            # A call that never finished is not evaluated: an error, not a wrong target.
            (hang, REFERENCE, 3, "UNSUPPORTED"),
            (crash, REFERENCE, 3, "UNSUPPORTED"),
            (hang, None, 3, "UNSUPPORTED"),
            (broken, REFERENCE, 3, "UNSUPPORTED"),
        ]
        for impl, reference, code, expected in cases:
            with self.subTest(target=impl.name, reference=bool(reference)):
                result = verify(FIXTURE.document, POLICY_TEXT, reference=reference, target=impl,
                                target_timeout=0.5, search_budget=40)
                self.assertEqual(result.report["verification"]["result"]["exit_code"], code)
                self.assertIn(expected, result.codes())
                if expected == "UNSUPPORTED":  # every case above
                    self.assertFalse([c for c in result.codes() if c.startswith("TARGET_DISCREPANCY")])


class RequiredLevelTests(unittest.TestCase):
    def test_verdict_only_turns_ok_into_insufficient_evidence(self):
        cases = [
            ([], "L1", "L3", 5),
            ([], "L3", "L3", 0),
            ([], "L2", "L2", 0),
            ([], "NONE", "L0", 5),
            ([], "L1", None, 0),                                              # default: no minimum
            ([finding("TARGET_DISCREPANCY_CONFIRMED", "error")], "L2", "L3", 3),
            ([finding("TARGET_DISCREPANCY_MODEL_ONLY", "warning")], "L1", "L3", 4),
            ([finding("VALIDATION_REJECTED", "error")], "NONE", "L3", 2),
        ]
        for items, level, required, code in cases:
            with self.subTest(level=level, required=required, codes=[f.code for f in items]):
                result = verdict(items, level, required)
                self.assertEqual(result["exit_code"], code)
                if required is not None:
                    self.assertEqual((result["required_level"], result["level_reached"]), (required, level))
                else:
                    self.assertNotIn("required_level", result)

    def test_invalid_required_level_is_rejected(self):
        with self.assertRaises(ValueError):
            verify(FIXTURE.document, POLICY_TEXT, required_level="L4")

    def test_cli_require_level(self):
        run = CommandLineExitCodeTests().run_main
        replay = [str(POLICY_PATH), "--replay", str(FIXTURE_PATH)]
        cases = [
            (["--reference", "democo-meal", "--target", "democo-fixed", "--require-level", "L3"], 0, "OK"),
            (["--target", "democo-fixed", "--require-level", "L3"], 5, "INSUFFICIENT_EVIDENCE"),
            (["--reference", "democo-meal", "--require-level", "L3"], 5, "INSUFFICIENT_EVIDENCE"),
            (["--target", "democo-fixed"], 0, "OK"),                         # unchanged default
            (["--reference", "democo-meal", "--target", "democo-buggy", "--require-level", "L3"], 3, "FAILED"),
            (["--target", "democo-buggy", "--require-level", "L3"], 4, "INCONCLUSIVE"),
        ]
        for extra, code, label in cases:
            with self.subTest(args=extra):
                exit_code, out, _ = run(replay + extra)
                self.assertEqual(exit_code, code)
                self.assertIn(f"Result: {label} (exit code {code})", out)
        self.assertEqual(run(replay + ["--require-level", "L9"])[0], 2)


class CommandLineExitCodeTests(unittest.TestCase):
    def run_main(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = verification.main(argv)
            except SystemExit as exc:
                code = exc.code
        return code, out.getvalue(), err.getvalue()

    def replay(self, *extra):
        return [str(POLICY_PATH), "--replay", str(FIXTURE_PATH), *extra]

    def test_documented_exit_codes(self):
        cases = [
            (self.replay("--reference", "democo-meal", "--target", "democo-buggy"), 3, "FAILED"),
            (self.replay("--reference", "democo-meal", "--target", "democo-loophole"), 3, "FAILED"),
            (self.replay("--reference", "democo-meal", "--target", "democo-fixed"), 0, "OK"),
            (self.replay("--target", "democo-buggy"), 4, "INCONCLUSIVE"),
            (self.replay("--reference", "democo-meal"), 0, "OK"),
        ]
        for argv, code, label in cases:
            with self.subTest(argv=argv[3:]):
                exit_code, out, _ = self.run_main(argv)
                self.assertEqual(exit_code, code)
                self.assertIn(f"Result: {label} (exit code {code})", out)

    def test_report_records_the_same_result_as_the_exit_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "r.json"
            exit_code, _, _ = self.run_main(self.replay("--target", "democo-buggy", "--report", str(path)))
            result = json.loads(path.read_text(encoding="utf-8"))["verification"]["result"]
            self.assertEqual((exit_code, result["exit_code"], result["label"]), (4, 4, "INCONCLUSIVE"))

    def test_rejected_operational_and_usage_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "bad.json"
            body = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
            body["output"][0]["content"][0]["text"] = "{}"
            bad.write_text(json.dumps(body), encoding="utf-8")
            self.assertEqual(self.run_main([str(POLICY_PATH), "--replay", str(bad)])[0], 2)
        self.assertEqual(self.run_main(["no-such-policy.txt", "--replay", str(FIXTURE_PATH)])[0], 1)
        self.assertEqual(self.run_main(self.replay("--target", "not-allowlisted"))[0], 2)

    def test_help_documents_every_exit_code(self):
        _, out, _ = self.run_main(["--help"])
        for code, label in ((1, "ERROR"), (2, "REJECTED"), (3, "FAILED"), (4, "INCONCLUSIVE"),
                            (5, "INSUFFICIENT_EVIDENCE"), (0, "OK")):
            self.assertIn(f"  {code}  {label}", out)


if __name__ == "__main__":
    unittest.main()
