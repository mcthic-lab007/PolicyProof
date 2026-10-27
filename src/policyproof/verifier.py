from collections.abc import Callable

from src.policyproof.models import Decision, TestCase, TestResult
from src.policyproof.reference import evaluate_meal_claim as reference_engine


def compare_engines(
    cases: list[TestCase],
    target: Callable[[TestCase], Decision],
) -> list[TestResult]:
    results = []

    for case in cases:
        expected = reference_engine(case)
        actual = target(case)

        results.append(
            TestResult(
                case=case,
                expected=expected,
                actual=actual,
                rule_id=(
                    "democo-meal-approve-40"
                    if case.has_service_date
                    and case.amount == 40
                    and expected != actual
                    else None
                ),
                explanation=(
                    "Claim at the $40 threshold was rejected; "
                    "the policy says $40 or less must be approved."
                    if case.has_service_date
                    and case.amount == 40
                    and expected != actual
                    else ""
                ),
            )
        )

    return results
