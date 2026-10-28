"""Misbehaving targets for the worker-process tests. Imported by the worker
as "tests.isolation_targets:<name>"; not a test module itself."""

import os
import sys
import time
from decimal import Decimal

from src.policyproof.reference import evaluate_meal_claim as correct

FORTY = Decimal("40.00")


def _at_forty(case):
    return case.has_service_date and case.amount == FORTY


def hangs_always(case):
    while True:  # a runaway loop, not a sleep: it must be killed, not woken
        pass


def hangs_at_forty(case):
    if _at_forty(case):
        hangs_always(case)
    return correct(case)


def slow(case):
    time.sleep(0.05)
    return correct(case)


def slow_at_forty(case):
    """Correct, but takes 1 s for dated $40.00."""
    if _at_forty(case):
        time.sleep(1.0)
    return correct(case)


def wrong_below_slow_at_forty(case):
    """Wrong at dated $39.99 and takes 1 s for dated $40.00."""
    if case.has_service_date and case.amount == Decimal("39.99"):
        return "REJECT"
    return slow_at_forty(case)


def hangs_at_a_thousand(case):
    """Correct, but never returns for dated $1,000.00, a round-number probe
    of the target search rather than an evaluated point."""
    if case.has_service_date and case.amount == Decimal("1000.00"):
        hangs_always(case)
    return correct(case)


def crashes_at_forty(case):
    if _at_forty(case):
        os._exit(7)
    return correct(case)


def exits(case):
    sys.exit(0)


def raises(case):
    raise RuntimeError("ledger offline")


def returns_lowercase(case):
    return "approve"


def returns_none(case):
    return None


def prints_noise(case):
    print("debug output from the target")
    return correct(case)


def corrupts_protocol(case):
    os.write(1, b"not json\n")  # bypasses the redirected sys.stdout
    return correct(case)


def raises_keyboard_interrupt(case):
    raise KeyboardInterrupt


def reports_env(case):
    return "REJECT" if "META_MUSE_API_KEY" in os.environ else "APPROVE"


not_callable = 42
