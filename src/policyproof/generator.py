from decimal import Decimal

from src.policyproof.models import TestCase


def generate_meal_claim_cases() -> list[TestCase]:
    """Generate deterministic cases around the fictional $40 threshold."""
    return [
        TestCase(Decimal("0.00"), True, "Zero amount"),
        TestCase(Decimal("39.99"), True, "Just below threshold"),
        TestCase(Decimal("40.00"), True, "Exact threshold"),
        TestCase(Decimal("40.01"), True, "Just above threshold"),
        TestCase(Decimal("100.00"), True, "Well above threshold"),
        TestCase(Decimal("20.00"), False, "Missing service date"),
        TestCase(Decimal("40.00"), False, "Threshold with missing date"),
    ]
