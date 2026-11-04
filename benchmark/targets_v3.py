"""Corpus v3 targets: special cases whose amounts are not written as
literals and cannot be folded by method E's constant evaluator.

Imported by the worker as "benchmark.targets_v3:<name>"; not a test module.
Every defect is confined to dated claims; undated claims are REVIEW, as the
policy requires. Ground truth is declared in benchmark/corpus_v3.py as
literal intervals, worked out from the mechanism below and checked
exhaustively over a window in tests/test_benchmark_v3.py.

Comments and docstrings here describe the bugs. The excerpt shown to Muse
drops them (source_literals.source_excerpt), exactly as for corpus v2.

Each mechanism is labelled:
  realistic mechanism  - a pattern found in real billing code, used here
                         to plant a deliberate defect;
  artificial fixture   - built only to probe a specific analysis limit.
"""

from decimal import ROUND_HALF_UP, Decimal

from benchmark.targets_v3_config import AUDIT_AMOUNT

LIMIT = Decimal("40.00")
CENT = Decimal("0.01")


def _policy(case):
    if not case.has_service_date:
        return "REVIEW"
    return "APPROVE" if case.amount <= LIMIT else "REJECT"


# --------------------------------------------------------- defective targets

# Realistic mechanism: a currency conversion rounded at run time. Approves
# dated claims whose converted amount rounds to exactly 1850:
# 1849.5 <= amount * 0.9213 < 1850.5, i.e. $2,007.49 to $2,008.57.
RATE = Decimal("0.9213")
PROMO_CONVERTED = Decimal("1850")


def converted_rounding_window(case):
    if not case.has_service_date:
        return "REVIEW"
    converted = (case.amount * RATE).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    if converted == PROMO_CONVERTED:
        return "APPROVE"
    return _policy(case)


# Artificial fixture: a value assembled by a loop at import time.
# sum(100 * k for k = 1..5) + 0.07 = $1,500.07, one cent.
_TIERS = tuple(Decimal("100.00") * k for k in range(1, 6))
_LOOP_EDGE = sum(_TIERS) + Decimal("0.07")


def loop_assembled_cent(case):
    if not case.has_service_date:
        return "REVIEW"
    if case.amount == _LOOP_EDGE:
        return "APPROVE"
    return _policy(case)


# Realistic mechanism: a range encoded in a configuration string and parsed
# at decision time. Approves dated $7,531.24 to $7,531.89.
_PROMO_RULE = "approve:7531.24-7531.89"


def encoded_string_range(case):
    if not case.has_service_date:
        return "REVIEW"
    _, _, span = _PROMO_RULE.partition(":")
    low, _, high = span.partition("-")
    if Decimal(low) <= case.amount <= Decimal(high):
        return "APPROVE"
    return _policy(case)


# Realistic mechanism: an override table keyed by integer cents. Approves
# dated $6,543.21 only. Its literal, 654321, read as dollars is $654,321.00.
_OVERRIDE_CENTS = frozenset({654321})


def integer_cents_table(case):
    if not case.has_service_date:
        return "REVIEW"
    if int(case.amount * 100) in _OVERRIDE_CENTS:
        return "APPROVE"
    return _policy(case)


# Artificial fixture: edges computed inside a helper (a lambda bound at
# module level). Approves dated $2,500.13 to $2,500.33. E folds constant
# sub-expressions wherever they occur, so it is expected to reach the lower edge.
_promo_floor = lambda: LIMIT * Decimal("62.5") + Decimal("0.13")  # noqa: E731


def helper_computed_range(case):
    if not case.has_service_date:
        return "REVIEW"
    floor = _promo_floor()
    if floor <= case.amount <= floor + Decimal("0.20"):
        return "APPROVE"
    return _policy(case)


# Artificial fixture: the special amount lives in another module
# (benchmark/targets_v3_config.py). Approves dated $8,642.13 only.
def imported_constant_cent(case):
    if not case.has_service_date:
        return "REVIEW"
    if case.amount == AUDIT_AMOUNT:
        return "APPROVE"
    return _policy(case)


# ------------------------------------------------------------ correct targets

# Same rounding mechanism, no defect: rounds to whole cents (a no-op for
# whole-cent inputs) before comparing.
def correct_quantized(case):
    if not case.has_service_date:
        return "REVIEW"
    rounded = case.amount.quantize(CENT, rounding=ROUND_HALF_UP)
    return "APPROVE" if rounded <= LIMIT else "REJECT"


# Same configuration-string mechanism, encoding the policy correctly.
_LIMIT_RULE = "approve-up-to:40.00"


def correct_config_string(case):
    if not case.has_service_date:
        return "REVIEW"
    limit = Decimal(_LIMIT_RULE.partition(":")[2])
    return "APPROVE" if case.amount <= limit else "REJECT"
