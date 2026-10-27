import ast
import copy
import json
import unittest
from decimal import Decimal
from pathlib import Path
from unittest import mock

from src.policyproof import schema
from src.policyproof.models import TestCase
from src.policyproof.reference import evaluate_meal_claim as reference_engine
from src.policyproof.schema import (
    Condition,
    RuleValidationError,
    parse_rule_document,
    validate_rule_payload,
)


EXAMPLES = Path(__file__).resolve().parent.parent / "examples"
POLICY_TEXT = (EXAMPLES / "democo_meal_policy.txt").read_text(encoding="utf-8")
RULES_JSON = (EXAMPLES / "democo_meal_rules.json").read_text(encoding="utf-8")
BASE_PAYLOAD = json.loads(RULES_JSON, parse_float=Decimal)


def payload():
    return copy.deepcopy(BASE_PAYLOAD)


class SchemaTestCase(unittest.TestCase):
    def assert_invalid(self, data, *expected, policy=POLICY_TEXT):
        """Assert validation fails with an issue for each (path, fragment) pair."""
        with self.assertRaises(RuleValidationError) as ctx:
            if isinstance(data, (str, bytes)):
                parse_rule_document(data, policy)
            else:
                validate_rule_payload(data, policy)
        issues = ctx.exception.issues
        for path, fragment in expected:
            self.assertTrue(
                any(i.path == path and fragment in i.message for i in issues),
                f"no issue at {path!r} containing {fragment!r}; got: {issues}",
            )
        return issues


class ValidDocumentTests(SchemaTestCase):
    def test_example_document_parses(self):
        document = parse_rule_document(RULES_JSON, POLICY_TEXT)

        self.assertEqual(document.policy_id, "democo-meal-claims")
        self.assertEqual(len(document.rules), 3)
        self.assertEqual(len(document.test_cases), 4)

        approve = document.rules[1]
        self.assertEqual(approve.id, "democo-meal-approve-40")
        self.assertEqual(approve.decision, "APPROVE")
        self.assertEqual(approve.conditions[1].operator, "<=")
        self.assertEqual(approve.conditions[1].value, Decimal("40.00"))
        self.assertIsInstance(approve.conditions[1].value, Decimal)
        self.assertIs(approve.conditions[0].value, True)

    def test_evidence_span_points_at_policy_text(self):
        document = parse_rule_document(RULES_JSON, POLICY_TEXT)
        for rule in document.rules:
            start, end = rule.evidence_span
            self.assertEqual(POLICY_TEXT[start:end], rule.evidence)

    def test_amounts_are_exact_decimals(self):
        document = parse_rule_document(RULES_JSON, POLICY_TEXT)
        amounts = [case.amount for case in document.test_cases]
        self.assertEqual(amounts[:3], [Decimal("39.99"), Decimal("40.00"), Decimal("40.01")])

    def test_example_expectations_agree_with_reference_engine(self):
        document = parse_rule_document(RULES_JSON, POLICY_TEXT)
        for case in document.test_cases:
            with self.subTest(case=case.id):
                self.assertEqual(
                    reference_engine(case.to_test_case()), case.expected_decision
                )

    def test_bytes_input_is_accepted(self):
        document = parse_rule_document(RULES_JSON.encode("utf-8"), POLICY_TEXT)
        self.assertEqual(len(document.rules), 3)

    def test_optional_case_fields_may_be_omitted_or_null(self):
        data = payload()
        del data["test_cases"][0]["rationale"]
        data["test_cases"][1]["rule_id"] = None
        document = validate_rule_payload(data, POLICY_TEXT)
        self.assertIsNone(document.test_cases[0].rationale)
        self.assertIsNone(document.test_cases[1].rule_id)

    def test_empty_conditions_and_test_cases_are_allowed(self):
        data = payload()
        data["rules"][2]["conditions"] = []
        data["test_cases"] = []
        document = validate_rule_payload(data, POLICY_TEXT)
        self.assertEqual(document.rules[2].conditions, ())
        self.assertEqual(document.test_cases, ())


class MalformedJsonTests(SchemaTestCase):
    def test_truncated_json(self):
        self.assert_invalid(RULES_JSON[:200], ("$", "malformed JSON"))

    def test_empty_string(self):
        self.assert_invalid("", ("$", "malformed JSON"))

    def test_markdown_fenced_json_is_rejected(self):
        self.assert_invalid(f"```json\n{RULES_JSON}\n```", ("$", "malformed JSON"))

    def test_duplicate_keys_are_rejected(self):
        raw = RULES_JSON.replace(
            '"schema_version": "1.0",', '"schema_version": "1.0", "schema_version": "1.0",'
        )
        self.assert_invalid(raw, ("$", "duplicate key 'schema_version'"))

    def test_non_finite_numbers_are_rejected(self):
        raw = RULES_JSON.replace('"amount": 39.99', '"amount": NaN')
        self.assert_invalid(raw, ("$", "non-finite number NaN"))

    def test_invalid_utf8_is_rejected(self):
        self.assert_invalid(b"\xff\xfe{}", ("$", "not valid UTF-8"))

    def test_oversized_document_is_rejected(self):
        raw = " " * (schema.MAX_DOCUMENT_CHARS + 1)
        self.assert_invalid(raw, ("$", "exceeds"))

    def test_top_level_must_be_object(self):
        self.assert_invalid("[]", ("$", "expected object, got array"))


class StructureTests(SchemaTestCase):
    def test_unknown_fields_are_rejected_at_every_level(self):
        data = payload()
        data["notes"] = "x"
        data["rules"][0]["confidence"] = 0.9
        data["rules"][0]["conditions"][0]["unit"] = "USD"
        data["test_cases"][0]["weight"] = 1
        data["test_cases"][0]["inputs"]["currency"] = "USD"
        self.assert_invalid(
            data,
            ("$", "unknown field 'notes'"),
            ("$.rules[0]", "unknown field 'confidence'"),
            ("$.rules[0].conditions[0]", "unknown field 'unit'"),
            ("$.test_cases[0]", "unknown field 'weight'"),
            ("$.test_cases[0].inputs", "unknown field 'currency'"),
        )

    def test_missing_required_fields(self):
        data = payload()
        del data["rules"][1]["evidence"]
        del data["test_cases"][0]["expected_decision"]
        del data["test_cases"][1]["inputs"]["has_service_date"]
        self.assert_invalid(
            data,
            ("$.rules[1]", "missing required field 'evidence'"),
            ("$.test_cases[0]", "missing required field 'expected_decision'"),
            ("$.test_cases[1].inputs", "missing required field 'has_service_date'"),
        )

    def test_wrong_container_types(self):
        data = payload()
        data["rules"][0]["conditions"] = {"field": "amount"}
        data["test_cases"][0]["inputs"] = [40, True]
        self.assert_invalid(
            data,
            ("$.rules[0].conditions", "expected array, got object"),
            ("$.test_cases[0].inputs", "expected object, got array"),
        )

    def test_rules_must_not_be_empty(self):
        data = payload()
        data["rules"] = []
        self.assert_invalid(data, ("$.rules", "must contain 1.."))

    def test_unsupported_schema_version(self):
        data = payload()
        data["schema_version"] = "2.0"
        self.assert_invalid(data, ("$.schema_version", "unsupported schema_version"))

    def test_invalid_identifiers(self):
        data = payload()
        data["rules"][0]["id"] = "Rule 1"
        data["test_cases"][0]["id"] = ""
        self.assert_invalid(
            data,
            ("$.rules[0].id", "invalid identifier"),
            ("$.test_cases[0].id", "must not be blank"),
        )

    def test_duplicate_ids_and_priorities(self):
        data = payload()
        data["rules"][2]["id"] = data["rules"][1]["id"]
        data["rules"][2]["priority"] = data["rules"][1]["priority"]
        data["test_cases"][1]["id"] = data["test_cases"][0]["id"]
        self.assert_invalid(
            data,
            ("$.rules", "duplicate id 'democo-meal-approve-40'"),
            ("$.rules", "duplicate priority 2"),
            ("$.test_cases", "duplicate id 'just-below-threshold'"),
        )

    def test_test_case_must_reference_known_rule(self):
        data = payload()
        data["test_cases"][0]["rule_id"] = "democo-meal-approve-50"
        self.assert_invalid(
            data, ("$.test_cases[0].rule_id", "unknown rule 'democo-meal-approve-50'")
        )

    def test_all_issues_are_reported_together(self):
        data = payload()
        data["rules"][0]["decision"] = "DENY"
        data["rules"][1]["conditions"][1]["operator"] = "=<"
        data["test_cases"][2]["inputs"]["amount"] = "40.01"
        issues = self.assert_invalid(
            data,
            ("$.rules[0].decision", "invalid decision"),
            ("$.rules[1].conditions[1].operator", "unsupported operator"),
            ("$.test_cases[2].inputs.amount", "expected number, got string"),
        )
        self.assertEqual(len(issues), 3)


class OperatorAndDecisionTests(SchemaTestCase):
    def test_unknown_operators_are_rejected(self):
        for operator in ["=<", "contains", "between", "__import__('os')", "", None, 1]:
            with self.subTest(operator=operator):
                data = payload()
                data["rules"][1]["conditions"][1]["operator"] = operator
                self.assert_invalid(
                    data, ("$.rules[1].conditions[1].operator", "unsupported operator")
                )

    def test_ordering_operator_on_boolean_field_is_rejected(self):
        data = payload()
        data["rules"][0]["conditions"][0]["operator"] = "<"
        self.assert_invalid(
            data, ("$.rules[0].conditions[0].operator", "unsupported operator '<'")
        )

    def test_unknown_field_is_rejected(self):
        data = payload()
        data["rules"][1]["conditions"][1]["field"] = "employee_level"
        self.assert_invalid(
            data, ("$.rules[1].conditions[1].field", "unsupported field 'employee_level'")
        )

    def test_invalid_decisions_are_rejected(self):
        for decision in ["approve", "DENY", "Approve ", "", None, True]:
            with self.subTest(decision=decision):
                data = payload()
                data["rules"][1]["decision"] = decision
                data["test_cases"][0]["expected_decision"] = decision
                self.assert_invalid(
                    data,
                    ("$.rules[1].decision", "invalid decision"),
                    ("$.test_cases[0].expected_decision", "invalid decision"),
                )


class ValueTests(SchemaTestCase):
    def test_unsupported_amounts_are_rejected(self):
        cases = [
            (40.0, "floats are inexact"),
            ("40.00", "expected number, got string"),
            (True, "expected number, got boolean"),
            (None, "expected number, got null"),
            (Decimal("-0.01"), "between 0 and"),
            (Decimal("1000000.01"), "between 0 and"),
            (Decimal("40.001"), "whole cents"),
            (Decimal("NaN"), "must be finite"),
            (Decimal("Infinity"), "must be finite"),
        ]
        for value, fragment in cases:
            with self.subTest(value=value):
                data = payload()
                data["test_cases"][0]["inputs"]["amount"] = value
                data["rules"][1]["conditions"][1]["value"] = value
                self.assert_invalid(
                    data,
                    ("$.test_cases[0].inputs.amount", fragment),
                    ("$.rules[1].conditions[1].value", fragment),
                )

    def test_integer_and_trailing_zero_amounts_are_accepted(self):
        data = payload()
        data["test_cases"][0]["inputs"]["amount"] = 40
        data["test_cases"][1]["inputs"]["amount"] = Decimal("40.000")
        document = validate_rule_payload(data, POLICY_TEXT)
        self.assertEqual(document.test_cases[0].amount, Decimal("40"))
        self.assertEqual(document.test_cases[1].amount, Decimal("40.00"))

    def test_boolean_fields_reject_non_booleans(self):
        for value in [1, 0, "true", None]:
            with self.subTest(value=value):
                data = payload()
                data["test_cases"][0]["inputs"]["has_service_date"] = value
                data["rules"][0]["conditions"][0]["value"] = value
                self.assert_invalid(
                    data,
                    ("$.test_cases[0].inputs.has_service_date", "expected boolean"),
                    ("$.rules[0].conditions[0].value", "expected boolean"),
                )

    def test_invalid_priorities_are_rejected(self):
        for value in [0, -1, True, "1", Decimal("1.5"), schema.MAX_PRIORITY + 1]:
            with self.subTest(value=value):
                data = payload()
                data["rules"][0]["priority"] = value
                self.assert_invalid(data, ("$.rules[0].priority", "expected integer"))

    def test_overlong_text_is_rejected(self):
        data = payload()
        data["rules"][0]["description"] = "x" * (schema.MAX_TEXT_CHARS + 1)
        self.assert_invalid(data, ("$.rules[0].description", "exceeds"))


class PolicyEvidenceTests(SchemaTestCase):
    def test_paraphrased_evidence_is_rejected(self):
        data = payload()
        data["rules"][1]["evidence"] = "Meal claims up to $40 are approved automatically."
        self.assert_invalid(data, ("$.rules[1].evidence", "not found verbatim"))

    def test_changed_threshold_is_rejected(self):
        data = payload()
        data["rules"][1]["evidence"] = "Meal claims of $50.00 or less are approved automatically."
        self.assert_invalid(data, ("$.rules[1].evidence", "not found verbatim"))

    def test_case_change_is_rejected(self):
        data = payload()
        data["rules"][2]["evidence"] = "meal claims above $40.00 are rejected."
        self.assert_invalid(data, ("$.rules[2].evidence", "not found verbatim"))

    def test_evidence_from_another_policy_is_rejected(self):
        with self.assertRaises(RuleValidationError) as ctx:
            parse_rule_document(RULES_JSON, "Travel claims require a receipt.")
        evidence_issues = [i for i in ctx.exception.issues if i.path.endswith(".evidence")]
        self.assertEqual(len(evidence_issues), 3)

    def test_too_short_evidence_is_rejected_even_if_present(self):
        data = payload()
        data["rules"][1]["evidence"] = "$40.00"
        self.assert_invalid(data, ("$.rules[1].evidence", "at least 15 characters"))

    def test_whitespace_differences_are_tolerated(self):
        data = payload()
        data["rules"][1]["evidence"] = "Meal claims of $40.00\n   or less are\tapproved automatically."
        document = validate_rule_payload(data, POLICY_TEXT)
        start, end = document.rules[1].evidence_span
        self.assertEqual(
            POLICY_TEXT[start:end], "Meal claims of $40.00 or less are approved automatically."
        )

    def test_evidence_spanning_a_line_break_matches(self):
        data = payload()
        data["rules"][0]["evidence"] = (
            "must include the date the meal was served. "
            "Claims without a service date"
        )
        validate_rule_payload(data, POLICY_TEXT)

    def test_regex_metacharacters_in_evidence_are_literal(self):
        data = payload()
        data["rules"][1]["evidence"] = "Meal claims of $40.00 or less .* automatically."
        self.assert_invalid(data, ("$.rules[1].evidence", "not found verbatim"))

    def test_blank_policy_text_is_a_caller_error(self):
        with self.assertRaises(ValueError):
            parse_rule_document(RULES_JSON, "   ")


def single_rule_payload(index, evidence, threshold=None):
    """A document holding only sample rule `index`, so it can be checked
    against a custom policy without the other rules' quotes."""
    data = payload()
    rule = data["rules"][index]
    rule["evidence"] = evidence
    if threshold is not None:
        rule["conditions"][1]["value"] = threshold
    data["rules"] = [rule]
    data["test_cases"] = []
    return data


def with_evidence(index, evidence, policy=POLICY_TEXT, threshold=None):
    data = single_rule_payload(index, evidence, threshold)
    return validate_rule_payload(data, policy).rules[0]


class EvidenceBoundaryTests(SchemaTestCase):
    def assert_splits_token(self, index, evidence):
        data = payload()
        data["rules"][index]["evidence"] = evidence
        self.assert_invalid(
            data, (f"$.rules[{index}].evidence", "middle of a word or number")
        )

    def test_truncated_dollar_amounts_are_rejected(self):
        for evidence in [
            "Meal claims of $4",
            "Meal claims of $40",
            "Meal claims of $40.",
            "Meal claims of $40.0",
        ]:
            with self.subTest(evidence=evidence):
                self.assert_splits_token(1, evidence)

    def test_quote_starting_inside_a_number_is_rejected(self):
        self.assert_splits_token(0, "00 or less are approved automatically.")
        self.assert_splits_token(0, ".00 or less are approved automatically.")

    def test_quote_beginning_mid_word_is_rejected(self):
        self.assert_splits_token(2, "eal claims above $40.00 are rejected.")

    def test_quote_ending_mid_word_is_rejected(self):
        self.assert_splits_token(2, "Meal claims above $40.00 are reject")

    def test_sentence_punctuation_boundaries_are_accepted(self):
        for evidence in [
            "Meal claims above $40.00 are rejected",
            "Meal claims above $40.00 are rejected.",
        ]:
            with self.subTest(evidence=evidence):
                with_evidence(2, evidence)

    def test_quote_inside_parentheses_is_accepted(self):
        rule = with_evidence(0, "Fictional policy for demonstration purposes only.")
        start, end = rule.evidence_span
        self.assertEqual(POLICY_TEXT[start - 1], "(")

    def test_later_whole_token_occurrence_is_used(self):
        policy = "Reclaims without a date are held; claims without a date are held."
        rule = with_evidence(0, "claims without a date are held", policy)
        self.assertEqual(rule.evidence_span, (34, 64))


class ThresholdGroundingTests(SchemaTestCase):
    def test_unsupported_threshold_citing_approval_sentence_is_rejected(self):
        data = payload()
        data["rules"][1]["conditions"][1]["value"] = Decimal("500.00")
        issues = self.assert_invalid(
            data, ("$.rules[1].conditions[1].value", "threshold 500.00 is not stated")
        )
        self.assertEqual(len(issues), 1)

    def test_off_by_one_cent_threshold_is_rejected(self):
        data = payload()
        data["rules"][2]["conditions"][1]["value"] = Decimal("40.01")
        self.assert_invalid(
            data, ("$.rules[2].conditions[1].value", "threshold 40.01 is not stated")
        )

    def test_threshold_must_be_in_the_rules_own_quote(self):
        data = payload()
        data["rules"][1]["evidence"] = data["rules"][0]["evidence"]
        self.assert_invalid(
            data, ("$.rules[1].conditions[1].value", "threshold 40.00 is not stated")
        )

    def test_number_without_currency_marker_does_not_ground_an_amount(self):
        policy = "Meal claims within 40 days of purchase are approved automatically."
        self.assert_invalid(
            single_rule_payload(1, policy),
            ("$.rules[0].conditions[1].value", "not stated as a dollar amount"),
            policy=policy,
        )

    def test_equal_values_in_other_notations_are_grounded(self):
        cases = [
            ("Claims of $40 or less are approved.", Decimal("40.00")),
            ("Claims of $1,000.00 or less are approved.", Decimal("1000")),
            ("Claims of $ 40.00 or less are approved.", Decimal("40")),
        ]
        for policy, value in cases:
            with self.subTest(policy=policy):
                with_evidence(1, policy, policy, threshold=value)

    def test_larger_or_malformed_amounts_do_not_ground_a_prefix(self):
        for amount in ["$400.00", "$40,5", "$4⁰.00", "$40.00x"]:
            with self.subTest(amount=amount):
                policy = f"Meal claims of {amount} or less are approved automatically."
                self.assert_invalid(
                    single_rule_payload(1, policy, threshold=Decimal("40.00")),
                    ("$.rules[0].conditions[1].value", "threshold 40.00"),
                    policy=policy,
                )
        policy = "Meal claims of $4⁰.00 or less are approved automatically."
        self.assert_invalid(
            single_rule_payload(1, policy, threshold=Decimal("4.00")),
            ("$.rules[0].conditions[1].value", "threshold 4.00"),
            policy=policy,
        )

    def test_rules_without_amount_conditions_need_no_number(self):
        document = parse_rule_document(RULES_JSON, POLICY_TEXT)
        self.assertNotIn("$", document.rules[0].evidence)


class NestingTests(SchemaTestCase):
    def test_deeply_nested_json_is_a_validation_error(self):
        self.assert_invalid("[" * 50_000 + "]" * 50_000, ("$", "nesting exceeds 32"))

    def test_nesting_limit_boundary(self):
        self.assert_invalid("[" * 33 + "]" * 33, ("$", "nesting exceeds 32"))
        issues = self.assert_invalid("[" * 32 + "]" * 32, ("$", "expected object"))
        self.assertFalse(any("nesting" in issue.message for issue in issues))

    def test_brackets_inside_strings_do_not_count(self):
        data = json.loads(RULES_JSON)
        data["rules"][0]["description"] = '[{"' * 100 + '\\"]'
        document = parse_rule_document(json.dumps(data), POLICY_TEXT)
        self.assertTrue(document.rules[0].description.startswith('[{"'))

    def test_recursion_error_is_converted(self):
        with mock.patch.object(schema.json, "loads", side_effect=RecursionError):
            self.assert_invalid("{}", ("$", "nesting is too deep"))


class EvidenceSpanTests(SchemaTestCase):
    """Spans are [start, end) indices into the original, unmodified policy."""

    def assert_span(self, index, evidence, policy, expected_passage):
        rule = with_evidence(index, evidence, policy)
        start, end = rule.evidence_span
        self.assertEqual(policy[start:end], expected_passage)

    def test_span_after_non_ascii_text(self):
        policy = POLICY_TEXT.replace("DemoCo", "DémoCo ﬁnancé 🍽️")
        evidence = "Meal claims above $40.00 are rejected."
        self.assert_span(2, evidence, policy, evidence)

    def test_span_after_decomposed_characters(self):
        policy = "Café policy. " + POLICY_TEXT
        evidence = "Meal claims above $40.00 are rejected."
        self.assert_span(2, evidence, policy, evidence)

    def test_composed_quote_matches_decomposed_policy(self):
        policy = "Claims for café meals must be sent for manual review."
        self.assert_span(
            0, "Claims for café meals must be sent", policy,
            "Claims for café meals must be sent",
        )

    def test_ligature_in_policy_is_folded(self):
        policy = "Claims without a service date need a ﬁnal manual review."
        self.assert_span(
            0, "need a final manual review", policy, "need a ﬁnal manual review"
        )

    def test_typographic_quotes_and_dashes_are_folded(self):
        policy = "An employee’s claims — without a service date — are reviewed."
        self.assert_span(
            0, "An employee's claims - without a service date - are reviewed.",
            policy, policy,
        )

    def test_invisible_characters_are_ignored(self):
        policy = POLICY_TEXT.replace("$40.00 or less", "$40.00​ or le­ss")
        self.assert_span(
            1, "Meal claims of $40.00 or less are approved automatically.", policy,
            "Meal claims of $40.00​ or le­ss are approved automatically.",
        )

    def test_no_break_space_and_line_breaks_are_whitespace(self):
        policy = "Claims without a service date must be sent\n   for manual review."
        self.assert_span(
            0, "Claims without a service date must be sent for manual review.",
            policy, policy,
        )

    def test_numeric_compatibility_characters_are_not_folded(self):
        for variant in ["＄４０.００", "$4⁰.00", "$½0.00"]:
            with self.subTest(variant=variant):
                policy = POLICY_TEXT.replace("$40.00 or less", f"{variant} or less")
                # An ASCII "$40.00" quote does not match the variant...
                self.assert_invalid(
                    payload(), ("$.rules[1].evidence", "not found verbatim"), policy=policy
                )
                # ...and quoting the variant itself does not ground 40.00.
                evidence = f"Meal claims of {variant} or less are approved automatically."
                self.assert_invalid(
                    single_rule_payload(1, evidence),
                    ("$.rules[0].conditions[1].value", "not stated as a dollar amount"),
                    policy=policy,
                )

    def test_full_width_letters_are_folded(self):
        policy = "Claims without a service date are ｒｅｖｉｅｗｅｄ."
        self.assert_span(
            0, "without a service date are reviewed.", policy,
            "without a service date are ｒｅｖｉｅｗｅｄ.",
        )


class UnicodeAndNumericTests(SchemaTestCase):
    def test_lone_surrogates_are_rejected(self):
        cases = [
            ("go to manual review", "\\ud800", "$.rules[0].description"),
            ('"rationale": "One cent', '"rationale": "\\udfff', "$.test_cases[0].rationale"),
        ]
        for old, new, path in cases:
            with self.subTest(path=path):
                raw = RULES_JSON.replace(old, new, 1)
                self.assert_invalid(raw, (path, "invalid Unicode"))

    def test_surrogate_in_policy_text_is_a_caller_error(self):
        with self.assertRaises(ValueError):
            parse_rule_document(RULES_JSON, POLICY_TEXT + "\ud800")

    def test_valid_surrogate_pairs_are_accepted(self):
        raw = RULES_JSON.replace("go to manual review", "\\ud83c\\udf7d review", 1)
        document = parse_rule_document(raw, POLICY_TEXT)
        self.assertIn("\U0001f37d", document.rules[0].description)

    def test_amounts_are_canonicalized_to_two_places(self):
        cases = [
            ("40", "40.00"),
            ("4E+1", "40.00"),
            ("40.000", "40.00"),
            ("-0.00", "0.00"),
            ("0", "0.00"),
            ("1E+6", "1000000.00"),
        ]
        for literal, expected in cases:
            with self.subTest(literal=literal):
                raw = RULES_JSON.replace('"amount": 39.99', f'"amount": {literal}')
                amount = parse_rule_document(raw, POLICY_TEXT).test_cases[0].amount
                self.assertEqual(str(amount), expected)

    def test_condition_values_are_canonicalized(self):
        raw = RULES_JSON.replace(
            '"operator": "<=", "value": 40.00', '"operator": "<=", "value": 4E+1'
        )
        rule = parse_rule_document(raw, POLICY_TEXT).rules[1]
        self.assertEqual(str(rule.conditions[1].value), "40.00")


class InterpretationAssumptionTests(unittest.TestCase):
    def test_missing_date_precedence_is_an_explicit_assumption(self):
        """An undated $20 claim satisfies both "Claims without a service date
        must be sent for manual review" and "Meal claims of $40.00 or less are
        approved automatically". The policy does not say which wins.

        The sample rules and reference.py both ASSUME the missing date takes
        precedence. This test pins that assumption so that changing it, or
        the policy wording, is a visible decision rather than a silent one.
        """
        lowered = POLICY_TEXT.lower()
        for phrase in ["precedence", "overrides", "regardless", "even if", "unless"]:
            self.assertNotIn(phrase, lowered)

        rules = {rule.id: rule for rule in parse_rule_document(RULES_JSON, POLICY_TEXT).rules}
        review = rules["democo-meal-review-no-date"]
        approve = rules["democo-meal-approve-40"]

        self.assertIn("Interpretation assumption", review.description)
        self.assertLess(review.priority, approve.priority)
        # The approval rule's date condition comes from the assumption, not
        # from its quote, which says nothing about service dates.
        self.assertIn(Condition("has_service_date", "==", True), approve.conditions)
        self.assertNotIn("date", approve.evidence)

        self.assertEqual(reference_engine(TestCase(Decimal("20.00"), False)), "REVIEW")


class NoDynamicEvaluationTests(unittest.TestCase):
    def test_schema_module_never_calls_eval_exec_or_compile(self):
        source = Path(schema.__file__).read_text(encoding="utf-8")
        forbidden = {"eval", "exec", "compile", "__import__"}
        calls = {
            node.func.id
            for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        self.assertFalse(calls & forbidden)


if __name__ == "__main__":
    unittest.main()
