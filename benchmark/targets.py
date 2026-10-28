"""Benchmark targets for the fictional DemoCo meal policy. Imported by the
worker as "benchmark.targets:<name>"; not a test module itself.

Every function is a self-contained engine (none calls the reference), so a
target is wrong exactly where its own code says so. The ground truth for
each one is declared in benchmark/corpus.py, next to the reason it exists.

Policy (examples/democo_meal_policy.txt): no service date -> REVIEW; dated
claims of $40.00 or less -> APPROVE; dated claims above $40.00 -> REJECT.
"""

import time
from decimal import ROUND_HALF_EVEN, Decimal


LIMIT = Decimal("40.00")
CENT = Decimal("0.01")


# ----------------------------------------------------------- correct targets

def correct_integer_cents(case):
    """Works in integer cents."""
    if not case.has_service_date:
        return "REVIEW"
    return "APPROVE" if int(case.amount * 100) <= 4000 else "REJECT"


def correct_reordered(case):
    """Tests the amount before the date, but keeps the date's precedence."""
    if case.amount > LIMIT and case.has_service_date:
        return "REJECT"
    if not case.has_service_date:
        return "REVIEW"
    return "APPROVE"


def correct_float(case):
    """Compares as a float. Looks suspicious, but 40.0 is exact in binary and
    every whole-cent amount above $40.00 converts to a float above 40.0."""
    if not case.has_service_date:
        return "REVIEW"
    return "APPROVE" if float(case.amount) <= 40.0 else "REJECT"


# ------------------------------------------------- buggy targets: boundaries

def off_by_one_cent(case):
    """Approves up to $40.01."""
    if not case.has_service_date:
        return "REVIEW"
    return "APPROVE" if case.amount <= Decimal("40.01") else "REJECT"


def truncates_cents(case):
    """Drops the cents before comparing: $40.01 to $40.99 are approved."""
    if not case.has_service_date:
        return "REVIEW"
    return "APPROVE" if int(case.amount) <= 40 else "REJECT"


def bankers_rounding(case):
    """Rounds to whole dollars half-to-even first: $40.50 rounds to $40, so
    $40.01 to $40.50 are approved."""
    if not case.has_service_date:
        return "REVIEW"
    dollars = case.amount.quantize(Decimal("1"), rounding=ROUND_HALF_EVEN)
    return "APPROVE" if dollars <= 40 else "REJECT"


def date_checked_after_amount(case):
    """Rejects large claims before looking at the date, so undated claims
    above $40.00 are rejected instead of reviewed."""
    if case.amount > LIMIT:
        return "REJECT"
    if not case.has_service_date:
        return "REVIEW"
    return "APPROVE"


# ------------------------------------ buggy targets: far from any threshold

def single_cent_override(case):
    """A leftover special case: dated $777.77 is approved."""
    if not case.has_service_date:
        return "REVIEW"
    if case.amount == Decimal("777.77"):
        return "APPROVE"
    return "APPROVE" if case.amount <= LIMIT else "REJECT"


def narrow_literal_range(case):
    """Approves dated $12,345.67 to $12,345.99 (33 cents wide)."""
    if not case.has_service_date:
        return "REVIEW"
    if Decimal("12345.67") <= case.amount <= Decimal("12345.99"):
        return "APPROVE"
    return "APPROVE" if case.amount <= LIMIT else "REJECT"


# Edges computed from other constants: no literal in the source equals them.
_BASE = LIMIT * 50                       # 2000.00
_LOW = _BASE + Decimal(37) * CENT        # 2000.37
_HIGH = _LOW + Decimal(15) * CENT        # 2000.52


def narrow_computed_range(case):
    """Approves dated $2,000.37 to $2,000.52; the edges are computed."""
    if not case.has_service_date:
        return "REVIEW"
    if _LOW <= case.amount <= _HIGH:
        return "APPROVE"
    return "APPROVE" if case.amount <= LIMIT else "REJECT"


def approves_from_900k(case):
    """Approves dated claims from $900,000.00 to the end of the domain."""
    if not case.has_service_date:
        return "REVIEW"
    if case.amount >= Decimal("900000.00"):
        return "APPROVE"
    return "APPROVE" if case.amount <= LIMIT else "REJECT"


def two_disconnected_ranges(case):
    """Approves dated $100.00 to $199.99, and undated $5,000.00 to $9,999.99."""
    if not case.has_service_date:
        return "APPROVE" if Decimal("5000.00") <= case.amount <= Decimal("9999.99") else "REVIEW"
    if Decimal("100.00") <= case.amount <= Decimal("199.99"):
        return "APPROVE"
    return "APPROVE" if case.amount <= LIMIT else "REJECT"


def odd_cents_approved(case):
    """Approves dated claims above $40.00 whose cents are odd: about half of
    a hundred million amounts, but no two of them adjacent."""
    if not case.has_service_date:
        return "REVIEW"
    if case.amount > LIMIT and int(case.amount * 100) % 2 == 1:
        return "APPROVE"
    return "APPROVE" if case.amount <= LIMIT else "REJECT"


# ----------------------------------------------- execution-failure targets

def raises_above_500(case):
    """A lookup that fails for dated claims above $500.00."""
    if not case.has_service_date:
        return "REVIEW"
    if case.amount > Decimal("500.00"):
        raise LookupError("approval ledger has no tier for this amount")
    return "APPROVE" if case.amount <= LIMIT else "REJECT"


def hangs_at_threshold(case):
    """Never returns for dated $40.00 (a busy loop, not a sleep)."""
    if not case.has_service_date:
        return "REVIEW"
    if case.amount == LIMIT:
        while True:
            pass
    return "APPROVE" if case.amount <= LIMIT else "REJECT"


def lowercase_approve(case):
    """Returns "approve" instead of "APPROVE" for dated claims up to $40.00."""
    if not case.has_service_date:
        return "REVIEW"
    return "approve" if case.amount <= LIMIT else "REJECT"


def slow_at_threshold(case):
    """Correct everywhere, but takes 3 s for dated $40.00: longer than the
    default 2 s per-call timeout, so that call never completes."""
    if case.has_service_date and case.amount == LIMIT:
        time.sleep(3.0)
    if not case.has_service_date:
        return "REVIEW"
    return "APPROVE" if case.amount <= LIMIT else "REJECT"


def slow_correct(case):
    """Correct, but takes 20 ms per call."""
    time.sleep(0.02)
    if not case.has_service_date:
        return "REVIEW"
    return "APPROVE" if case.amount <= LIMIT else "REJECT"


def exclusive_reference(case):
    """A second human reading of the policy that excludes exactly $40.00.
    Used as a conflicting *reference*, not as a target."""
    if not case.has_service_date:
        return "REVIEW"
    return "APPROVE" if case.amount < LIMIT else "REJECT"
