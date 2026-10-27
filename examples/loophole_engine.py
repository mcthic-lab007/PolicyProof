from decimal import Decimal

from src.policyproof.models import Decision, TestCase


APPROVAL_LIMIT = Decimal("40.00")
# Seeded defect, far from any threshold the policy states: dated claims from
# $1,000.00 to $4,999.99 are approved instead of rejected.
LOOPHOLE_LOW = Decimal("1000.00")
LOOPHOLE_HIGH = Decimal("4999.99")


def evaluate_meal_claim(case: TestCase) -> Decision:
    """DemoCo engine that is correct at every policy threshold but approves
    dated claims from $1,000.00 to $4,999.99."""
    if not case.has_service_date:
        return "REVIEW"
    if LOOPHOLE_LOW <= case.amount <= LOOPHOLE_HIGH:
        return "APPROVE"
    return "APPROVE" if case.amount <= APPROVAL_LIMIT else "REJECT"
