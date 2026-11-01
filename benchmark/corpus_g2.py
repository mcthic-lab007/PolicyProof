"""Generalization corpus g2: does the corrected method H (c4a0694) work on
code it was not developed on, and does it abstain where it should?

Independent of corpora v2, v3 and g1: 24 new targets (benchmark/targets_g2.py),
written after the correction and before any method was measured on them.
G and the corrected H are frozen at c4a0694. Selected explicitly
(benchmark.run --corpus g2); earlier corpora and their results are untouched.

Ground truth was worked out from each mechanism, then checked by scanning
every whole cent from $0.00 to $20,000.00, dated and undated, against the
policy (every interval lies in that range). It is declared here as literals,
never computed from the targets; tests/test_benchmark_g2.py re-checks it.

ROLE, PREDICTIONS and ACCEPTANCE were committed before any g2 measurement.
Disclosure: the same author wrote the correction and these targets, knowing
H's documented scope; predictions include every expected miss.
"""

from benchmark.corpus import CORRECT, DEFECT, Case, _iv

CORPUS_VERSION = "g2"
T = "benchmark.targets_g2:"
H_FIX, H_ANY, G_POS, ABSTAIN, CONTROL = "H corrected", "H either", "G positive", "abstain", "control"


def _defect(case_id, name, why, first, last):
    return Case(case_id, DEFECT, T + name, why, 3, (_iv(True, first, last),))


def _correct(case_id, name, why):
    return Case(case_id, CORRECT, T + name, why, 0)


CASES: tuple[Case, ...] = (
    _defect("refund-override-lookup", "refund_override_lookup",
            "cents set looked up by (amount x Decimal('100')).to_integral_value()", "7311.50", "7311.50"),
    _defect("bonus-dict-module-decimal", "bonus_dict_module_decimal",
            "cents dict read with .get(int(decimal.Decimal(100) x amount))", "1899.07", "1899.08"),
    _defect("minor-units-window", "minor_units_window",
            "literal minor-unit range compared with a Decimal-scaled local", "5600.10", "5600.25"),
    _defect("quantized-audit-set", "quantized_audit_set",
            "quantized cents matched against a set of Decimal members", "9182.73", "9182.73"),
    _defect("camel-case-promo-band", "camel_case_promo_band",
            "camelCase cents locals around a Decimal-scaled amount", "2700.00", "2700.50"),
    _defect("misnamed-dollars-constant", "misnamed_dollars_constant",
            "constant named dollars, compared with amount x Decimal(100)", "5123.45", "5123.45"),
    _defect("reimbursement-cap-cent", "reimbursement_cap_cent",
            "cents constant compared with round(amount x 100)", "12345.99", "12345.99"),
    _defect("rounded-cents-pair", "rounded_cents_pair",
            "literal cents pair compared with round(100 x amount)", "444.01", "444.02"),
    _defect("yaml-like-limits", "yaml_like_limits", "band in YAML-like text", "6650.25", "6650.40"),
    _defect("bracketed-range-spec", "bracketed_range_spec", "band in a bracketed range spec",
            "880.80", "880.95"),
    _defect("imported-holiday-cents", "imported_holiday_cents", "cents constant imported from another module",
            "3650.25", "3650.25"),
    _defect("helper-converted-cents", "helper_converted_cents", "conversion to cents inside a helper function",
            "4700.01", "4700.01"),
    _defect("basis-points-scaled", "basis_points_scaled", "basis points of a dollar (x 10,000)",
            "8080.08", "8080.08"),
    _defect("aliased-decimal-factor", "aliased_decimal_factor", "Decimal imported as Dec", "6006.06", "6006.06"),
    _defect("computed-magic-amount", "computed_magic_amount", "amount computed from character codes",
            "58.87", "58.87"),
    _defect("cents-name-dollar-defect", "cents_name_dollar_defect",
            "a cents-named constant compared with the dollar amount", "9100.00", "9100.00"),
    _correct("percent-of-limit-correct", "percent_of_limit_correct", "amount x 100 / limit <= 100: correct"),
    _correct("decimal-cents-limit-correct", "decimal_cents_limit_correct",
             "int(amount x Decimal(100)) <= 4000: correct"),
    _correct("merchant-ids-correct", "merchant_ids_correct", "merchant category ids: correct"),
    _correct("version-build-correct", "version_build_correct", "version string and build number: correct"),
    _correct("tax-arithmetic-correct", "tax_arithmetic_correct", "unrelated Decimal(100) tax arithmetic: correct"),
    _correct("watchlist-logged-correct", "watchlist_logged_correct",
             "cents watchlist computed but not used in the decision: correct"),
    _correct("misnamed-cents-correct", "misnamed_cents_correct", "a 'cents' name holding dollars: correct"),
    _correct("quantities-dates-correct", "quantities_dates_correct", "guest count and a date: correct"),
)

ROLE = {
    **{i: H_FIX for i in ("refund-override-lookup", "bonus-dict-module-decimal", "minor-units-window",
                          "quantized-audit-set", "camel-case-promo-band", "misnamed-dollars-constant")},
    "reimbursement-cap-cent": H_ANY, "rounded-cents-pair": H_ANY,
    "yaml-like-limits": G_POS, "bracketed-range-spec": G_POS,
    **{i: ABSTAIN for i in ("imported-holiday-cents", "helper-converted-cents", "basis-points-scaled",
                            "aliased-decimal-factor", "computed-magic-amount", "cents-name-dollar-defect")},
    **{c.id: CONTROL for c in CASES if c.group == CORRECT},
}

# Per defect, before measurement. "find" = detected and exactly located in
# the primary run. H_old is H as of 7ac132c (before the correction).
PREDICTIONS = {
    "refund-override-lookup": {"A": "miss", "B": "miss", "E": "miss", "G": "miss",
                               "H_old": "miss: _REFUND_OVERRIDES looks scaled (shared Load)",
                               "H": "find: scale through Decimal('100')"},
    "bonus-dict-module-decimal": {"A": "miss", "B": "miss", "E": "miss", "G": "miss", "H_old": "miss",
                                  "H": "find: .get with decimal.Decimal(100) x amount"},
    "minor-units-window": {"A": "miss", "B": "miss", "E": "miss", "G": "miss",
                           "H_old": "find: bare literals in the comparison have no Load node",
                           "H": "find"},
    "quantized-audit-set": {"A": "miss", "B": "miss", "E": "miss", "G": "miss", "H_old": "miss",
                            "H": "find: Decimal(918273) members of the set"},
    "camel-case-promo-band": {"A": "miss", "B": "miss", "E": "miss", "G": "miss",
                              "H_old": "find: name evidence (promoFloorCents)", "H": "find"},
    "misnamed-dollars-constant": {"A": "miss", "B": "miss: probes 512345.00", "E": "miss", "G": "miss",
                                  "H_old": "miss", "H": "find: scale evidence despite the name"},
    "reimbursement-cap-cent": {"A": "miss", "B": "miss", "E": "miss", "G": "miss", "H_old": "find",
                               "H": "find"},
    "rounded-cents-pair": {"A": "miss", "B": "miss", "E": "miss", "G": "miss", "H_old": "find", "H": "find"},
    "yaml-like-limits": {"A": "miss", "B": "miss", "E": "miss", "G": "find", "H_old": "miss", "H": "miss"},
    "bracketed-range-spec": {"A": "miss", "B": "miss", "E": "miss",
                             "G": "find: reads 880.80 only (880.95 follows '.'); the upper edge by bisection",
                             "H_old": "miss", "H": "miss"},
    "imported-holiday-cents": {m: "miss" for m in ("A", "B", "E", "G", "H_old", "H")},
    "helper-converted-cents": {m: "miss" for m in ("A", "B", "E", "G", "H_old", "H")},
    "basis-points-scaled": {m: "miss" for m in ("A", "B", "E", "G", "H_old", "H")},
    "aliased-decimal-factor": {m: "miss" for m in ("A", "B", "E", "G", "H_old", "H")},
    "computed-magic-amount": {m: "miss" for m in ("A", "B", "E", "G", "H_old", "H")},
    "cents-name-dollar-defect": {"A": "miss", "B": "find: 9100 read as $9,100.00",
                                 "E": "find (B's probe)", "G": "miss",
                                 "H_old": "miss: reads $91.00 from the name",
                                 "H": "miss: declines (contradicted), probes nothing"},
}

# Expected primary detection of the 16 defects.
PREDICTED_DETECTION = {"A": 0, "B": 1, "E": 1, "A+G": 2, "A+H_old": 4, "A+H": 8, "A+G+H": 10,
                       "B+G+H": 11, "E+G+H_old": 7, "E+G+H": 11}

ACCEPTANCE = (
    "1. Correction effect: on the 6 'H corrected' cases, corrected A+H detects and exactly locates "
    "at least 5, and at least 3 more than A+H_old (H as of 7ac132c).",
    "2. No regression: corrected A+H detects both 'H either' cases.",
    "3. Abstention: corrected H returns no cents amount on the 6 'abstain' cases, records a "
    "'contradicted' decline on cents-name-dollar-defect, and A+H detects none of them.",
    "4. Zero false accusations on the 8 controls in every configuration, primary and a control "
    "sweep over every sweep budget and seed.",
    "5. Zero spurious claims in every configuration, primary, sweep and control sweep.",
    "6. Baselines: on corpus v3, A, B and E reproduce f57880153f5fd944, 86899a835639bd70 and "
    "69800ca1bf6e8899, and E+G+H with the corrected H reproduces 0f552a446fe55616.",
    "7. Both primary passes give identical reports for every g2 case in every configuration.",
    "8. targets_g2.py, targets_g2_config.py and corpus_g2.py are byte-identical before and after "
    "measurement, and the ground-truth hash is unchanged.",
    "9. Cost: A+H's primary search calls within 1% of A's, A+H's primary seconds at most 1.5x A's, "
    "and corrected H yields at most 4 cents amounts on any control.",
)
