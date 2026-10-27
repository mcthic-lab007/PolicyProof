import contextlib
import copy
import dataclasses
import hashlib
import io
import json
import socket
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest import mock

import requests

from examples.buggy_engine import evaluate_meal_claim as buggy_engine
from examples.fixed_engine import evaluate_meal_claim as fixed_engine
from src.policyproof import verification
from src.policyproof.muse_client import API_KEY_ENV, replay_proposal
from src.policyproof.reference import evaluate_meal_claim as reference_engine
from src.policyproof.rule_engine import DerivationLimitError
from src.policyproof.schema import (
    Condition,
    RuleDocument,
    RuleSpec,
    parse_rule_document,
)
from src.policyproof.verification import Implementation, rejection_result, verify


ROOT = Path(__file__).resolve().parent.parent
POLICY_PATH = ROOT / "examples" / "democo_meal_policy.txt"
POLICY_TEXT = POLICY_PATH.read_text(encoding="utf-8")
FIXTURE_PATH = ROOT / "tests" / "fixtures" / "muse_democo_meal_response.json"
RULES_PAYLOAD = json.loads((ROOT / "examples" / "democo_meal_rules.json").read_text(encoding="utf-8"))
# Saved live Muse Spark response: local only, git-ignored, never committed.
LIVE_RESPONSE = ROOT / "artifacts" / "muse_live_001.json"

REFERENCE = Implementation("democo-meal-reference", "human-written synthetic reference", reference_engine)
BUGGY = Implementation("democo-buggy-engine", "seeded $40 bug", buggy_engine)
FIXED = Implementation("democo-fixed-engine", "corrected engine", fixed_engine)

FIXTURE = replay_proposal(FIXTURE_PATH, POLICY_TEXT)


def validated(mutate=None, policy=POLICY_TEXT):
    payload = copy.deepcopy(RULES_PAYLOAD)
    if mutate:
        mutate(payload)
    return parse_rule_document(json.dumps(payload), policy)


def live_shaped(payload):
    """The live proposal's structure: amount rules without date conditions."""
    for rule in payload["rules"][1:]:
        rule["conditions"] = [c for c in rule["conditions"] if c["field"] == "amount"]


def codes(result, code):
    return [f for f in result.findings if f.code == code]


def run(document, **kwargs):
    kwargs.setdefault("reference", REFERENCE)
    return verify(document, POLICY_TEXT, **kwargs)


class ConfirmedDiscrepancyTests(unittest.TestCase):
    """Acceptance 1 and 2: the seeded $40 bug."""

    def test_synthetic_fixture_finds_exactly_one_confirmed_discrepancy(self):
        result = run(FIXTURE.document, proposal=FIXTURE, target=BUGGY)
        confirmed = codes(result, "TARGET_DISCREPANCY_CONFIRMED")
        self.assertEqual(len(confirmed), 1)
        finding = confirmed[0]
        self.assertEqual(finding.points, ("point-40.00-dated",))
        self.assertEqual(finding.details, {
            "target": "REJECT", "target_error": None, "reference": "APPROVE", "interpreted": "APPROVE",
        })
        self.assertEqual(finding.rules, ("democo-meal-approve-40",))
        self.assertIn("Meal claims of $40.00 or less are approved automatically.", finding.summary)
        self.assertEqual(result.level, "L2")
        for code in ("TARGET_DISCREPANCY_DISPUTED", "TARGET_DISCREPANCY_MODEL_ONLY",
                     "REFERENCE_DISAGREEMENT", "COVERAGE_GAP", "SELF_INCONSISTENT"):
            self.assertEqual(codes(result, code), [], code)

    def test_found_without_any_model_test_cases(self):
        document = dataclasses.replace(FIXTURE.document, test_cases=())
        result = run(document, target=BUGGY)
        confirmed = codes(result, "TARGET_DISCREPANCY_CONFIRMED")
        self.assertEqual([f.points for f in confirmed], [("point-40.00-dated",)])
        point = next(p for p in result.report["points"] if p["id"] == "point-40.00-dated")
        kinds = {s["kind"] for s in point["sources"]}
        self.assertEqual(kinds, {"rule_threshold", "policy_text_amount"})

    def test_policy_text_thresholds_probe_what_the_rules_omit(self):
        def no_amount_rules(p):
            p["rules"] = p["rules"][:1] + [{**p["rules"][0], "id": "dated", "priority": 2,
                                           "decision": "APPROVE", "conditions": []}]
            p["test_cases"] = []

        result = run(validated(no_amount_rules), target=BUGGY)
        points = {p["id"]: p for p in result.report["points"]}
        self.assertTrue({"point-39.99-dated", "point-40.00-dated", "point-40.01-dated"} <= set(points))
        # The rules state no amount threshold; the $40.00 points exist only
        # because the policy text states $40.00.
        self.assertEqual({s["kind"] for s in points["point-40.00-dated"]["sources"]}, {"policy_text_amount"})
        # The rules approve every dated claim, which the reference contradicts...
        disagreement = {f.points[0] for f in codes(result, "REFERENCE_DISAGREEMENT")}
        self.assertIn("point-40.01-dated", disagreement)
        self.assertEqual(result.level, "L1")
        # ...but at $40.00 both independent perspectives approve and the target
        # rejects, so the seeded bug is still confirmed at that point.
        self.assertEqual([f.points for f in codes(result, "TARGET_DISCREPANCY_CONFIRMED")],
                         [("point-40.00-dated",)])


class CorrectTargetTests(unittest.TestCase):
    """Acceptance 3."""

    def test_fixed_target_reaches_l3_within_stated_scope(self):
        result = run(FIXTURE.document, proposal=FIXTURE, target=FIXED)
        self.assertEqual(result.level, "L3")
        self.assertEqual([f.code for f in result.findings], ["CHECKED"])
        scope = result.report["verification"]["scope"]
        self.assertIn("agreement holds at these points only", scope)
        self.assertIn("semantic correctness", " ".join(result.report["verification"]["not_established"]))
        self.assertNotIn("semantically correct", result.to_json())


class CorruptedRuleTests(unittest.TestCase):
    """Acceptance 4, 5 and 6: corruptions the validator accepts."""

    def test_less_than_never_yields_a_false_confirmation(self):
        for shape in (None, live_shaped):
            def mutate(p, shape=shape):
                if shape:
                    shape(p)
                for condition in p["rules"][1]["conditions"]:
                    if condition["field"] == "amount":
                        condition["operator"] = "<"

            with self.subTest(shape="live" if shape else "example"):
                result = run(validated(mutate), target=BUGGY)
                self.assertEqual(codes(result, "TARGET_DISCREPANCY_CONFIRMED"), [])
                gap = codes(result, "COVERAGE_GAP")
                self.assertEqual(len(gap), 1)
                self.assertIn("point-40.00-dated", gap[0].points)
                self.assertEqual(gap[0].details["other_perspectives"]["point-40.00-dated"]["reference"], "APPROVE")
                disputed = codes(result, "TARGET_DISCREPANCY_DISPUTED")
                self.assertEqual([f.points for f in disputed], [("point-40.00-dated",)])
                self.assertEqual(result.level, "L0")

    def test_flipped_decision_cannot_be_confirmed(self):
        result = run(validated(lambda p: p["rules"][1].update(decision="REJECT")), target=BUGGY)
        self.assertEqual(codes(result, "TARGET_DISCREPANCY_CONFIRMED"), [])
        self.assertEqual([f.points for f in codes(result, "TARGET_DISCREPANCY_DISPUTED")],
                         [("point-40.00-dated",)])
        disagreements = sorted(f.points[0] for f in codes(result, "REFERENCE_DISAGREEMENT"))
        self.assertEqual(disagreements, ["point-0.00-dated", "point-39.99-dated", "point-40.00-dated"])
        inconsistent = {f.details["case_id"] for f in codes(result, "SELF_INCONSISTENT")}
        self.assertEqual(inconsistent, {"just-below-threshold", "exact-threshold"})
        self.assertEqual(result.level, "L0")

    def test_flipped_decision_with_a_target_that_follows_it(self):
        flipped = Implementation("follows-flip", "rejects up to $40", lambda case: "REVIEW"
                                 if not case.has_service_date else "REJECT")
        result = run(validated(lambda p: p["rules"][1].update(decision="REJECT")), target=flipped)
        self.assertEqual(codes(result, "TARGET_DISCREPANCY_CONFIRMED"), [])
        self.assertTrue(codes(result, "TARGET_DISCREPANCY_DISPUTED"))

    def test_inverted_priorities_are_surfaced(self):
        def invert(p):
            live_shaped(p)
            p["rules"][0]["priority"], p["rules"][2]["priority"] = 3, 1

        result = run(validated(invert), target=FIXED)
        disagreements = {f.points[0] for f in codes(result, "REFERENCE_DISAGREEMENT")}
        self.assertTrue({"point-20.00-undated", "point-40.00-undated", "point-40.01-undated"} <= disagreements)
        precedence = codes(result, "PRECEDENCE_DEPENDENT")
        self.assertTrue(precedence)
        for finding in precedence:
            self.assertEqual(finding.severity, "warning")
            self.assertIs(finding.details["reference_agrees_with_priority_result"], False)
        self.assertNotEqual(result.level, "L2")

    def test_unreachable_rules_are_surfaced(self):
        def add_rules(p):
            duplicate = {**copy.deepcopy(p["rules"][1]), "id": "approve-duplicate", "priority": 4}
            impossible = {**copy.deepcopy(p["rules"][2]), "id": "never-holds", "priority": 5}
            impossible["conditions"] = [{"field": "amount", "operator": ">", "value": 40.00},
                                        {"field": "amount", "operator": "<", "value": 40.00}]
            p["rules"] += [duplicate, impossible]

        result = run(validated(add_rules))
        unreachable = {f.rules[0]: f.details["matches_somewhere"] for f in codes(result, "UNREACHABLE_RULE")}
        self.assertEqual(unreachable, {"approve-duplicate": True, "never-holds": False})


class PrecedenceTests(unittest.TestCase):
    """Acceptance 7."""

    def test_live_shaped_rules_expose_the_missing_date_assumption(self):
        result = run(validated(live_shaped), target=FIXED)
        groups = {f.details["overridden_rules"][0]["rule_id"]: f for f in codes(result, "PRECEDENCE_DEPENDENT")}
        self.assertEqual(set(groups), {"democo-meal-approve-40", "democo-meal-reject-above-40"})
        above = groups["democo-meal-reject-above-40"]
        self.assertIn("point-40.01-undated", above.points)
        self.assertIn("point-1000000.00-undated", above.points)
        self.assertIn("point-40.00-undated", groups["democo-meal-approve-40"].points)
        for finding in groups.values():
            self.assertEqual(finding.severity, "info")
            self.assertTrue(finding.details["assumption_documented"])
            self.assertIs(finding.details["reference_agrees_with_priority_result"], True)
            self.assertIn("does not itself state the order", finding.summary)
        self.assertEqual(result.level, "L3")

    def test_undocumented_overlap_is_a_warning(self):
        def undocumented(p):
            live_shaped(p)
            p["rules"][0]["description"] = "Claims without a service date go to manual review"

        precedence = codes(run(validated(undocumented)), "PRECEDENCE_DEPENDENT")
        self.assertTrue(precedence)
        self.assertTrue(all(f.severity == "warning" for f in precedence))
        self.assertTrue(all("No rule records this" in f.summary for f in precedence))

    @unittest.skipUnless(LIVE_RESPONSE.exists(), "local live Muse response not present (never committed)")
    def test_saved_live_response(self):
        proposal = replay_proposal(LIVE_RESPONSE, POLICY_TEXT)
        result = run(proposal.document, proposal=proposal, target=BUGGY)
        self.assertEqual(result.report["proposal"]["provenance_label"], "REPLAY_SAVED_LIVE_RESPONSE")
        self.assertEqual([f.points for f in codes(result, "TARGET_DISCREPANCY_CONFIRMED")],
                         [("point-40.00-dated",)])
        self.assertEqual(len(codes(result, "PRECEDENCE_DEPENDENT")), 2)


class NoReferenceTests(unittest.TestCase):
    """Acceptance 8."""

    def test_without_reference_l2_and_l3_are_unreachable(self):
        result = verify(FIXTURE.document, POLICY_TEXT, target=BUGGY)
        self.assertEqual(result.level, "L1")
        criteria = result.report["verification"]["criteria"]
        self.assertEqual(criteria["L2"]["detail"], "no reference supplied")
        self.assertFalse(criteria["L3"]["met"])
        self.assertEqual(codes(result, "TARGET_DISCREPANCY_CONFIRMED"), [])
        model_only = codes(result, "TARGET_DISCREPANCY_MODEL_ONLY")
        self.assertEqual([f.points for f in model_only], [("point-40.00-dated",)])
        self.assertIn("not confirmed", model_only[0].summary)

    def test_without_reference_or_target(self):
        result = verify(FIXTURE.document, POLICY_TEXT)
        self.assertEqual(result.level, "L1")
        self.assertIsNone(result.report["reference"])
        self.assertIsNone(result.report["target"])


class FailSafeTests(unittest.TestCase):
    """Acceptance 9."""

    def test_rejected_proposal(self):
        body = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        text = body["output"][0]["content"][0]["text"].replace("approved automatically", "auto-approved", 2)
        body["output"][0]["content"][0]["text"] = text
        with mock.patch.object(Path, "read_text", return_value=json.dumps(body)):
            try:
                replay_proposal("bad.json", POLICY_TEXT)
            except verification.ProposalRejectedError as exc:
                result = rejection_result(exc, POLICY_TEXT)
        self.assertEqual(result.level, "NONE")
        self.assertEqual(result.codes(), ["VALIDATION_REJECTED"])
        self.assertTrue(result.findings[0].details["issues"])
        self.assertEqual(result.report["points"], [])
        self.assertEqual(result.report["proposal"]["provenance_label"], "REPLAY_SYNTHETIC")

    def test_unsupported_document(self):
        document = RuleDocument("1.0", "x", (RuleSpec("r", "d", 1, (), "DENY", "e", (0, 0)),), ())
        result = run(document, target=BUGGY)
        self.assertEqual(result.level, "NONE")
        self.assertEqual(result.codes(), ["UNSUPPORTED"])
        self.assertIn("unsupported decision", result.findings[0].details["problems"][0])

    def test_derivation_limit(self):
        with mock.patch.object(verification, "derive_boundary_points",
                               side_effect=DerivationLimitError("12005 derived points exceed the limit")):
            result = run(FIXTURE.document)
        self.assertEqual((result.level, result.codes()), ("NONE", ["UNSUPPORTED"]))

    def test_target_that_raises_or_returns_garbage(self):
        def raises(case):
            raise RuntimeError("database offline")

        for name, decide, fragment in [
            ("raises", raises, "raised RuntimeError: database offline"),
            ("lowercase", lambda case: "approve", "returned 'approve'"),
            ("none", lambda case: None, "returned None"),
        ]:
            with self.subTest(target=name):
                result = run(FIXTURE.document, target=Implementation(name, "bad", decide))
                confirmed = codes(result, "TARGET_DISCREPANCY_CONFIRMED")
                per_point = [f for f in confirmed if f.details.get("kind") != "range"]
                self.assertEqual(len(per_point), len(result.points))
                self.assertIn(fragment, per_point[0].details["target_error"])
                # The target search adds one range per date value spanning the
                # whole domain, since the target fails everywhere.
                ranges = [f.details for f in confirmed if f.details.get("kind") == "range"]
                self.assertEqual(
                    sorted((r["has_service_date"], r["start"], r["end"]) for r in ranges),
                    [(False, "0.00", "1000000.00"), (True, "0.00", "1000000.00")],
                )
                self.assertEqual(result.level, "L2")

    def test_reference_that_fails_blocks_l2(self):
        def flaky(case):
            if case.amount == Decimal("40.00"):
                raise ValueError("unhandled")
            return reference_engine(case)

        result = run(FIXTURE.document, reference=Implementation("flaky", "bad", flaky), target=BUGGY)
        unsupported = codes(result, "UNSUPPORTED")
        self.assertEqual(len(unsupported), 1)
        self.assertEqual(set(unsupported[0].points), {"point-40.00-dated", "point-40.00-undated"})
        self.assertEqual(result.level, "L1")
        # Without a usable reference at 40.00 the bug is model-only, never confirmed.
        self.assertEqual([f.points for f in codes(result, "TARGET_DISCREPANCY_MODEL_ONLY")],
                         [("point-40.00-dated",)])
        self.assertEqual(codes(result, "TARGET_DISCREPANCY_CONFIRMED"), [])

    def test_unusable_and_excessive_policy_amounts(self):
        policy = POLICY_TEXT + "\nFees of $0.005 and $2,000,000.00 apply.\n"
        result = verify(FIXTURE.document, policy, reference=REFERENCE)
        unusable = [f for f in codes(result, "UNSUPPORTED") if f.severity == "info"]
        self.assertEqual({f.details["amount"] for f in unusable}, {"0.005", "2000000.00"})

        many = POLICY_TEXT + "".join(f"\nItem {i} costs ${i}.00." for i in range(1, 121))
        result = verify(FIXTURE.document, many, reference=REFERENCE)
        capped = [f for f in codes(result, "UNSUPPORTED") if f.severity == "warning"]
        self.assertEqual(len(capped), 1)
        self.assertIn("only the lowest 100", capped[0].summary)

    def test_missing_model_test_cases_are_reported_not_hidden(self):
        result = run(dataclasses.replace(FIXTURE.document, test_cases=()), target=FIXED)
        self.assertIn("0 of 0 model expectations agree", result.report["verification"]["criteria"]["L1"]["detail"])
        self.assertEqual(result.level, "L3")

    def test_invalid_arguments_raise(self):
        with self.assertRaises(ValueError):
            verify(FIXTURE.document, "   ")


class ReleaseReviewTests(unittest.TestCase):
    """Regressions for the release review: L0 must be earned against the
    supplied policy, and wording must not attribute a synthetic proposal to
    Muse Spark."""

    def manual_document(self, evidence, threshold="40.00", span=(0, 0)):
        rules = (
            RuleSpec("approve", "d", 1, (Condition("amount", "<=", Decimal(threshold)),),
                     "APPROVE", evidence, span),
            RuleSpec("reject", "d", 2, (), "REJECT", "Meal claims above $40.00 are rejected.", (0, 0)),
        )
        return RuleDocument("1.0", "manual", rules, ())

    def test_ungrounded_hand_built_document_is_rejected(self):
        result = run(self.manual_document("Meal claims up to $40 are fine."), target=BUGGY)
        self.assertEqual((result.level, result.codes()), ("NONE", ["VALIDATION_REJECTED"]))
        self.assertIn("not found verbatim", result.findings[0].details["issues"][0]["message"])

    def test_ungrounded_threshold_in_hand_built_document_is_rejected(self):
        doc = self.manual_document("Meal claims of $40.00 or less are approved automatically.", "50.00")
        self.assertEqual(run(doc).codes(), ["VALIDATION_REJECTED"])

    def test_stale_spans_are_recomputed_against_this_policy(self):
        doc = self.manual_document("Meal claims of $40.00 or less are approved automatically.", span=(0, 5))
        result = run(doc, target=BUGGY)
        self.assertEqual(result.level, "L1")  # the hand-built rules leave undated claims to REJECT
        for rule in result.report["rules"]:
            start, end = rule["evidence"]["span"]
            self.assertEqual(POLICY_TEXT[start:end], rule["evidence"]["quote"])

    def test_documents_from_another_policy_are_rejected(self):
        result = verify(FIXTURE.document, "Travel claims require a receipt for every expense.")
        self.assertEqual(result.codes(), ["VALIDATION_REJECTED"])

    def test_findings_never_attribute_a_synthetic_proposal_to_muse(self):
        for mutate in (None, lambda p: p["rules"][1].update(decision="REJECT")):
            for target in (BUGGY, None):
                with self.subTest(mutated=bool(mutate), target=bool(target)):
                    result = run(validated(mutate) if mutate else FIXTURE.document,
                                 proposal=FIXTURE, target=target, reference=REFERENCE if target else None)
                    text = " ".join(f["summary"] for f in result.report["findings"])
                    text += result.report["verification"]["scope"]
                    self.assertNotIn("Muse", text)
        self.assertIn("proposed rules", codes(run(FIXTURE.document, target=BUGGY),
                                              "TARGET_DISCREPANCY_CONFIRMED")[0].summary)

    def test_report_explains_levels_and_reported_model(self):
        report = run(FIXTURE.document, proposal=FIXTURE, target=BUGGY).report
        self.assertIn("not a quality grade", report["verification"]["level_meaning"])
        self.assertEqual(report["proposal"]["model_reported"], "muse-spark-1.3")
        self.assertNotIn("model", report["proposal"])
        self.assertEqual(report["proposal"]["provenance_label"], "REPLAY_SYNTHETIC")


class DeterminismAndNetworkTests(unittest.TestCase):
    """Acceptance 10."""

    def test_replay_runs_are_identical_and_offline(self):
        attempts = []

        def blocked(name):
            def fail(*args, **kwargs):
                attempts.append(name)
                raise OSError(f"network blocked ({name})")
            return fail

        guards = [mock.patch.object(socket, "getaddrinfo", blocked("dns")),
                  mock.patch.object(socket.socket, "connect", blocked("connect")),
                  mock.patch.object(requests.Session, "send", blocked("requests"))]
        with contextlib.ExitStack() as stack:
            for guard in guards:
                stack.enter_context(guard)
            reports = []
            for _ in range(2):
                proposal = replay_proposal(FIXTURE_PATH, POLICY_TEXT)
                reports.append(run(proposal.document, proposal=proposal, target=BUGGY).to_json())
        self.assertEqual(reports[0], reports[1])
        self.assertEqual(attempts, [])


class ReportTests(unittest.TestCase):
    """Acceptance 11."""

    @classmethod
    def setUpClass(cls):
        cls.result = run(FIXTURE.document, proposal=FIXTURE, target=BUGGY)
        cls.report = json.loads(cls.result.to_json())

    def test_policy_identity_without_policy_text(self):
        policy = self.report["policy"]
        self.assertEqual(policy["sha256"], hashlib.sha256(POLICY_TEXT.encode("utf-8")).hexdigest())
        self.assertEqual(policy["policy_id"], "democo-meal-claims")
        self.assertNotIn(POLICY_TEXT, self.result.to_json())

    def test_evidence_quotes_point_into_the_original_policy(self):
        for rule in self.report["rules"]:
            start, end = rule["evidence"]["span"]
            self.assertEqual(POLICY_TEXT[start:end], rule["evidence"]["quote"])

    def test_policy_thresholds_carry_positions(self):
        thresholds = self.report["policy_thresholds"]
        self.assertEqual([t["amount"] for t in thresholds], ["40.00"])
        for start, end in thresholds[0]["spans"]:
            self.assertEqual(POLICY_TEXT[start:end], "$40.00")

    def test_point_provenance_keeps_every_source(self):
        point = next(p for p in self.report["points"] if p["id"] == "point-40.00-dated")
        sources = point["sources"]
        self.assertEqual(
            sorted((s.get("rule_id") or s.get("case_id") or s["kind"]) for s in sources),
            sorted(["democo-meal-approve-40", "democo-meal-reject-above-40",
                    "policy_text_amount", "exact-threshold"]),
        )
        self.assertEqual(point["target"], {"decision": "REJECT", "error": None})
        self.assertEqual(point["reference"], {"decision": "APPROVE", "error": None})
        self.assertEqual(point["interpreted"]["decided_by"], "democo-meal-approve-40")
        self.assertEqual(point["model_expectations"][0]["expected_decision"], "APPROVE")
        self.assertEqual(len(point["interpreted"]["trace"]), 3)

    def test_proposal_reference_and_target_identities(self):
        proposal = self.report["proposal"]
        self.assertEqual(proposal["provenance_label"], "REPLAY_SYNTHETIC")
        self.assertEqual(proposal["response_id"], "resp_synthetic_democo_meal_001")
        self.assertIn("not cryptographic proof", proposal["note"])
        self.assertEqual(self.report["reference"]["name"], "democo-meal-reference")
        self.assertEqual(self.report["target"]["name"], "democo-buggy-engine")

    def test_report_is_stable_json(self):
        self.assertEqual(self.result.to_json(), run(FIXTURE.document, proposal=FIXTURE, target=BUGGY).to_json())
        self.assertNotIn("Bearer", self.result.to_json())


class CommandLineTests(unittest.TestCase):
    def run_main(self, argv, environ=None):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.dict(verification.sys.modules["os"].environ, environ or {}, clear=True), \
                mock.patch.object(requests.Session, "send", side_effect=AssertionError("network")), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = verification.main(argv)
        return code, out.getvalue(), err.getvalue()

    def base(self, *extra):
        return [str(POLICY_PATH), "--replay", str(FIXTURE_PATH), "--reference", "democo-meal", *extra]

    def test_buggy_target_exits_3_with_confirmed_finding(self):
        code, out, _ = self.run_main(self.base("--target", "democo-buggy"))
        self.assertEqual(code, 3)
        self.assertTrue(out.startswith("REPLAY of a SYNTHETIC fixture"))
        self.assertIn("TARGET_DISCREPANCY_CONFIRMED", out)
        self.assertIn("Verification level: L2", out)

    def test_fixed_target_exits_0_at_l3(self):
        code, out, _ = self.run_main(self.base("--target", "democo-fixed"))
        self.assertEqual(code, 0)
        self.assertIn("Verification level: L3", out)

    def test_report_is_written_and_never_overwritten_silently(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "report.json"
            code, out, _ = self.run_main(self.base("--target", "democo-buggy", "--report", str(path)))
            self.assertEqual(code, 3)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["verification"]["level"], "L2")
            code, _, err = self.run_main(self.base("--report", str(path)))
            self.assertEqual(code, 1)
            self.assertIn("--overwrite", err)
            code, _, _ = self.run_main(self.base("--report", str(path), "--overwrite"))
            self.assertEqual(code, 0)

    def test_only_allowlisted_targets_can_run(self):
        for name in ["os", "examples.buggy_engine", "../evil", "democo-buggy; rm"]:
            with self.subTest(name=name), self.assertRaises(SystemExit) as ctx, \
                    contextlib.redirect_stderr(io.StringIO()):
                verification.main(self.base("--target", name))
            self.assertEqual(ctx.exception.code, 2)

    def test_live_requires_explicit_flag_and_a_key(self):
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            verification.main([str(POLICY_PATH)])
        code, _, err = self.run_main([str(POLICY_PATH), "--live"])
        self.assertEqual(code, 1)
        self.assertIn(API_KEY_ENV, err)

    def test_rejected_replay_exits_2(self):
        body = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        body["output"][0]["content"][0]["text"] = "{}"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.json"
            path.write_text(json.dumps(body), encoding="utf-8")
            code, out, _ = self.run_main([str(POLICY_PATH), "--replay", str(path)])
        self.assertEqual(code, 2)
        self.assertIn("VALIDATION_REJECTED", out)

    def test_overwrite_without_report_and_missing_policy(self):
        code, _, err = self.run_main(self.base("--overwrite"))
        self.assertEqual(code, 1)
        code, _, err = self.run_main(["missing-policy.txt", "--replay", str(FIXTURE_PATH)])
        self.assertEqual(code, 1)
        self.assertTrue(err.startswith("error:"))


if __name__ == "__main__":
    unittest.main()
