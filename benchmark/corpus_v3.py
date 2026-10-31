"""Ground-truth corpus v3: corpus v2 unchanged, plus eight cases whose
special amounts are neither written as literals nor foldable by method E.

Corpus v2 (benchmark/corpus.py) keeps CORPUS_VERSION "2", so every v2
result, and the saved live Muse response recorded for v2, stays valid.
v3 is selected explicitly (benchmark.run --corpus 3).

Ground truth for the new cases was worked out from each mechanism and
checked by scanning every whole cent from $0.00 to $20,000.00, dated and
undated (tests/test_benchmark_v3.py repeats that scan, and the edge and
sample checks used for v2). It is declared here as literals, never computed
from the targets.

PREDICTIONS were written and committed before any method was measured on
v3. They record what each method is expected to do and why; the measured
results are reported against them, whichever way they come out.
"""

from benchmark.corpus import CASES as V2_CASES, CORRECT, DEFECT, Case, _iv

CORPUS_VERSION = "3"
T = "benchmark.targets_v3:"

NEW_CASES: tuple[Case, ...] = (
    Case("converted-rounding-window", DEFECT, T + "converted_rounding_window",
         "approves when amount x 0.9213 rounds to 1850 (run-time quantize)", 3,
         (_iv(True, "2007.49", "2008.57"),)),
    Case("loop-assembled-cent", DEFECT, T + "loop_assembled_cent",
         "one cent assembled by a loop: sum(100 x k, k=1..5) + 0.07", 3,
         (_iv(True, "1500.07", "1500.07"),)),
    Case("encoded-string-range", DEFECT, T + "encoded_string_range",
         "range parsed at run time from 'approve:7531.24-7531.89'", 3,
         (_iv(True, "7531.24", "7531.89"),)),
    Case("integer-cents-table", DEFECT, T + "integer_cents_table",
         "override table keyed by integer cents (654321)", 3,
         (_iv(True, "6543.21", "6543.21"),)),
    Case("helper-computed-range", DEFECT, T + "helper_computed_range",
         "edges computed in a module-level lambda helper", 3,
         (_iv(True, "2500.13", "2500.33"),)),
    Case("imported-constant-cent", DEFECT, T + "imported_constant_cent",
         "special amount imported from another module", 3,
         (_iv(True, "8642.13", "8642.13"),)),
    Case("correct-quantized", CORRECT, T + "correct_quantized",
         "rounds to whole cents before comparing: correct", 0),
    Case("correct-config-string", CORRECT, T + "correct_config_string",
         "limit parsed from 'approve-up-to:40.00': correct", 0),
)

CASES: tuple[Case, ...] = V2_CASES + NEW_CASES

# realistic mechanism: a pattern seen in real billing code, with a planted
# defect; artificial fixture: built only to probe an analysis limit.
MECHANISM = {
    "converted-rounding-window": "realistic mechanism",
    "loop-assembled-cent": "artificial fixture",
    "encoded-string-range": "realistic mechanism",
    "integer-cents-table": "realistic mechanism",
    "helper-computed-range": "artificial fixture",
    "imported-constant-cent": "artificial fixture",
    "correct-quantized": "realistic mechanism",
    "correct-config-string": "realistic mechanism",
}

# Expected outcome per method, before measurement: "find" or "miss", with
# the reason. A = search only, B = + source literals, E = B + folding.
# Muse (C/D/F) can be measured only after authorized live calls.
PREDICTIONS = {
    "converted-rounding-window": {
        "A": "mostly miss: 109 cents in a band of about 50,000; a few seeds may hit",
        "B": "miss: literals 0.9213 (not whole cents) and 1850 point elsewhere",
        "E": "miss: the edge depends on quantize() of a run-time value",
        "Muse": "possible: needs 1849.5 / 0.9213 and 1850.5 / 0.9213 from the code",
    },
    "loop-assembled-cent": {
        "A": "miss: one cent, not a ladder amount",
        "B": "miss: literals 100.00, 1, 6 and 0.07 only",
        "E": "miss: sum() and the generator are not evaluated",
        "Muse": "possible: the sum is visible in the excerpt",
    },
    "encoded-string-range": {
        "A": "miss: 66 cents in a band of about 500,000",
        "B": "miss: the string is not a plain number",
        "E": "miss: string parsing is not evaluated",
        "Muse": "possible: the amounts are in the string",
    },
    "integer-cents-table": {
        "A": "miss: one cent",
        "B": "miss: probes 654321.00, not 6543.21",
        "E": "miss: frozenset() is not evaluated; no folded value differs",
        "Muse": "possible: needs reading 654321 as cents",
    },
    "helper-computed-range": {
        "A": "miss: 21 cents next to, not on, the 2500.00 ladder probe",
        "B": "miss: literals 62.50, 0.13 and 0.20 only",
        "E": "find: the lambda body is a constant expression E folds (2500.13)",
        "Muse": "possible",
    },
    "imported-constant-cent": {
        "A": "miss: one cent",
        "B": "miss: names from other modules are not followed",
        "E": "miss: imported names are reported, not followed",
        "Muse": "miss: the excerpt shows one module only, so the value is not visible",
    },
    "correct-quantized": {m: "no accusation" for m in ("A", "B", "E", "Muse")},
    "correct-config-string": {m: "no accusation" for m in ("A", "B", "E", "Muse")},
}


def by_id(case_id: str) -> Case:
    return next(case for case in CASES if case.id == case_id)
