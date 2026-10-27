import ast
import copy
import json
import random
import unittest
from decimal import Decimal
from pathlib import Path

from src.policyproof import rule_engine
from src.policyproof.reference import evaluate_meal_claim as reference_engine
from src.policyproof.rule_engine import (
    DEFAULT_MAX_POINTS,
    SCHEMA_MAX_POINTS,
    DerivationLimitError,
    RuleEngine,
    RuleEngineError,
    UnsupportedRuleError,
    case_inputs,
    count_boundary_points,
    derive_boundary_points,
    evaluate,
)
from src.policyproof.schema import (
    MAX_AMOUNT,
    Condition,
    RuleDocument,
    RuleSpec,
    parse_rule_document,
)


ROOT = Path(__file__).resolve().parent.parent
POLICY_TEXT = (ROOT / "examples" / "democo_meal_policy.txt").read_text(encoding="utf-8")
RULES_JSON = (ROOT / "examples" / "democo_meal_rules.json").read_text(encoding="utf-8")
BASE_PAYLOAD = json.loads(RULES_JSON)
# Saved live Muse Spark response: local only, git-ignored, never committed.
LIVE_RESPONSE = ROOT / "artifacts" / "muse_live_001.json"

D = Decimal


def inputs(amount, dated=True):
    return {"amount": D(amount), "has_service_date": dated}


def validated(mutate=None, policy=POLICY_TEXT):
    """A schema-validated document, optionally mutated before validation."""
    payload = copy.deepcopy(BASE_PAYLOAD)
    if mutate:
        mutate(payload)
    return parse_rule_document(json.dumps(payload), policy)


def drop_date_conditions(payload):
    """Shape of the live Muse proposal: the amount rules carry no date
    condition and rely on the review rule's higher priority."""
    for rule in payload["rules"][1:]:
        rule["conditions"] = [c for c in rule["conditions"] if c["field"] == "amount"]


def rule(rule_id, priority, decision, *conditions):
    return RuleSpec(rule_id, "test rule", priority, tuple(conditions), decision, "evidence", (0, 0))


def document(*rules, test_cases=()):
    return RuleDocument("1.0", "test-policy", tuple(rules), tuple(test_cases))


def amount(op, value):
    return Condition("amount", op, D(value))


def dated(value=True, op="=="):
    return Condition("has_service_date", op, value)


EXAMPLE = validated()
LIVE_SHAPED = validated(drop_date_conditions)


class BoundaryDecisionTests(unittest.TestCase):
    def test_forty_dollar_boundary(self):
        for doc in (EXAMPLE, LIVE_SHAPED):
            engine = RuleEngine(doc)
            for value, expected in [("39.99", "APPROVE"), ("40.00", "APPROVE"), ("40.01", "REJECT")]:
                with self.subTest(doc=doc.rules[1].id, amount=value):
                    result = engine.evaluate(inputs(value))
                    self.assertEqual(result.status, "DECIDED")
                    self.assertEqual(result.decision, expected)

    def test_missing_service_date_takes_precedence(self):
        for doc in (EXAMPLE, LIVE_SHAPED):
            engine = RuleEngine(doc)
            for value in ["0.00", "20.00", "40.00", "40.01", str(MAX_AMOUNT)]:
                with self.subTest(doc=doc.rules[1].id, amount=value):
                    result = engine.evaluate(inputs(value, dated=False))
                    self.assertEqual(result.decision, "REVIEW")
                    self.assertEqual(result.decided_by, doc.rules[0].id)

    def test_interpreter_agrees_with_reference_on_derived_points(self):
        for doc in (EXAMPLE, LIVE_SHAPED):
            engine = RuleEngine(doc)
            for point in derive_boundary_points(doc).points:
                with self.subTest(doc=doc.rules[1].id, point=point.id):
                    self.assertEqual(
                        engine.evaluate(case_inputs(point)).decision,
                        reference_engine(point.to_test_case()),
                    )


class TraceTests(unittest.TestCase):
    def test_trace_exposes_first_match_and_overlap(self):
        result = evaluate(LIVE_SHAPED, inputs("20.00", dated=False))
        review, approve, reject = result.rule_traces
        self.assertEqual(result.decided_by, review.rule_id)
        self.assertTrue(review.matched and review.decided)
        # The approval rule also matched; priority, not its conditions, kept it
        # from deciding. This is the precedence assumption, made visible.
        self.assertTrue(approve.matched)
        self.assertFalse(approve.decided)
        self.assertFalse(reject.matched)
        self.assertEqual(result.matching_rule_ids, (review.rule_id, approve.rule_id))
        self.assertTrue(result.has_conflicting_matches)

    def test_example_rules_do_not_overlap(self):
        for point in derive_boundary_points(EXAMPLE).points:
            with self.subTest(point=point.id):
                result = evaluate(EXAMPLE, case_inputs(point))
                self.assertEqual(len(result.matching_rule_ids), 1)
                self.assertFalse(result.has_conflicting_matches)

    def test_condition_trace_records_values_and_outcomes(self):
        result = evaluate(EXAMPLE, inputs("40.01"))
        approve = result.rule_traces[1]
        date_check, amount_check = approve.conditions
        self.assertEqual((date_check.field, date_check.actual, date_check.holds), ("has_service_date", True, True))
        self.assertEqual(
            (amount_check.operator, amount_check.expected, amount_check.actual, amount_check.holds),
            ("<=", D("40.00"), D("40.01"), False),
        )
        self.assertFalse(approve.matched)

    def test_all_rules_are_traced_in_priority_order(self):
        result = evaluate(EXAMPLE, inputs("10.00"))
        self.assertEqual([t.priority for t in result.rule_traces], [1, 2, 3])
        self.assertEqual(sum(t.decided for t in result.rule_traces), 1)


class CorruptionTests(unittest.TestCase):
    """Schema-valid corruptions: the validator accepts each of these. The
    interpreter executes them faithfully; spotting the corruption needs a
    comparison (with expectations or a reference) that is out of Phase 1."""

    def test_less_than_instead_of_less_or_equal_leaves_a_gap(self):
        doc = validated(lambda p: p["rules"][1]["conditions"][1].update(operator="<"))
        self.assertEqual(evaluate(doc, inputs("39.99")).decision, "APPROVE")
        at = evaluate(doc, inputs("40.00"))
        self.assertEqual(at.status, "NO_MATCH")
        self.assertIsNone(at.decision)
        statuses = {evaluate(doc, case_inputs(p)).status for p in derive_boundary_points(doc).points}
        self.assertIn("NO_MATCH", statuses)

    def test_less_than_in_live_shape_falls_through_to_no_match(self):
        doc = validated(lambda p: (drop_date_conditions(p), p["rules"][1]["conditions"][0].update(operator="<")))
        self.assertEqual(evaluate(doc, inputs("40.00")).status, "NO_MATCH")

    def test_inverted_priorities_change_the_decision_silently(self):
        def invert(p):
            drop_date_conditions(p)
            p["rules"][0]["priority"], p["rules"][2]["priority"] = 3, 1

        doc = validated(invert)
        result = evaluate(doc, inputs("20.00", dated=False))
        self.assertEqual(result.decision, "APPROVE")
        self.assertEqual(result.decided_by, "democo-meal-approve-40")
        # Not an error to the interpreter; only the overlap flag hints at it.
        self.assertTrue(result.has_conflicting_matches)
        self.assertNotEqual(result.decision, reference_engine(rule_engine.TestCase(D("20.00"), False)))

    def test_duplicate_rule_is_never_reached(self):
        def duplicate(p):
            copy_rule = copy.deepcopy(p["rules"][1])
            copy_rule.update(id="approve-duplicate", priority=4)
            p["rules"].append(copy_rule)

        doc = validated(duplicate)
        deciders, matchers = set(), set()
        for point in derive_boundary_points(doc).points:
            result = evaluate(doc, case_inputs(point))
            deciders.add(result.decided_by)
            matchers.update(result.matching_rule_ids)
        self.assertIn("approve-duplicate", matchers)
        self.assertNotIn("approve-duplicate", deciders)

    def test_flipped_decision_is_executed_as_written(self):
        doc = validated(lambda p: p["rules"][1].update(decision="REJECT"))
        self.assertEqual(evaluate(doc, inputs("39.99")).decision, "REJECT")
        # The document's own test cases still say APPROVE: the disagreement
        # is detectable, but by comparison, not by interpretation alone.
        disagreements = [
            case.id
            for case in doc.test_cases
            if evaluate(doc, case_inputs(case)).decision != case.expected_decision
        ]
        self.assertEqual(disagreements, ["just-below-threshold", "exact-threshold"])

    def test_wrong_expected_decision_is_not_the_interpreters_concern(self):
        doc = validated(lambda p: p["test_cases"][1].update(expected_decision="REJECT"))
        self.assertEqual(evaluate(doc, inputs("40.00")).decision, "APPROVE")


class NoMatchAndCombinationTests(unittest.TestCase):
    def test_no_matching_rule_is_never_an_approval(self):
        doc = document(rule("approve-small", 1, "APPROVE", amount("<=", "40.00")))
        result = evaluate(doc, inputs("40.01"))
        self.assertEqual(result.status, "NO_MATCH")
        self.assertIsNone(result.decision)
        self.assertIsNone(result.decided_by)
        self.assertEqual(result.matching_rule_ids, ())
        self.assertEqual(len(result.rule_traces), 1)

    def test_conditions_are_combined_with_and(self):
        doc = document(
            rule("band", 1, "REVIEW", amount(">", "10.00"), amount("<", "20.00"), dated()),
            rule("fallback", 2, "REJECT"),
        )
        cases = [("15.00", True, "band"), ("10.00", True, "fallback"), ("20.00", True, "fallback"),
                 ("15.00", False, "fallback"), ("10.01", True, "band"), ("19.99", True, "band")]
        for value, is_dated, expected in cases:
            with self.subTest(amount=value, dated=is_dated):
                self.assertEqual(evaluate(doc, inputs(value, is_dated)).decided_by, expected)

    def test_failed_conditions_are_identified(self):
        doc = document(rule("band", 1, "REVIEW", amount(">", "10.00"), amount("<", "20.00"), dated()))
        trace = evaluate(doc, inputs("25.00", False)).rule_traces[0]
        self.assertEqual([c.holds for c in trace.conditions], [True, False, False])

    def test_rule_without_conditions_always_matches(self):
        doc = document(rule("catch-all", 1, "REVIEW"))
        for value in ["0.00", "40.00", str(MAX_AMOUNT)]:
            self.assertEqual(evaluate(doc, inputs(value, False)).decision, "REVIEW")

    def test_boolean_not_equal_operator(self):
        doc = document(rule("dated-only", 1, "APPROVE", dated(False, "!=")))
        self.assertEqual(evaluate(doc, inputs("1.00", True)).decision, "APPROVE")
        self.assertEqual(evaluate(doc, inputs("1.00", False)).status, "NO_MATCH")

    def test_every_amount_operator(self):
        expected = {"<": [True, False, False], "<=": [True, True, False], ">": [False, False, True],
                    ">=": [False, True, True], "==": [False, True, False], "!=": [True, False, True]}
        for op, outcomes in expected.items():
            doc = document(rule("r", 1, "APPROVE", amount(op, "40.00")))
            for value, outcome in zip(["39.99", "40.00", "40.01"], outcomes):
                with self.subTest(op=op, amount=value):
                    self.assertEqual(evaluate(doc, inputs(value)).status == "DECIDED", outcome)


class InvalidInputTests(unittest.TestCase):
    def assert_invalid(self, value, fragment):
        result = evaluate(EXAMPLE, value)
        self.assertEqual(result.status, "INVALID_INPUT")
        self.assertIsNone(result.decision)
        self.assertEqual(result.rule_traces, ())
        self.assertTrue(any(fragment in issue for issue in result.input_issues), result.input_issues)

    def test_missing_and_unknown_inputs(self):
        self.assert_invalid({"amount": D("10.00")}, "missing input 'has_service_date'")
        self.assert_invalid({"has_service_date": True}, "missing input 'amount'")
        self.assert_invalid({}, "missing input")
        self.assert_invalid(dict(inputs("10.00"), currency="USD"), "unknown input 'currency'")

    def test_unexpected_amount_types_and_values(self):
        cases = [
            (40.0, "expected Decimal, got float"),
            (40, "expected Decimal, got int"),
            (True, "expected Decimal, got bool"),
            ("40.00", "expected Decimal, got str"),
            (None, "expected Decimal, got NoneType"),
            (D("NaN"), "must be finite"),
            (D("Infinity"), "must be finite"),
            (D("-0.01"), "outside schema domain"),
            (MAX_AMOUNT + D("0.01"), "outside schema domain"),
            (D("40.001"), "whole cents"),
        ]
        for value, fragment in cases:
            with self.subTest(value=value):
                self.assert_invalid({"amount": value, "has_service_date": True}, fragment)

    def test_unexpected_boolean_types(self):
        for value in [1, 0, "true", None, D("1")]:
            with self.subTest(value=value):
                self.assert_invalid({"amount": D("10.00"), "has_service_date": value}, "expected bool")

    def test_inputs_must_be_a_mapping(self):
        for value in [None, [("amount", D("1.00"))], "amount=1", D("1.00")]:
            with self.subTest(value=value):
                self.assert_invalid(value, "inputs must be a mapping")

    def test_all_issues_are_reported(self):
        result = evaluate(EXAMPLE, {"amount": 40.0, "extra": 1})
        self.assertEqual(len(result.input_issues), 3)


class UnsupportedDocumentTests(unittest.TestCase):
    def assert_unsupported(self, doc, fragment):
        with self.assertRaises(UnsupportedRuleError) as ctx:
            RuleEngine(doc)
        self.assertTrue(any(fragment in p for p in ctx.exception.problems), ctx.exception.problems)

    def test_raw_dicts_are_refused(self):
        self.assert_unsupported(BASE_PAYLOAD, "expected a validated RuleDocument, got dict")
        self.assert_unsupported(None, "got NoneType")

    def test_unsupported_operators_fields_and_values(self):
        cases = [
            (Condition("amount", "=~", D("1.00")), "unsupported operator '=~'"),
            (Condition("amount", "between", D("1.00")), "unsupported operator"),
            (Condition("has_service_date", "<", True), "unsupported operator '<'"),
            (Condition("employee_level", "==", D("1.00")), "unsupported field 'employee_level'"),
            (Condition("amount", "<", True), "value expected Decimal, got bool"),
            (Condition("amount", "<", 40.0), "value expected Decimal, got float"),
            (Condition("amount", "<", D("40.001")), "whole cents"),
            (Condition("has_service_date", "==", 1), "value expected bool"),
            (Condition(["amount"], "<", D("1.00")), "unsupported field"),
            ("amount < 40", "not a Condition"),
        ]
        for condition, fragment in cases:
            with self.subTest(condition=condition):
                self.assert_unsupported(document(rule("r", 1, "APPROVE", condition)), fragment)

    def test_unsupported_decisions(self):
        for decision in ["DENY", "approve", None, ["APPROVE"]]:
            with self.subTest(decision=decision):
                self.assert_unsupported(document(rule("r", 1, decision)), "unsupported decision")

    def test_duplicate_ids_and_priorities(self):
        self.assert_unsupported(document(rule("a", 1, "APPROVE"), rule("a", 2, "REJECT")), "duplicate id")
        self.assert_unsupported(document(rule("a", 1, "APPROVE"), rule("b", 1, "REJECT")), "duplicate priority 1")
        self.assert_unsupported(document(rule("a", True, "APPROVE")), "priority must be an integer")

    def test_empty_document(self):
        self.assert_unsupported(document(), "document has no rules")

    def test_all_problems_are_reported_together(self):
        doc = document(rule("a", 1, "DENY", Condition("amount", "=~", D("1"))), rule("a", 1, "APPROVE"))
        with self.assertRaises(UnsupportedRuleError) as ctx:
            RuleEngine(doc)
        self.assertEqual(len(ctx.exception.problems), 4)

    def test_derivation_also_refuses_unsupported_documents(self):
        with self.assertRaises(UnsupportedRuleError):
            derive_boundary_points(document(rule("r", 1, "DENY")))


class DecimalTests(unittest.TestCase):
    def test_equivalent_decimal_representations_evaluate_identically(self):
        for value in ["40", "40.0", "40.00", "4E+1", "40.000"]:
            with self.subTest(value=value):
                self.assertEqual(evaluate(EXAMPLE, inputs(value)).decision, "APPROVE")

    def test_negative_zero_is_zero(self):
        self.assertEqual(evaluate(EXAMPLE, inputs("-0.00")).decision, "APPROVE")

    def test_derived_amounts_are_exact_canonical_cents(self):
        amounts = [p.amount for p in derive_boundary_points(EXAMPLE).points]
        self.assertEqual(
            [str(a) for a in sorted(set(amounts))],
            ["0.00", "39.99", "40.00", "40.01", "1000000.00"],
        )
        self.assertTrue(all(a.as_tuple().exponent == -2 for a in amounts))

    def test_cent_offsets_have_no_binary_float_error(self):
        doc = document(rule("r", 1, "APPROVE", amount("<=", "0.30")))
        amounts = {str(p.amount) for p in derive_boundary_points(doc).points}
        self.assertTrue({"0.29", "0.30", "0.31"} <= amounts)
        self.assertNotEqual(0.1 + 0.2, 0.3)  # what Decimal avoids

    def test_thresholds_at_domain_edges_are_clipped_and_reported(self):
        doc = document(
            rule("low", 1, "REVIEW", amount("==", "0.00")),
            rule("high", 2, "REVIEW", amount(">=", str(MAX_AMOUNT))),
        )
        derivation = derive_boundary_points(doc)
        amounts = {p.amount for p in derivation.points}
        self.assertTrue(all(D("0.00") <= a <= MAX_AMOUNT for a in amounts))
        self.assertEqual(len(derivation.excluded), 2)
        self.assertTrue(any("-0.01" in e for e in derivation.excluded))
        self.assertTrue(any("1000000.01" in e for e in derivation.excluded))


class BoundaryDerivationTests(unittest.TestCase):
    def test_democo_points_cover_threshold_and_both_date_values(self):
        points = derive_boundary_points(LIVE_SHAPED).points
        pairs = {(str(p.amount), p.has_service_date) for p in points}
        for value in ["39.99", "40.00", "40.01"]:
            self.assertIn((value, True), pairs)
            self.assertIn((value, False), pairs)
        self.assertEqual(len(points), 10)

    def test_provenance_names_each_contributing_condition(self):
        points = {p.id: p for p in derive_boundary_points(EXAMPLE).points}
        at = points["derived-40.00-dated"]
        self.assertEqual(
            [(s.kind, s.rule_id, s.condition_index, s.offset) for s in at.amount_sources],
            [("threshold", "democo-meal-approve-40", 1, D("0.00")),
             ("threshold", "democo-meal-reject-above-40", 1, D("0.00"))],
        )
        below = points["derived-39.99-undated"]
        self.assertEqual({s.offset for s in below.amount_sources}, {D("-0.01")})
        self.assertIn("democo-meal-review-no-date.conditions[0]", below.boolean_sources[0])
        edge = points["derived-1000000.00-dated"]
        self.assertEqual(edge.amount_sources[0].kind, "domain_bound")
        self.assertIn("not a policy limit", edge.amount_sources[0].label)

    def test_unreferenced_boolean_is_still_varied_and_says_so(self):
        doc = document(rule("approve", 1, "APPROVE", amount("<=", "40.00")))
        points = derive_boundary_points(doc).points
        self.assertEqual({p.has_service_date for p in points}, {True, False})
        self.assertIn("no rule references it", points[0].boolean_sources[0])

    def test_extra_thresholds_carry_their_label(self):
        derivation = derive_boundary_points(EXAMPLE, [(D("25.00"), "policy text mentions $25.00")])
        sources = [s for p in derivation.points if p.amount == D("25.00") for s in p.amount_sources]
        self.assertTrue(sources)
        self.assertTrue(all(s.kind == "extra" and "policy text" in s.label for s in sources))
        with self.assertRaises(RuleEngineError):
            derive_boundary_points(EXAMPLE, [(25.0, "float")])

    def test_points_ignore_proposed_test_cases(self):
        def odd_cases(p):
            p["test_cases"][0]["inputs"]["amount"] = 12.34
            p["test_cases"][0]["expected_decision"] = "APPROVE"

        without = validated(lambda p: p.update(test_cases=[]))
        odd = validated(odd_cases)
        self.assertEqual(derive_boundary_points(without), derive_boundary_points(EXAMPLE))
        self.assertEqual(derive_boundary_points(odd), derive_boundary_points(EXAMPLE))
        self.assertNotIn(D("12.34"), {p.amount for p in derive_boundary_points(odd).points})

    def test_document_without_numeric_thresholds(self):
        def boolean_only(p):
            p["rules"] = p["rules"][:1]
            p["rules"].append({**p["rules"][0], "id": "dated", "priority": 2, "decision": "APPROVE",
                               "conditions": [{"field": "has_service_date", "operator": "==", "value": True}]})
            p["test_cases"] = []

        doc = validated(boolean_only)
        points = derive_boundary_points(doc).points
        self.assertEqual([(str(p.amount), p.has_service_date) for p in points],
                         [("0.00", False), ("0.00", True), ("1000000.00", False), ("1000000.00", True)])
        self.assertTrue(all(s.kind == "domain_bound" for p in points for s in p.amount_sources))

    def test_points_are_sorted_and_unique(self):
        points = derive_boundary_points(LIVE_SHAPED).points
        keys = [(p.amount, p.has_service_date) for p in points]
        self.assertEqual(keys, sorted(keys))
        self.assertEqual(len(keys), len(set(keys)))
        self.assertEqual(len({p.id for p in points}), len(points))

    def test_points_cover_every_distinct_rule_outcome(self):
        """Brute force: on whole cents near the thresholds, every combination
        of condition outcomes the rules can produce also occurs at some
        derived point. Seeded random documents with up to 8 thresholds."""
        rng = random.Random(20261027)
        ops = ["<", "<=", ">", ">=", "==", "!="]
        for trial in range(4):
            rules = [
                rule(f"r{i}", i + 1, rng.choice(["APPROVE", "REJECT", "REVIEW"]),
                     *[amount(rng.choice(ops), f"{rng.randint(0, 6000) / 100:.2f}")
                       for _ in range(rng.randint(1, 2))],
                     *([dated(rng.choice([True, False]))] if rng.random() < 0.5 else []))
                for i in range(rng.randint(2, 4))
            ]
            doc = document(*rules)
            engine = RuleEngine(doc)

            def signature(value, is_dated):
                result = engine.evaluate(inputs(value, is_dated))
                return tuple(c.holds for t in result.rule_traces for c in t.conditions)

            derived = {signature(p.amount, p.has_service_date) for p in derive_boundary_points(doc).points}
            brute = {signature(D(cents) / 100, d) for cents in range(0, 7001) for d in (False, True)}
            with self.subTest(trial=trial):
                self.assertLessEqual(brute, derived)


class SizeLimitTests(unittest.TestCase):
    def many_thresholds(self, count):
        return document(*[rule(f"r{i}", i + 1, "REVIEW", amount("<=", f"{i + 1}.00")) for i in range(count)])

    def test_count_matches_derivation(self):
        doc = self.many_thresholds(30)
        self.assertEqual(count_boundary_points(doc), len(derive_boundary_points(doc).points))

    def test_limit_fails_safely_before_generation(self):
        doc = self.many_thresholds(60)
        with self.assertRaises(DerivationLimitError) as ctx:
            derive_boundary_points(doc, max_points=100)
        self.assertIn("exceed the limit of 100", str(ctx.exception))

    def test_default_limit_covers_any_schema_valid_document(self):
        self.assertEqual(SCHEMA_MAX_POINTS, 12_004)
        self.assertGreaterEqual(DEFAULT_MAX_POINTS, SCHEMA_MAX_POINTS)


class DeterminismTests(unittest.TestCase):
    def test_repeated_runs_are_identical(self):
        first = [evaluate(LIVE_SHAPED, case_inputs(p)) for p in derive_boundary_points(LIVE_SHAPED).points]
        second = [evaluate(LIVE_SHAPED, case_inputs(p)) for p in derive_boundary_points(LIVE_SHAPED).points]
        self.assertEqual(first, second)

    def test_rule_order_in_document_does_not_matter(self):
        shuffled = RuleDocument(
            LIVE_SHAPED.schema_version, LIVE_SHAPED.policy_id,
            tuple(reversed(LIVE_SHAPED.rules)), LIVE_SHAPED.test_cases,
        )
        self.assertEqual(derive_boundary_points(shuffled), derive_boundary_points(LIVE_SHAPED))
        for point in derive_boundary_points(LIVE_SHAPED).points:
            self.assertEqual(evaluate(shuffled, case_inputs(point)), evaluate(LIVE_SHAPED, case_inputs(point)))


@unittest.skipUnless(LIVE_RESPONSE.exists(), "local live Muse response not present (it is never committed)")
class LiveMuseResponseTests(unittest.TestCase):
    """Runs only where the git-ignored live response exists. Offline replay;
    no API call."""

    def test_live_rules_on_derived_points(self):
        from src.policyproof.muse_client import replay_proposal

        doc = replay_proposal(LIVE_RESPONSE, POLICY_TEXT).document
        engine = RuleEngine(doc)
        conflicts = []
        for point in derive_boundary_points(doc).points:
            result = engine.evaluate(case_inputs(point))
            self.assertEqual(result.decision, reference_engine(point.to_test_case()), point.id)
            if result.has_conflicting_matches:
                conflicts.append(point.id)
        # Without date conditions on the amount rules, every undated claim
        # also matches an amount rule; only priority makes it REVIEW.
        undated = [p.id for p in derive_boundary_points(doc).points if not p.has_service_date]
        self.assertEqual(conflicts, undated)


class NoDynamicEvaluationTests(unittest.TestCase):
    def test_engine_never_evaluates_code(self):
        source = Path(rule_engine.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        calls = {
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        self.assertFalse(calls & {"eval", "exec", "compile", "__import__", "getattr"})


if __name__ == "__main__":
    unittest.main()
