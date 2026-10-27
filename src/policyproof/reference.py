from decimal import Decimal

from src.policyproof.models import Decision, TestCase


def evaluate_meal_claim(case: TestCase) -> Decision:
    """Evaluate the fictional DemoCo meal-claim policy."""
    if not case.has_service_date:
        return "REVIEW"

    if case.amount <= Decimal("40.00"):
        return "APPROVE"

    return "REJECT"
