import contextlib
import io
import json
import random
import unittest
from decimal import Decimal
from pathlib import Path

from examples.loophole_engine import evaluate_meal_claim as loophole_engine
from src.policyproof import verification
from src.policyproof.models import TestCase
from src.policyproof.muse_client import replay_proposal
from src.policyproof.reference import evaluate_meal_claim as reference_engine
from src.policyproof.target_search import (
    DEFAULT_BUDGET,
    DEFAULT_SEED,
    MAX_BUDGET,
    Judgement,
    search,
)
from src.policyproof.verification import Implementation, _registry, verify


ROOT = Path(__file__).resolve().parent.parent
POLICY_PATH = ROOT / "examples" / "democo_meal_policy.txt"
POLICY_TEXT = POLICY_PATH.read_text(encoding="utf-8")
FIXTURE_PATH = ROOT / "tests" / "fixtures" / "muse_democo_meal_response.json"
FIXTURE = replay_proposal(FIXTURE_PATH, POLICY_TEXT)
REFERENCES, TARGETS = _registry()
REFERENCE = REFERENCES["democo-meal"]
LOW, HIGH = Decimal("0.00"), Decimal("1000000.00")
D = Decimal


def wrong_in(*intervals, dated=True):
    """A target that is correct except for dated claims inside the intervals."""
    bounds = [(D(a), D(b)) for a, b in intervals]

    def decide(case):
        correct = reference_engine(case)
        if case.has_service_date == dated and any(a <= case.amount <= b for a, b in bounds):
            return "APPROVE" if correct != "APPROVE" else "REJECT"
        return correct
    return decide


def run(target, reference=REFERENCE, **kwargs):
    return verify(FIXTURE.document, POLICY_TEXT, proposal=FIXTURE, reference=reference,
                  target=Implementation("t", "test target", target), **kwargs)


def ranges(result):
    return [f for f in result.findings if f.details.get("kind") == "range"]


def span(finding):
    d = finding.details
    return (d["has_service_date"], d["start"], d["end"], d["lower_edge_verified"], d["upper_edge_verified"])


class LoopholeTests(unittest.TestCase):
    def test_loophole_range_is_found_with_verified_edges(self):
        result = run(loophole_engine)
        found = ranges(result)
        self.assertEqual([span(f) for f in found], [(True, "1000.00", "4999.99", True, True)])
        finding = found[0]
        self.assertEqual(finding.code, "TARGET_DISCREPANCY_CONFIRMED")
        self.assertEqual((finding.details["agrees_below"], finding.details["agrees_above"]), ("999.99", "5000.00"))
        self.assertEqual(result.level, "L2")
        # The edges in the report are real evaluations: check them against the engines.
        for amount, should_agree in [("999.99", True), ("1000.00", False), ("4999.99", False), ("5000.00", True)]:
            case = TestCase(D(amount), True)
            self.assertEqual(loophole_engine(case) == reference_engine(case), should_agree, amount)
        points = {p["id"]: p for p in result.report["points"]}
        for point_id in finding.points:
            self.assertIn(point_id, points)
        self.assertEqual(points["search-1000.00-dated"]["target"]["decision"], "APPROVE")
        self.assertEqual(points["search-1000.00-dated"]["reference"]["decision"], "REJECT")
        self.assertEqual(points["search-1000.00-dated"]["sources"][0]["kind"], "target_search")

    def test_without_search_the_loophole_passes_l3(self):
        """The gap this feature closes: only the evaluated points are checked."""
        result = run(loophole_engine, search_budget=0)
        self.assertEqual(result.level, "L3")
        self.assertEqual(result.report["target_search"], {"performed": False, "reason": "search budget is 0"})

    def test_cli_loophole_demo(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = verification.main([str(POLICY_PATH), "--replay", str(FIXTURE_PATH),
                                      "--reference", "democo-meal", "--target", "democo-loophole"])
        self.assertEqual(code, 3)
        self.assertIn("from $1000.00 to $4999.99 with a service date", out.getvalue())
        self.assertIn("Sampling, not exhaustive.", out.getvalue())

    def test_non_round_edges_are_located_by_bisection(self):
        result = run(wrong_in(("1234.56", "4321.09")))
        found = ranges(result)
        self.assertEqual([span(f) for f in found], [(True, "1234.56", "4321.09", True, True)])
        self.assertEqual((found[0].details["agrees_below"], found[0].details["agrees_above"]), ("1234.55", "4321.10"))
        self.assertGreater(result.report["target_search"]["bisection_calls"], 0)


class UnchangedBehaviourTests(unittest.TestCase):
    def test_buggy_target_still_has_exactly_one_confirmed_finding(self):
        result = run(TARGETS["democo-buggy"].decide)
        confirmed = [f for f in result.findings if f.code == "TARGET_DISCREPANCY_CONFIRMED"]
        self.assertEqual([f.points for f in confirmed], [("point-40.00-dated",)])
        self.assertEqual(ranges(result), [])
        self.assertEqual(result.level, "L2")

    def test_fixed_target_still_reaches_l3(self):
        result = run(TARGETS["democo-fixed"].decide)
        self.assertEqual(result.level, "L3")
        self.assertEqual([f.code for f in result.findings], ["CHECKED"])
        self.assertIn("target-search evaluations", result.report["verification"]["criteria"]["L3"]["detail"])
        self.assertIn("sampling, not exhaustive checking", result.report["verification"]["scope"])

    def test_no_reference_ranges_are_model_only(self):
        result = run(loophole_engine, reference=None)
        self.assertEqual([f.code for f in ranges(result)], ["TARGET_DISCREPANCY_MODEL_ONLY"])
        self.assertNotIn("TARGET_DISCREPANCY_CONFIRMED", result.codes())
        self.assertIn("not confirmed", ranges(result)[0].summary)

    def test_no_target_means_no_search(self):
        result = verify(FIXTURE.document, POLICY_TEXT, reference=REFERENCE)
        self.assertEqual(result.report["target_search"], {"performed": False, "reason": "no target supplied"})
        self.assertIsNone(result.search)


class BudgetAndDeterminismTests(unittest.TestCase):
    def counting(self, decide):
        calls = []

        def wrapped(case):
            calls.append(case)
            return decide(case)
        return wrapped, calls

    def test_budget_is_never_exceeded(self):
        base = run(TARGETS["democo-fixed"].decide, search_budget=0)
        base_calls = len(base.points)
        for budget in [1, 2, 3, 7, 50, 333, DEFAULT_BUDGET]:
            for decide in (loophole_engine, wrong_in(("0.00", "1000000.00")), wrong_in(("1234.56", "4321.09"))):
                with self.subTest(budget=budget):
                    target, calls = self.counting(decide)
                    result = run(target, search_budget=budget)
                    search_calls = len(calls) - base_calls
                    self.assertLessEqual(search_calls, budget)
                    self.assertEqual(search_calls, result.report["target_search"]["target_calls"])

    def test_tiny_budgets_report_unverified_edges_honestly(self):
        result = run(wrong_in(("1234.56", "4321.09")), search_budget=20)
        for finding in ranges(result):
            if not finding.details["lower_edge_verified"]:
                self.assertIn("was not located to the cent", finding.summary)

    def test_invalid_budgets_and_seeds(self):
        for bad in [-1, MAX_BUDGET + 1, 1.5, True, "100"]:
            with self.subTest(budget=bad), self.assertRaises(ValueError):
                run(loophole_engine, search_budget=bad)
        with self.assertRaises(ValueError):
            run(loophole_engine, search_seed="7")
        for bad in ["-1", str(MAX_BUDGET + 1), "x"]:
            with self.subTest(cli=bad), self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
                verification.main([str(POLICY_PATH), "--replay", str(FIXTURE_PATH), "--search-budget", bad])

    def test_identical_inputs_give_identical_reports(self):
        first = run(loophole_engine).to_json()
        self.assertEqual(first, run(loophole_engine).to_json())
        self.assertEqual(json.loads(first)["target_search"]["seed"], DEFAULT_SEED)

    def test_other_seeds_sample_differently_but_agree_on_the_loophole(self):
        outcomes = [run(loophole_engine, search_seed=seed) for seed in (1, 2, 3)]
        samples = [sorted(o.search.observations) for o in outcomes]
        self.assertNotEqual(samples[0], samples[1])
        for outcome in outcomes:
            self.assertEqual([span(f) for f in ranges(outcome)], [(True, "1000.00", "4999.99", True, True)])


class AlgorithmLimitTests(unittest.TestCase):
    def test_multiple_disjoint_ranges(self):
        result = run(wrong_in(("1234.56", "2345.67"), ("7000.00", "8999.99")))
        self.assertEqual(
            [span(f) for f in ranges(result)],
            [(True, "1234.56", "2345.67", True, True), (True, "7000.00", "8999.99", True, True)],
        )

    def test_both_date_values_are_searched(self):
        result = run(wrong_in(("2222.22", "3333.33"), dated=False))
        self.assertEqual([span(f) for f in ranges(result)], [(False, "2222.22", "3333.33", True, True)])

    def test_isolated_single_value_bug_can_be_missed(self):
        """A documented limit: one wrong cent away from every probe."""
        result = run(wrong_in(("33.33", "33.33")))
        self.assertEqual(ranges(result), [])
        self.assertEqual(result.level, "L3")
        self.assertIn("isolated amounts can be missed", " ".join(result.report["target_search"]["limitations"]))

    def test_isolated_bug_on_a_round_number_is_found(self):
        result = run(wrong_in(("2500.00", "2500.00")))
        self.assertEqual([span(f) for f in ranges(result)], [(True, "2500.00", "2500.00", True, True)])

    def test_unsampled_agreeing_gap_merges_two_ranges(self):
        """A documented limit: an agreeing gap that no probe lands in cannot
        separate two ranges. The finding then only claims what was evaluated."""
        result = run(wrong_in(("3000.00", "3499.99"), ("3500.02", "3999.99")))
        found = ranges(result)
        self.assertEqual([span(f) for f in found], [(True, "3000.00", "3999.99", True, True)])
        self.assertIn("sampled, not all checked", found[0].summary)
        self.assertIn("may contain agreeing amounts", " ".join(result.report["target_search"]["limitations"]))


class FailureHandlingTests(unittest.TestCase):
    def test_target_exceptions_during_search_are_recorded(self):
        def fails_above_1000(case):
            if case.amount > 1000:
                raise RuntimeError("ledger offline")
            return reference_engine(case)

        result = run(fails_above_1000)
        found = ranges(result)
        self.assertEqual({f.details["start"] for f in found}, {"1000.01"})
        self.assertTrue(all(f.details["end"] == "1000000.00" for f in found))
        self.assertIn("raised RuntimeError: ledger offline", found[0].details["at_start"]["target_error"])
        json.loads(result.to_json())

    def test_target_calling_sys_exit_does_not_end_the_run(self):
        def exits(case):
            raise SystemExit(0)

        result = run(exits)
        self.assertIn("raised SystemExit", result.points[0].target.error)
        self.assertEqual(result.level, "L2")

    def test_keyboard_interrupt_still_stops_the_run(self):
        def interrupted(case):
            raise KeyboardInterrupt

        with self.assertRaises(KeyboardInterrupt):
            run(interrupted)

    def test_reference_failures_during_search_are_unjudged(self):
        def reference_fails_above_100(case):
            if case.amount > 100:
                raise ValueError("no data")
            return reference_engine(case)

        result = run(loophole_engine, reference=Implementation("ref", "", reference_fails_above_100))
        self.assertGreater(result.report["target_search"]["unjudged_evaluations"], 0)
        self.assertEqual(ranges(result), [])  # never judged, so never reported
        self.assertNotEqual(result.level, "L3")

    def test_unjudged_search_evaluations_block_l3_and_ok(self):
        # Regression (benchmark corpus v1, time-limit-exhausted): every
        # evaluated point was judged, but search calls that could not be
        # judged were counted as agreement, giving L3 and exit 0.
        def reference_fails_between_points(case):
            if D("500.00") < case.amount < D("600.00"):
                raise ValueError("no data")
            return reference_engine(case)

        result = run(TARGETS["democo-fixed"].decide,
                     reference=Implementation("ref", "", reference_fails_between_points))
        search = result.report["target_search"]
        self.assertGreater(search["unjudged_evaluations"], 0)
        unjudged = [f for f in result.findings if f.code == "UNSUPPORTED" and "could not be judged" in f.summary]
        self.assertEqual(len(unjudged), 1)
        details = unjudged[0].details
        self.assertEqual(details["unjudged"], search["unjudged_evaluations"])
        self.assertEqual(details["reasons"], {"reference produced no decision": details["unjudged"]})
        self.assertTrue(D("500.00") < D(details["first_unjudged"]["amount"]) < D("600.00"))
        self.assertEqual(unjudged[0].severity, "error")
        self.assertEqual(result.level, "L2")
        self.assertIn("could not be judged", result.report["verification"]["criteria"]["L3"]["detail"])
        self.assertEqual(result.report["verification"]["result"]["exit_code"], 3)
        self.assertFalse([c for c in result.codes() if c.startswith("TARGET_DISCREPANCY")])

    def test_fully_judged_search_adds_no_unjudged_finding(self):
        result = run(TARGETS["democo-fixed"].decide)
        self.assertEqual(result.report["target_search"]["unjudged_evaluations"], 0)
        self.assertEqual(result.codes(), ["CHECKED"])
        self.assertEqual(result.level, "L3")


class SearchAlgorithmTests(unittest.TestCase):
    """The search alone, against a plain predicate."""

    def known(self, oracle):
        return {
            (amount, dated): Judgement(oracle(amount, dated))
            for amount in (LOW, D("40.00"), HIGH) for dated in (False, True)
        }

    def test_every_verified_edge_is_sound(self):
        rng = random.Random(7)
        for trial in range(60):
            a = rng.randrange(1, 90_000_000)
            b = rng.randrange(a, min(a + rng.randrange(1, 5_000_000), 99_999_999))
            low_c, high_c = D(a) / 100, D(b) / 100

            def oracle(amount, dated):
                return not (dated and low_c <= amount <= high_c)

            outcome = search(lambda amount, dated: Judgement(oracle(amount, dated)),
                             self.known(oracle), low=LOW, high=HIGH, seed=trial, budget=600)
            self.assertLessEqual(outcome.calls, 600)
            for found in outcome.ranges:
                for edge in (found.lower, found.upper):
                    self.assertFalse(oracle(edge.inside, found.has_service_date))
                    if edge.outside is not None:
                        self.assertTrue(oracle(edge.outside, found.has_service_date))
                    if edge.verified and edge.outside is not None:
                        self.assertEqual(abs(edge.outside - edge.inside), D("0.01"))
                for amount in found.disagreeing:
                    self.assertFalse(oracle(amount, found.has_service_date))

    def test_budget_zero_makes_no_calls(self):
        calls = []
        outcome = search(lambda a, d: calls.append(a) or Judgement(True), {}, low=LOW, high=HIGH, budget=0)
        self.assertEqual((calls, outcome.calls, outcome.ranges), ([], 0, ()))


if __name__ == "__main__":
    unittest.main()
