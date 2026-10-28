import unittest
from decimal import Decimal

from benchmark import targets as bench
from src.policyproof.source_literals import MAX_SOURCE_AMOUNTS, source_amounts
from tests.test_target_search import TARGETS, run, ranges, span

D = Decimal
LOW, HIGH = D("0.00"), D("1000000.00")
LIMIT = D("40.00")
_CALLED = []


def _mixed(case):
    """Literals of every kind, only some of them amounts."""
    _CALLED.append(case)
    flags = (True, 3, 2.5, "12.34", "APPROVE", "1.005", -5, 2_000_000, "7")
    return LIMIT if flags else D("0.125")


_MANY = (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32, 33, 34, 35, 36, 37, 38, 39, 40, 41, 42, 43, 44, 45, 46, 47, 48, 49, 50, 51, 52, 53, 54, 55, 56, 57, 58, 59, 60, 61, 62, 63, 64, 65, 66, 67, 68, 69, 70, 71, 72, 73, 74, 75, 76, 77, 78, 79, 80, 81, 82, 83, 84, 85, 86, 87, 88, 89, 90, 91, 92, 93, 94, 95, 96, 97, 98, 99, 100, 101, 102, 103, 104, 105, 106, 107, 108, 109, 110, 111, 112, 113, 114, 115, 116, 117, 118, 119, 120)


def _many(case):
    return case.amount in _MANY


def amounts(function):
    return [str(a) for a in source_amounts(function, LOW, HIGH).amounts]


class SourceAmountTests(unittest.TestCase):
    def test_literals_are_read_not_executed(self):
        self.assertEqual(amounts(_mixed), ["2.50", "3.00", "5.00", "7.00", "12.34", "40.00"])  # -5 is a negated 5
        self.assertEqual(_CALLED, [])

    def test_module_constants_contribute_literal_operands_only(self):
        found = amounts(bench.narrow_computed_range)
        self.assertIn("40.00", found)
        self.assertNotIn("2000.37", found)  # computed, never evaluated
        self.assertNotIn("2000.52", found)

    def test_corpus_literals(self):
        self.assertIn("777.77", amounts(bench.single_cent_override))
        self.assertTrue({"12345.67", "12345.99"} <= set(amounts(bench.narrow_literal_range)))

    def test_no_source_means_no_amounts(self):
        result = source_amounts(lambda case: "APPROVE", LOW, HIGH)
        self.assertEqual(result.amounts, ())
        self.assertIn("not available", result.unavailable)
        self.assertEqual(source_amounts(len, LOW, HIGH).amounts, ())

    def test_amounts_are_capped(self):
        self.assertEqual(len(source_amounts(_many, LOW, HIGH).amounts), MAX_SOURCE_AMOUNTS)


def implementation(function):
    from src.policyproof.verification import Implementation
    return Implementation(function.__name__, "", function)


class SourceProbeVerificationTests(unittest.TestCase):
    # Regressions (benchmark corpus v2): both were missed in every
    # search-enabled run, because sampling almost never lands on them.
    def test_single_wrong_cent_is_found_with_verified_edges(self):
        result = run(bench.single_cent_override)
        found = ranges(result)
        self.assertEqual([span(f) for f in found], [(True, "777.77", "777.77", True, True)])
        self.assertEqual(found[0].code, "TARGET_DISCREPANCY_CONFIRMED")
        self.assertIn("777.77", result.report["target_search"]["source_amounts"]["amounts"])

    def test_narrow_literal_range_is_found_with_verified_edges(self):
        result = run(bench.narrow_literal_range)
        self.assertEqual([span(f) for f in ranges(result)], [(True, "12345.67", "12345.99", True, True)])

    def test_switched_off_the_single_cent_is_missed_again(self):
        result = run(bench.single_cent_override, source_probes=False)
        self.assertEqual(ranges(result), [])
        self.assertEqual(result.level, "L3")
        self.assertEqual(result.report["target_search"]["source_amounts"], {"used": False, "reason": "disabled"})

    def test_correct_targets_are_not_accused(self):
        for target in (TARGETS["democo-fixed"].decide, bench.correct_float, bench.correct_reordered):
            with self.subTest(target=target.__name__):
                result = run(target)
                self.assertFalse([c for c in result.codes() if c.startswith("TARGET_DISCREPANCY")])
                self.assertEqual(result.level, "L3")

    def test_a_source_amount_alone_is_not_evidence(self):
        """$777.77 is in the source of a target that is correct there:
        probing it finds nothing."""
        def correct_but_mentions(case):
            if case.amount == D("777.77") and not case.has_service_date:
                return "REVIEW"
            return TARGETS["democo-fixed"].decide(case)
        result = run(correct_but_mentions)
        self.assertIn("777.77", result.report["target_search"]["source_amounts"]["amounts"])
        self.assertEqual(ranges(result), [])
        self.assertEqual(result.level, "L3")

    def test_cli_and_viewer_show_the_probed_amounts(self):
        import contextlib, io, json, tempfile
        from src.policyproof import verification
        from src.policyproof.viewer import render_report
        from tests.test_target_search import POLICY_PATH, FIXTURE_PATH
        with tempfile.TemporaryDirectory() as tmp:
            report_path = f"{tmp}/r.json"
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = verification.main([str(POLICY_PATH), "--replay", str(FIXTURE_PATH), "--reference",
                                          "democo-meal", "--target", "democo-loophole", "--report", report_path])
            self.assertEqual(code, 3)
            self.assertIn("Source amounts probed: $40.00, $1000.00, $4999.99", out.getvalue())
            self.assertIn("parsed, not executed", out.getvalue())
            with open(report_path, encoding="utf-8") as handle:
                page = render_report(json.load(handle))
        self.assertIn("probed first: $40.00, $1000.00, $4999.99", page)
        self.assertIn("They are probes, not evidence.", page)

    def test_unavailable_source_is_reported(self):
        result = run(lambda case: TARGETS["democo-fixed"].decide(case))
        section = result.report["target_search"]["source_amounts"]
        self.assertEqual((section["used"], section["amounts"]), (True, []))
        self.assertIn("not available", section["unavailable"])


if __name__ == "__main__":
    unittest.main()
