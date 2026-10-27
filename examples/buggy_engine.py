from decimal import Decimal

from src.policyproof.models import Decision, TestCase


def evaluate_meal_claim(case: TestCase) -> Decision:
    """Intentionally buggy DemoCo engine: rejects claims at exactly $40."""
    if not case.has_service_date:
        return "REVIEW"

    if case.amount < Decimal("40.00"):
        return "APPROVE"

    return "REJECT"
