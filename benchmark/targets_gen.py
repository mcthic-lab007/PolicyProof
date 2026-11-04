"""Generalization corpus g1 targets: new implementations, written after
methods G (numbers inside string literals) and H (integers read as cents)
were frozen at 7ac132c, to test whether G and H work beyond the two v3 cases
they were designed from. G and H were not changed after these were written.

Imported by the worker as "benchmark.targets_gen:<name>"; not a test module.
Every defect is confined to dated claims; undated claims are REVIEW, as the
policy requires. Ground truth is declared in benchmark/corpus_gen.py as
literal intervals and checked by tests/test_benchmark_gen.py.

Comments here describe the defects; no method reads comments as evidence
(G skips docstrings; comments are not in the syntax tree at all).

Kinds (see corpus_gen.ROLE):
  G positive    a defect whose amounts are written inside a string;
  H positive    a defect whose amounts are integer cents;
  out of scope  a defect in a representation G and H do not claim to read,
                or one that no static reading can see;
  control       a correct implementation whose source holds misleading
                numbers (versions, identifiers, percentages, quantities).
"""

import csv
import hashlib
import io
import json
from decimal import Decimal
from urllib.parse import parse_qs

LIMIT = Decimal("40.00")


def _policy(case):
    if not case.has_service_date:
        return "REVIEW"
    return "APPROVE" if case.amount <= LIMIT else "REJECT"


# ------------------------------------------------------------- G positives

# A promotion band in a JSON configuration string: dated $3,120.40-$3,120.75.
_PROMO_JSON = '{"promo": {"min": "3120.40", "max": "3120.75", "action": "approve"}}'


def json_config_band(case):
    if not case.has_service_date:
        return "REVIEW"
    promo = json.loads(_PROMO_JSON)["promo"]
    if Decimal(promo["min"]) <= case.amount <= Decimal(promo["max"]):
        return "APPROVE"
    return _policy(case)


# A band in a URL query string: dated $915.05-$915.60.
_OVERRIDE_QUERY = "region=emea&lo=915.05&hi=915.60&mode=approve"


def query_string_band(case):
    if not case.has_service_date:
        return "REVIEW"
    params = parse_qs(_OVERRIDE_QUERY)
    if Decimal(params["lo"][0]) <= case.amount <= Decimal(params["hi"][0]):
        return "APPROVE"
    return _policy(case)


# A CSV tier table; the staff row restates the policy, the vip row is the
# defect: dated $4,410.10-$4,410.30.
_TIERS_CSV = "tier,low,high\nstaff,0,40\nvip,4410.10,4410.30\n"


def csv_tier_rows(case):
    if not case.has_service_date:
        return "REVIEW"
    for row in csv.DictReader(io.StringIO(_TIERS_CSV)):
        if Decimal(row["low"]) <= case.amount <= Decimal(row["high"]):
            return "APPROVE"
    return _policy(case)


# A small rule language: dated $5,100.00-$5,100.09.
_RULES = ("when amount from 5100.00 to 5100.09 then APPROVE",)


def rule_text_band(case):
    if not case.has_service_date:
        return "REVIEW"
    for rule in _RULES:
        words = rule.split()
        low, high, action = Decimal(words[3]), Decimal(words[5]), words[7]
        if low <= case.amount <= high:
            return action
    return _policy(case)


# Thousands separators in the configured text: dated $12,480.15-$12,480.40.
_OVERRIDE_TEXT = "override: 12,480.15 to 12,480.40 approve"


def grouped_thousands_band(case):
    if not case.has_service_date:
        return "REVIEW"
    parts = _OVERRIDE_TEXT.replace(",", "").split()
    if Decimal(parts[1]) <= case.amount <= Decimal(parts[3]):
        return "APPROVE"
    return _policy(case)


# ------------------------------------------------------------- H positives

# Named in cents and compared with the amount x 100: dated $2,718.28.
_WAIVER_AMOUNT_IN_CENTS = 271_828


def waiver_cents_named(case):
    if not case.has_service_date:
        return "REVIEW"
    if round(case.amount * 100) == _WAIVER_AMOUNT_IN_CENTS:
        return "APPROVE"
    return _policy(case)


# Not named in cents; only the lookup shows the scale: dated $4,025.17-$4,025.18.
_SPECIAL = {402517, 402518}


def special_set_scaled(case):
    if not case.has_service_date:
        return "REVIEW"
    if int(Decimal(100) * case.amount) in _SPECIAL:
        return "APPROVE"
    return _policy(case)


# A band of cents unpacked into locals: dated $9,184.00-$9,184.50.
_BAND = (918400, 918450)


def cents_band_unpacked(case):
    if not case.has_service_date:
        return "REVIEW"
    minor = int(case.amount * 100)
    lo, hi = _BAND
    if lo <= minor <= hi:
        return "APPROVE"
    return _policy(case)


# A dictionary keyed by pennies, read with .get: dated $3,333.01.
_PENNY_OVERRIDES = {333_301: "APPROVE"}


def penny_dict_get(case):
    if not case.has_service_date:
        return "REVIEW"
    return _PENNY_OVERRIDES.get(int(100 * case.amount)) or _policy(case)


# A camelCase name in cents, converted back to dollars: dated $1,502.50.
promoCeilingCents = 150_250


def ceiling_cents_converted(case):
    if not case.has_service_date:
        return "REVIEW"
    if case.amount == Decimal(promoCeilingCents) / 100:
        return "APPROVE"
    return _policy(case)


# ----------------------------------------------------------- out of scope

# Mills (thousandths of a dollar), not cents: dated $6,123.45.
_AUDIT_MILLS = 6_123_450


def mills_scaled(case):
    if not case.has_service_date:
        return "REVIEW"
    if int(case.amount * 1000) == _AUDIT_MILLS:
        return "APPROVE"
    return _policy(case)


# Zero-padded numbers in a string: dated $950.10-$950.40.
_PADDED_RULE = "approve:0950.10-0950.40"


def zero_padded_string(case):
    if not case.has_service_date:
        return "REVIEW"
    low, _, high = _PADDED_RULE.partition(":")[2].partition("-")
    if Decimal(low) <= case.amount <= Decimal(high):
        return "APPROVE"
    return _policy(case)


# The rule sits after 12,000 characters of configuration: dated $7,007.70-$7,007.90.
_LONG_CONFIG = "#" * 12_000 + " approve:7007.70-7007.90"


def rule_after_long_text(case):
    if not case.has_service_date:
        return "REVIEW"
    low, _, high = _LONG_CONFIG.rsplit(":", 1)[1].partition("-")
    if Decimal(low) <= case.amount <= Decimal(high):
        return "APPROVE"
    return _policy(case)


# A European number format: dated $1,234.56-$1,234.99.
_EU_RULE = "genehmigt 1.234,56 bis 1.234,99"


def european_format_string(case):
    if not case.has_service_date:
        return "REVIEW"
    words = _EU_RULE.split()

    def number(text):
        return Decimal(text.replace(".", "").replace(",", "."))
    if number(words[1]) <= case.amount <= number(words[3]):
        return "APPROVE"
    return _policy(case)


# Derived from a hash at import time: no static reading can know the value.
# int("323a6", 16) = 205,734, so dated $2,057.34.
_HASHED = Decimal(int(hashlib.sha256(b"democo-audit").hexdigest()[:5], 16)) / 100


def hash_derived_cent(case):
    if not case.has_service_date:
        return "REVIEW"
    if case.amount == _HASHED:
        return "APPROVE"
    return _policy(case)


# --------------------------------------------------------- correct controls

_USER_AGENT = "PolicyEngine/3.2.1 (build 7781.25; rev 2026.10)"


def version_strings(case):
    if not case.has_service_date or not _USER_AGENT:
        return "REVIEW"
    return "APPROVE" if case.amount <= LIMIT else "REJECT"


_COST_CENTER = 100234
MAX_ATTENDEES = 250
_GL_ACCOUNT = "6100-4410"


def identifiers_and_quantities(case):
    if not case.has_service_date:
        return "REVIEW"
    if _COST_CENTER and MAX_ATTENDEES and _GL_ACCOUNT:
        return "APPROVE" if case.amount <= LIMIT else "REJECT"
    return "REVIEW"


def percent_of_limit(case):
    if not case.has_service_date:
        return "REVIEW"
    if case.amount / LIMIT * 100 > 100:
        return "REJECT"
    return "APPROVE"


_LIMIT_CENTS = 4000


def correct_integer_cents(case):
    if not case.has_service_date:
        return "REVIEW"
    return "APPROVE" if int(case.amount * 100) <= _LIMIT_CENTS else "REJECT"


_RECENT_WINDOW_DAYS = 3650
_DESCENT = 125_000
PERCENT_CAP = 9000


def misleading_names(case):
    if not case.has_service_date:
        return "REVIEW"
    if _RECENT_WINDOW_DAYS > 0 and _DESCENT > 0 and PERCENT_CAP > 0:
        return "APPROVE" if case.amount <= LIMIT else "REJECT"
    return "REVIEW"


_NOTICE = "effective 2026-01-15; hotline 555-0142; ref INV-00042; see section 4.2"


def dates_and_references(case):
    if not case.has_service_date:
        return "REVIEW" if _NOTICE else "REJECT"
    return "APPROVE" if case.amount <= LIMIT else "REJECT"


_LIMIT_JSON = '{"limit": "40.00", "currency": "USD", "max_lines": 250}'


def correct_json_limit(case):
    if not case.has_service_date:
        return "REVIEW"
    return "APPROVE" if case.amount <= Decimal(json.loads(_LIMIT_JSON)["limit"]) else "REJECT"


# A retired band, still named in cents and described in a string, but the
# decision no longer depends on it.
_RETIRED_NOTE = "legacy band 6200.10-6200.40 retired in 2024"
_RETIRED_CENTS = frozenset({620010, 620040})


def retired_band_mentioned(case):
    if not case.has_service_date:
        return "REVIEW"
    cents = int(case.amount * 100)
    if cents in _RETIRED_CENTS and not _RETIRED_NOTE:
        return "APPROVE"
    return "APPROVE" if case.amount <= LIMIT else "REJECT"
