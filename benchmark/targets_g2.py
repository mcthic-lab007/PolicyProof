"""Generalization corpus g2 targets: written after the H correction
(c4a0694) and frozen before any method was measured on them, to test the
corrected H (and G) on code not used to develop either. None is a copy or a
renamed mutation of a corpus g1 target.

Imported by the worker as "benchmark.targets_g2:<name>"; not a test module.
Every defect is confined to dated claims; undated claims are REVIEW, as the
policy requires. Ground truth is declared in benchmark/corpus_g2.py as
literal intervals and re-checked by tests/test_benchmark_g2.py.

Roles (corpus_g2.ROLE):
  H corrected   integer cents scaled with a Decimal factor: the case the
                correction is about (H before c4a0694 is predicted to miss);
  H either      integer cents scaled with a plain 100 (both H versions);
  G positive    amounts written inside strings, in layouts not in g1;
  abstain       a defect H must not claim: imported, inside a helper, an
                unsupported factor, an alias, an undiscoverable value, or a
                cents name the code itself uses as dollars;
  control       a correct implementation full of misleading numbers.
"""

import decimal
import re
from decimal import Decimal
from decimal import Decimal as Dec

from benchmark.targets_g2_config import HOLIDAY_CENTS

LIMIT = Decimal("40.00")


def _policy(case):
    if not case.has_service_date:
        return "REVIEW"
    return "APPROVE" if case.amount <= LIMIT else "REJECT"


# ------------------------------------------------------------ H corrected

# Refund overrides keyed by cents, scaled with Decimal("100"): dated $7,311.50.
_REFUND_OVERRIDES = frozenset({731150})


def refund_override_lookup(case):
    if not case.has_service_date:
        return "REVIEW"
    if int((case.amount * Decimal("100")).to_integral_value()) in _REFUND_OVERRIDES:
        return "APPROVE"
    return _policy(case)


# A bonus dictionary read through decimal.Decimal(100): dated $1,899.07-$1,899.08.
_BONUS = {189907: "APPROVE", 189908: "APPROVE"}


def bonus_dict_module_decimal(case):
    if not case.has_service_date:
        return "REVIEW"
    return _BONUS.get(int(decimal.Decimal(100) * case.amount)) or _policy(case)


# A range of minor units held in a local: dated $5,600.10-$5,600.25.
def minor_units_window(case):
    if not case.has_service_date:
        return "REVIEW"
    minor_units = int(case.amount * Decimal(100))
    if 560010 <= minor_units <= 560025:
        return "APPROVE"
    return _policy(case)


# Quantized to whole cents and matched against Decimal members: dated $9,182.73.
_AUDIT_SET = {Decimal(918273)}


def quantized_audit_set(case):
    if not case.has_service_date:
        return "REVIEW"
    cents = (case.amount * Decimal("100.00")).quantize(Decimal("1"))
    if cents in _AUDIT_SET:
        return "APPROVE"
    return _policy(case)


# camelCase locals in cents: dated $2,700.00-$2,700.50.
def camel_case_promo_band(case):
    if not case.has_service_date:
        return "REVIEW"
    promoFloorCents = 270000
    promoCeilCents = 270050
    amountCents = int(case.amount * Decimal(100))
    if promoFloorCents <= amountCents <= promoCeilCents:
        return "APPROVE"
    return _policy(case)


# Misnamed: called dollars, used as cents: dated $5,123.45.
_LIMIT_DOLLARS = 512_345


def misnamed_dollars_constant(case):
    if not case.has_service_date:
        return "REVIEW"
    if int(case.amount * Decimal(100)) == _LIMIT_DOLLARS:
        return "APPROVE"
    return _policy(case)


# --------------------------------------------------------------- H either

REIMBURSEMENT_CAP_CENTS = 1_234_599


def reimbursement_cap_cent(case):
    if not case.has_service_date:
        return "REVIEW"
    if round(case.amount * 100) == REIMBURSEMENT_CAP_CENTS:
        return "APPROVE"
    return _policy(case)


def rounded_cents_pair(case):
    if not case.has_service_date:
        return "REVIEW"
    cents = round(100 * case.amount)
    if cents in {44401, 44402}:
        return "APPROVE"
    return _policy(case)


# ------------------------------------------------------------- G positive

_LIMITS_YAML = "limits:\n  promo_low: 6650.25\n  promo_high: 6650.40\n"


def yaml_like_limits(case):
    if not case.has_service_date:
        return "REVIEW"
    values = dict(line.strip().split(": ") for line in _LIMITS_YAML.splitlines()[1:])
    if Decimal(values["promo_low"]) <= case.amount <= Decimal(values["promo_high"]):
        return "APPROVE"
    return _policy(case)


_RANGE_SPEC = "range[880.80..880.95] action=approve"


def bracketed_range_spec(case):
    if not case.has_service_date:
        return "REVIEW"
    low, high = re.search(r"\[(.+)\.\.(.+)\]", _RANGE_SPEC).groups()
    if Decimal(low) <= case.amount <= Decimal(high):
        return "APPROVE"
    return _policy(case)


# ---------------------------------------------------------------- abstain

# Imported cents: dated $3,650.25.
def imported_holiday_cents(case):
    if not case.has_service_date:
        return "REVIEW"
    if int(case.amount * Decimal(100)) == HOLIDAY_CENTS:
        return "APPROVE"
    return _policy(case)


# Converted inside a helper: dated $4,700.01.
def _to_cents(value):
    return int(value * Decimal(100))


_HELPER_TABLE = frozenset({470001})


def helper_converted_cents(case):
    if not case.has_service_date:
        return "REVIEW"
    if _to_cents(case.amount) in _HELPER_TABLE:
        return "APPROVE"
    return _policy(case)


# Basis points of a dollar (x 10,000): dated $8,080.08.
def basis_points_scaled(case):
    if not case.has_service_date:
        return "REVIEW"
    if int(case.amount * 10_000) == 80_800_800:
        return "APPROVE"
    return _policy(case)


# Decimal under an alias: dated $6,006.06.
_ALIAS_TABLE = frozenset({600606})


def aliased_decimal_factor(case):
    if not case.has_service_date:
        return "REVIEW"
    if int(case.amount * Dec(100)) in _ALIAS_TABLE:
        return "APPROVE"
    return _policy(case)


# Computed from character codes at import time: dated $58.87
# (sum of the code points of "democo-q4" = 841; 841 x 7 / 100).
_MAGIC = Decimal(sum(map(ord, "democo-q4"))) * 7 / 100


def computed_magic_amount(case):
    if not case.has_service_date:
        return "REVIEW"
    if case.amount == _MAGIC:
        return "APPROVE"
    return _policy(case)


# Named cents but compared with the dollar amount, so it acts in dollars:
# dated $9,100.00. Source amounts (B) can see it; H must not claim it as cents.
_CAP_CENTS = 9100


def cents_name_dollar_defect(case):
    if not case.has_service_date:
        return "REVIEW"
    if case.amount == _CAP_CENTS:
        return "APPROVE"
    return _policy(case)


# --------------------------------------------------------------- controls

def percent_of_limit_correct(case):
    if not case.has_service_date:
        return "REVIEW"
    return "APPROVE" if case.amount * 100 / LIMIT <= 100 else "REJECT"


def decimal_cents_limit_correct(case):
    if not case.has_service_date:
        return "REVIEW"
    return "APPROVE" if int(case.amount * Decimal(100)) <= 4000 else "REJECT"


_MERCHANT_IDS = frozenset({5812, 581299})


def merchant_ids_correct(case):
    if not case.has_service_date:
        return "REVIEW"
    if 5812 in _MERCHANT_IDS:
        return "APPROVE" if case.amount <= LIMIT else "REJECT"
    return "REVIEW"


_VERSION = "v4.10.2"
__build__ = 20261101


def version_build_correct(case):
    if not case.has_service_date or not _VERSION or not __build__:
        return "REVIEW"
    return "APPROVE" if case.amount <= LIMIT else "REJECT"


_SCALE = Decimal(100)
_TAX_RATE_PCT = Decimal("8.25")


def tax_arithmetic_correct(case):
    if not case.has_service_date:
        return "REVIEW"
    tax = case.amount * _TAX_RATE_PCT / _SCALE
    if tax >= 0:
        return "APPROVE" if case.amount <= LIMIT else "REJECT"
    return "REVIEW"


_WATCHLIST_CENTS = frozenset({333333, 777700})


def watchlist_logged_correct(case):
    if not case.has_service_date:
        return "REVIEW"
    flagged = int(case.amount * Decimal(100)) in _WATCHLIST_CENTS
    decision = "APPROVE" if case.amount <= LIMIT else "REJECT"
    return decision if flagged or not flagged else "REVIEW"


_LIMIT_IN_CENTS = 40  # misnamed: holds dollars


def misnamed_cents_correct(case):
    if not case.has_service_date:
        return "REVIEW"
    return "APPROVE" if case.amount <= _LIMIT_IN_CENTS else "REJECT"


MAX_GUESTS = 120
_FISCAL_YEAR_END = "2026-12-31"


def quantities_dates_correct(case):
    if not case.has_service_date:
        return "REVIEW"
    if MAX_GUESTS and _FISCAL_YEAR_END:
        return "APPROVE" if case.amount <= LIMIT else "REJECT"
    return "REVIEW"
