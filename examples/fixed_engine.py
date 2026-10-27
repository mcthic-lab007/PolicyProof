from decimal import Decimal

from src.policyproof.models import Decision, TestCase


APPROVAL_LIMIT = Decimal("40.00")


def evaluate_meal_claim(case: TestCase) -> Decision:
    """Corrected DemoCo engine: claims of exactly $40.00 are approved."""
    if not case.has_service_date:
        return "REVIEW"
    return "APPROVE" if case.amount <= APPROVAL_LIMIT else "REJECT"
