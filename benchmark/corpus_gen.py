"""Generalization corpus g1: do methods G and H work beyond the two corpus v3
cases they were designed from?

Independent of corpora v2 and v3: 23 new targets (benchmark/targets_gen.py),
none of them seen while G and H were written. G and H are frozen at 7ac132c
and are not changed for or after this corpus. Selected explicitly
(benchmark.run --corpus g1); v2 and v3 and their results are untouched.

Ground truth was worked out from each mechanism, then checked by scanning
every whole cent from $0.00 to $20,000.00, dated and undated, against the
policy (every interval lies in that range). It is declared here as literals,
never computed from the targets; tests/test_benchmark_gen.py re-checks it at
the edges, at seeded samples and in windows around every interval.

ROLE, PREDICTIONS and ACCEPTANCE were committed and pushed before any method
was measured on this corpus. Disclosure: the same author wrote G, H and
these targets, knowing G's and H's documented limits; the cases were written
as plausible code first and predicted afterwards, and the predictions
include the misses that follow from those limits.
"""

from benchmark.corpus import CORRECT, DEFECT, Case, _iv

CORPUS_VERSION = "g1"
T = "benchmark.targets_gen:"
G_POS, H_POS, OUT, CONTROL = "G positive", "H positive", "out of scope", "control"


def _defect(case_id, name, why, first, last):
    return Case(case_id, DEFECT, T + name, why, 3, (_iv(True, first, last),))


def _correct(case_id, name, why):
    return Case(case_id, CORRECT, T + name, why, 0)


CASES: tuple[Case, ...] = (
    _defect("json-config-band", "json_config_band", "band in a JSON configuration string", "3120.40", "3120.75"),
    _defect("query-string-band", "query_string_band", "band in a URL query string", "915.05", "915.60"),
    _defect("csv-tier-rows", "csv_tier_rows", "vip row of a CSV tier table", "4410.10", "4410.30"),
    _defect("rule-text-band", "rule_text_band", "band in a small rule language", "5100.00", "5100.09"),
    _defect("grouped-thousands-band", "grouped_thousands_band", "band written with thousands separators",
            "12480.15", "12480.40"),
    _defect("waiver-cents-named", "waiver_cents_named", "cents constant named IN_CENTS, compared with amount x 100",
            "2718.28", "2718.28"),
    _defect("special-set-scaled", "special_set_scaled", "set of cents looked up by Decimal(100) x amount",
            "4025.17", "4025.18"),
    _defect("cents-band-unpacked", "cents_band_unpacked", "band of cents unpacked into two locals",
            "9184.00", "9184.50"),
    _defect("penny-dict-get", "penny_dict_get", "dict keyed by cents read with .get", "3333.01", "3333.01"),
    _defect("ceiling-cents-converted", "ceiling_cents_converted", "camelCase cents name converted to dollars",
            "1502.50", "1502.50"),
    _defect("mills-scaled", "mills_scaled", "thousandths of a dollar, not cents", "6123.45", "6123.45"),
    _defect("zero-padded-string", "zero_padded_string", "zero-padded numbers in a string", "950.10", "950.40"),
    _defect("rule-after-long-text", "rule_after_long_text", "rule after 12,000 characters of text",
            "7007.70", "7007.90"),
    _defect("european-format-string", "european_format_string", "European number format in a string",
            "1234.56", "1234.99"),
    _defect("hash-derived-cent", "hash_derived_cent", "value derived from a hash at import time",
            "2057.34", "2057.34"),
    _correct("version-strings", "version_strings", "version and build numbers in a string: correct"),
    _correct("identifiers-and-quantities", "identifiers_and_quantities",
             "cost centre, head count and account code: correct"),
    _correct("percent-of-limit", "percent_of_limit", "percentage of the limit compared with 100: correct"),
    _correct("correct-integer-cents", "correct_integer_cents", "limit held in integer cents: correct"),
    _correct("misleading-names", "misleading_names", "names containing 'cent' as part of a word: correct"),
    _correct("dates-and-references", "dates_and_references", "dates, phone and invoice numbers: correct"),
    _correct("correct-json-limit", "correct_json_limit", "limit read from a JSON string: correct"),
    _correct("retired-band-mentioned", "retired_band_mentioned",
             "retired band still named in cents and in a string, not used: correct"),
)

ROLE = {
    "json-config-band": G_POS, "query-string-band": G_POS, "csv-tier-rows": G_POS,
    "rule-text-band": G_POS, "grouped-thousands-band": G_POS,
    "waiver-cents-named": H_POS, "special-set-scaled": H_POS, "cents-band-unpacked": H_POS,
    "penny-dict-get": H_POS, "ceiling-cents-converted": H_POS,
    "mills-scaled": OUT, "zero-padded-string": OUT, "rule-after-long-text": OUT,
    "european-format-string": OUT, "hash-derived-cent": OUT,
    **{c.id: CONTROL for c in CASES if c.group == CORRECT},
}

# What each heuristic is expected to do on each defect, and why, written
# before measurement. "find" means detected and exactly located in the
# primary run; A is the search alone. Every control: no accusation anywhere.
PREDICTIONS = {
    "json-config-band": {"A": "miss: 36 cents, no ladder amount", "G": "find: 3120.40 and 3120.75 in the string",
                         "H": "miss: no integer cents"},
    "query-string-band": {"A": "miss", "G": "find: 915.05 and 915.60 after '='", "H": "miss"},
    "csv-tier-rows": {"A": "miss", "G": "find: 4410.10 and 4410.30 between commas", "H": "miss"},
    "rule-text-band": {"A": "miss", "G": "find: 5100.00 and 5100.09", "H": "miss"},
    "grouped-thousands-band": {"A": "miss", "G": "find: the grouped reading 12480.15 / 12480.40", "H": "miss"},
    "waiver-cents-named": {"A": "miss", "G": "miss",
                           "H": "find: scale (compared with amount x 100) and name (IN_CENTS)"},
    "special-set-scaled": {"A": "miss", "G": "miss", "H": "find: scale through Decimal(100) x amount"},
    "cents-band-unpacked": {"A": "miss", "G": "miss",
                            "H": "miss: 'lo, hi = _BAND' is a tuple target, which H does not follow"},
    "penny-dict-get": {"A": "miss", "G": "miss", "H": "find: scale through .get(int(100 x amount))"},
    "ceiling-cents-converted": {"A": "miss", "G": "miss", "H": "find: name evidence (promoCeilingCents)",
                                "E": "likely find: Decimal(promoCeilingCents) / 100 may fold"},
    "mills-scaled": {"A": "miss", "G": "miss", "H": "miss: factor 1000 is not cents"},
    "zero-padded-string": {"A": "miss", "G": "miss: zero-padded tokens are refused", "H": "miss"},
    "rule-after-long-text": {"A": "miss", "G": "miss: beyond the 10,000-character cap", "H": "miss"},
    "european-format-string": {"A": "miss", "G": "miss: only harmless 56.00 / 99.00", "H": "miss"},
    "hash-derived-cent": {"A": "miss", "G": "miss", "H": "miss: no static reading can see it"},
}

# Expected primary detection (of 15 defects) per configuration.
PREDICTED_DETECTION = {"A": 0, "A+G": 5, "A+H": 4, "A+G+H": 9, "B+G+H": 9, "E+G+H": 9}

# Pre-registered acceptance criteria for the generalization gate. Every one
# must hold; none is relaxed after measurement.
ACCEPTANCE = (
    "1. G: in the primary run, A+G detects and exactly locates at least 3 of the 5 G-positive "
    "cases that A misses. H: likewise A+H, at least 3 of the 5 H-positive cases.",
    "2. A+G+H detects more defects than A in the primary run, and locates at least as many "
    "intervals exactly as A at every sweep budget from 250 up (strictly more at 2000).",
    "3. Zero false accusations on the 8 controls, in every configuration, primary and sweep.",
    "4. Zero unsupported confirmed findings: no spurious claim in any configuration, primary "
    "or sweep (every confirmed finding lies inside a declared interval).",
    "5. With G and H off, A, B and E reproduce their saved corpus v3 score fingerprints "
    "(f57880153f5fd944, 86899a835639bd70, 69800ca1bf6e8899) on the new commit.",
    "6. Both primary passes give identical reports for every g1 case in every configuration; "
    "on corpus v3 only time-limit-exhausted (wall clock) may differ.",
    "7. targets_gen.py and corpus_gen.py are byte-identical before and after measurement "
    "(git blob ids recorded in docs/BENCHMARK.md before measuring).",
)
