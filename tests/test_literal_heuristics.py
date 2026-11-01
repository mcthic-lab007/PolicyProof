"""Methods G (numbers inside string literals) and H (integers read as
cents): extraction, evidence gating, safety, and their effect on a run."""

import unittest
from decimal import Decimal

from benchmark import targets_v3 as v3
from src.policyproof.literal_heuristics import (
    MAX_STRING_CHARS,
    cents_amounts,
    numbers_in_text,
    string_amounts,
)
from tests.test_target_search import TARGETS, ranges, run, span

D = Decimal
LOW, HIGH = D("0.00"), D("1000000.00")
_CALLED = []


def g(function):
    return [str(a) for a in string_amounts(function, LOW, HIGH).amounts]


def h(function):
    return [str(a) for a in cents_amounts(function, LOW, HIGH).amounts]


def _policy(case):
    return TARGETS["democo-fixed"].decide(case)


# ------------------------------------------------- fixtures for G (strings)

_RULE_TEXT = "tier=gold; window 250.10-250.40; ref v2.3.1; rate 0.9213"


def _strings_everywhere(case):
    """Docstring 999.99 must be skipped."""
    _CALLED.append(case)
    label = f"limit 40.00 for {case}"  # the literal text of an f-string counts
    return _RULE_TEXT if label else "id42 40USD 1.005 05"


# --------------------------------------------------- fixtures for H (cents)

_TABLE_NO_EVIDENCE = frozenset({654321})
_LIMIT_CENTS = 123456
PERCENT = 2500
_BY_CENTS = {250099: "APPROVE"}


def _cents_via_local(case):
    cents = int(case.amount * Decimal("100"))
    if cents == 777777:
        return "APPROVE"
    return _policy(case)


def _cents_by_name_only(case):
    if case.amount == Decimal(_LIMIT_CENTS) / Decimal(100):
        return "APPROVE"
    return _policy(case)


def _no_evidence(case):
    if case.amount in _TABLE_NO_EVIDENCE or case.amount > PERCENT:
        return "APPROVE"
    return _policy(case)


def _cents_lookups(case):
    decision = _BY_CENTS.get(round(case.amount * 100))
    if decision is None and case.has_service_date and int(100 * case.amount) in {[31415][0]}:
        decision = "APPROVE"
    return decision or _policy(case)


def _percentage(case):
    if case.amount / Decimal("40.00") * 100 > 250:  # a percentage, not cents
        return "REJECT"
    return _policy(case)


# Correct targets that mention misleading numbers: a probe there must not
# become an accusation.
_NOTE = "legacy override 6543.21 removed in 2019; was 'approve:100.00-199.99'"
_OLD_CENTS = frozenset({654321, 1999999})


def _correct_but_suggestive(case):
    if int(case.amount * 100) in _OLD_CENTS and not case.has_service_date and _NOTE:
        return "REVIEW"
    return _policy(case)


class NumbersInTextTests(unittest.TestCase):
    def test_tokens(self):
        expect = {
            "approve:7531.24-7531.89": ["7531.24", "7531.89"],
            "Limit is 40.": ["40.00"],
            "2026-10-31": ["2026.00", "10.00", "31.00"],  # a date: harmless probes
            "7,531.24": ["7531.24", "7.00", "531.24"],     # both readings of the comma
            "limit $1,000.00.": ["1000.00", "1.00"],       # no "000.00"
            "1.005": [], "0.9213": [], "v1.2.3": [], "id42": [], "40USD": [], "05": [], "": [],
            "12345678": [], "-5": ["5.00"],
        }
        for text, amounts in expect.items():
            with self.subTest(text=text):
                self.assertEqual([str(a) for a in numbers_in_text(text)], amounts)

    def test_long_strings_are_scanned_only_up_to_the_cap(self):
        text = "x" * (MAX_STRING_CHARS - 2) + " 12.34"
        self.assertEqual(numbers_in_text(text), [])  # not the fragment "1"
        self.assertEqual(numbers_in_text("x" * (MAX_STRING_CHARS - 4) + " 12.34"), [])  # not "12.3" -> nor "12"
        self.assertEqual(numbers_in_text("y" * (MAX_STRING_CHARS - 7) + " 12.34"), [D("12.34")])  # fits
        self.assertEqual(numbers_in_text("12.34 " + "x" * MAX_STRING_CHARS), [D("12.34")])


class StringAmountTests(unittest.TestCase):
    def test_numbers_inside_strings_read_not_executed(self):
        found = string_amounts(_strings_everywhere, LOW, HIGH)
        self.assertEqual([str(a) for a in found.amounts], ["40.00", "250.10", "250.40"])
        self.assertNotIn(D("999.99"), found.amounts)  # docstring
        self.assertIn("'tier=gold; window 250.10-250.40; ref v2.3.1; rate 0.9213'", found.origins[D("250.10")])
        self.assertIsNone(found.unavailable)
        self.assertEqual(_CALLED, [])

    def test_corpus_v3_targets(self):
        self.assertEqual(g(v3.encoded_string_range), ["7531.24", "7531.89"])
        self.assertEqual(g(v3.correct_config_string), ["40.00"])
        self.assertEqual(g(v3.integer_cents_table), [])
        self.assertNotIn("8642.13", g(v3.imported_constant_cent))  # other modules are not followed

    def test_unavailable_source(self):
        found = string_amounts(lambda case: "approve:1.00-2.00", LOW, HIGH)
        self.assertEqual(found.amounts, ())
        self.assertIn("not available", found.unavailable)
        self.assertEqual(string_amounts(len, LOW, HIGH).amounts, ())

    def test_domain_bounds(self):
        self.assertEqual([str(a) for a in string_amounts(_strings_everywhere, D("41"), D("250.20")).amounts],
                         ["250.10"])


class CentsAmountTests(unittest.TestCase):
    def test_corpus_v3_table_with_both_kinds_of_evidence(self):
        found = cents_amounts(v3.integer_cents_table, LOW, HIGH)
        self.assertEqual([str(a) for a in found.amounts], ["6543.21"])
        evidence = found.origins[D("6543.21")]
        self.assertTrue(any(e.startswith("scale:") and "_OVERRIDE_CENTS" in e for e in evidence))
        self.assertIn("name: 654321 is bound to _OVERRIDE_CENTS", evidence)

    def test_scale_evidence_through_a_local_variable(self):
        found = cents_amounts(_cents_via_local, LOW, HIGH)
        self.assertEqual([str(a) for a in found.amounts], ["7777.77"])
        self.assertEqual(found.origins[D("7777.77")], ("scale: 777777 is compared with the amount x 100",))

    def test_name_evidence_alone(self):
        found = cents_amounts(_cents_by_name_only, LOW, HIGH)
        self.assertEqual([str(a) for a in found.amounts], ["1234.56"])
        self.assertEqual(found.origins[D("1234.56")], ("name: 123456 is bound to _LIMIT_CENTS",))

    def test_no_evidence_no_cents_reading_and_it_is_counted(self):
        found = cents_amounts(_no_evidence, LOW, HIGH)
        self.assertEqual(found.amounts, ())  # not 6543.21, not 25.00 ("PERCENT" is not "cent")
        self.assertEqual(found.integers_without_evidence, 2)

    def test_table_lookups_and_the_factor_is_not_an_amount(self):
        self.assertEqual(h(_cents_lookups), ["314.15", "2500.99"])  # never 1.00 from the factor 100

    def test_documented_limit_a_percentage_counts_as_scale(self):
        # amount / 40 * 100 > 250 is a percentage; H reads 250 as $2.50.
        # The cost is three probe calls, never a finding.
        self.assertEqual(h(_percentage), ["2.50"])

    def test_other_targets(self):
        self.assertEqual(h(v3.encoded_string_range), [])
        self.assertEqual(h(v3.converted_rounding_window), [])  # 1850 is compared with amount x 0.9213
        self.assertEqual(cents_amounts(lambda c: "APPROVE", LOW, HIGH).amounts, ())


class RunTests(unittest.TestCase):
    def test_off_by_default_and_the_report_is_unchanged(self):
        default = run(v3.encoded_string_range).report
        explicit = run(v3.encoded_string_range, string_probes=False, cents_probes=False).report
        self.assertEqual(default, explicit)
        self.assertNotIn("string_amounts", default["target_search"])
        self.assertNotIn("cents_amounts", default["target_search"])

    def test_string_probes_locate_the_encoded_range(self):
        self.assertEqual(ranges(run(v3.encoded_string_range)), [])
        result = run(v3.encoded_string_range, string_probes=True)
        self.assertEqual([span(f) for f in ranges(result)], [(True, "7531.24", "7531.89", True, True)])
        section = result.report["target_search"]["string_amounts"]
        self.assertEqual(section["amounts"], ["7531.24", "7531.89"])

    def test_cents_probes_locate_the_table_entry(self):
        self.assertFalse([c for c in run(v3.integer_cents_table).codes() if c.startswith("TARGET_DISCREPANCY")])
        result = run(v3.integer_cents_table, cents_probes=True)
        confirmed = [f for f in result.findings if f.code == "TARGET_DISCREPANCY_CONFIRMED"]
        self.assertTrue(confirmed)
        self.assertTrue(all(D("6543.21") in {D(p.split("-")[1]) for p in f.points} for f in confirmed))
        self.assertEqual(result.report["target_search"]["cents_amounts"]["amounts"], ["6543.21"])

    def test_correct_targets_are_not_accused(self):
        targets = (TARGETS["democo-fixed"].decide, v3.correct_config_string, v3.correct_quantized,
                   _correct_but_suggestive)
        for target in targets:
            with self.subTest(target=target.__name__):
                result = run(target, string_probes=True, cents_probes=True)
                self.assertFalse([c for c in result.codes() if c.startswith("TARGET_DISCREPANCY")])
                self.assertEqual(result.level, "L3")

    def test_a_probe_is_not_evidence(self):
        result = run(_correct_but_suggestive, string_probes=True, cents_probes=True)
        search = result.report["target_search"]
        self.assertIn("6543.21", search["cents_amounts"]["amounts"])
        self.assertIn("6543.21", search["string_amounts"]["amounts"])
        self.assertEqual(ranges(result), [])

    def test_unparsable_source_is_reported(self):
        result = run(lambda case: _policy(case), string_probes=True, cents_probes=True)
        search = result.report["target_search"]
        for key in ("string_amounts", "cents_amounts"):
            self.assertEqual(search[key]["amounts"], [])
            self.assertIn("not available", search[key]["unavailable"])


class BenchmarkFlagTests(unittest.TestCase):
    def test_flags_reach_verify_and_the_environment(self):
        import contextlib, io, tempfile
        from unittest import mock
        from benchmark import run as bench
        seen = []

        def fake_run_case(case, policy_text, **kwargs):
            seen.append((bench.STRING_PROBES, bench.CENTS_PROBES))
            return {"case": case.id, "report_sha256": "x", "detected": False, "confirmed_findings": 0,
                    "intervals": [], "spurious_claims": 0, "claims": 0, "points_correct": 0,
                    "points_judged": 0, "exit_code": case.expected_exit, "expected_exit": case.expected_exit,
                    "search_calls": 0, "seconds": 0.0, "group": case.group, "level": "L0", "codes": []}
        saved = (bench.STRING_PROBES, bench.CENTS_PROBES, bench.CASES, bench.CORPUS_VERSION)
        try:
            with tempfile.TemporaryDirectory() as tmp, mock.patch.object(bench, "run_case", fake_run_case), \
                    contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(bench.main(["--output-dir", tmp, "--skip-sweep", "--corpus", "3",
                                             "--string-probes", "--cents-probes"]), 0)
                import json, pathlib
                env = json.loads((pathlib.Path(tmp) / "results-run.json").read_text(encoding="utf-8"))["environment"]
        finally:
            bench.STRING_PROBES, bench.CENTS_PROBES, bench.CASES, bench.CORPUS_VERSION = saved
        self.assertEqual(set(seen), {(True, True)})
        self.assertEqual((env["string_probes"], env["cents_probes"], env["corpus_version"]), (True, True, "3"))


if __name__ == "__main__":
    unittest.main()
