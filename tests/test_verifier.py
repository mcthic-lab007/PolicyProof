import unittest
from decimal import Decimal

from examples.buggy_engine import evaluate_meal_claim as buggy_engine
from src.policyproof.generator import generate_meal_claim_cases
from src.policyproof.models import TestCase
from src.policyproof.reference import evaluate_meal_claim as reference_engine
from src.policyproof.verifier import compare_engines


class PolicyProofTests(unittest.TestCase):
    def test_reference_engine_boundary(self):
        cases = [
            (Decimal("39.99"), True, "APPROVE"),
            (Decimal("40.00"), True, "APPROVE"),
            (Decimal("40.01"), True, "REJECT"),
            (Decimal("20.00"), False, "REVIEW"),
        ]
        for amount, has_date, expected in cases:
            with self.subTest(amount=amount, has_date=has_date):
                self.assertEqual(
                    reference_engine(TestCase(amount, has_date)),
                    expected,
                )

    def test_verifier_detects_seeded_bug(self):
        cases = [
            TestCase(Decimal("39.99"), True, "Below threshold"),
            TestCase(Decimal("40.00"), True, "Exact threshold"),
            TestCase(Decimal("40.01"), True, "Above threshold"),
            TestCase(Decimal("20.00"), False, "Missing service date"),
        ]
        results = compare_engines(cases, buggy_engine)
        mismatches = [result for result in results if result.mismatch]

        self.assertEqual(len(results), 4)
        self.assertEqual(len(mismatches), 1)
        self.assertEqual(mismatches[0].case.amount, Decimal("40.00"))
        self.assertEqual(mismatches[0].expected, "APPROVE")
        self.assertEqual(mismatches[0].actual, "REJECT")
        self.assertEqual(mismatches[0].rule_id, "democo-meal-approve-40")

    def test_generated_cases_detect_boundary_bug(self):
        cases = generate_meal_claim_cases()
        results = compare_engines(cases, buggy_engine)
        mismatches = [result for result in results if result.mismatch]

        self.assertEqual(len(cases), 7)
        self.assertEqual(len(mismatches), 1)
        self.assertEqual(mismatches[0].case.description, "Exact threshold")


if __name__ == "__main__":
    unittest.main()
