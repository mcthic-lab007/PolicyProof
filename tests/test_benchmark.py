import random
import unittest
from decimal import Decimal

from benchmark import run as bench
from benchmark.corpus import CASES, CORRECT, DEFECT, Case, by_id
from src.policyproof.models import TestCase
from src.policyproof.reference import evaluate_meal_claim as reference_engine


CENT = Decimal("0.01")
LOW, HIGH = Decimal("0.00"), Decimal("1000000.00")
POLICY_TEXT = bench.POLICY.read_text(encoding="utf-8")
# Targets that cannot be called in this process: they hang, cannot be
# imported, or are slow by design.
NOT_IN_PROCESS = {"hangs-at-40", "import-fails", "time-limit-exhausted"}


def differs(target, amount: Decimal, dated: bool) -> bool:
    case = TestCase(amount, dated, "ground-truth-check")
    try:
        got = target(case)
    except Exception:
        return True  # a failure differs from every decision, as in verification
    return got != reference_engine(case)


def samples(seed: str, count: int):
    rng = random.Random(seed)
    ladder = [Decimal(m) * 10 ** k for m in ("1", "2", "2.5", "5") for k in range(7)]
    amounts = {a.quantize(CENT) + o for a in ladder for o in (-CENT, 0, CENT)}
    amounts |= {(Decimal(rng.randrange(0, 100_000_001)) * CENT).quantize(CENT) for _ in range(count)}
    return sorted(a for a in amounts if LOW <= a <= HIGH)


class GroundTruthTests(unittest.TestCase):
    """The declared ground truth matches each target's actual behaviour at
    every interval edge, one cent beyond it, and seeded samples. A
    consistency check, not an exhaustive proof."""

    def test_declarations_match_targets(self):
        for case in CASES:
            if case.id in NOT_IN_PROCESS:
                continue
            target = bench._import(case.target)
            with self.subTest(case=case.id):
                checks = []
                for dated, first, last in case.intervals:
                    checks += [(first, dated), (last, dated), (first - CENT, dated), (last + CENT, dated)]
                    span = int((last - first) / CENT)
                    rng = random.Random(f"{case.id}:{first}")
                    checks += [(first + rng.randrange(0, span + 1) * CENT, dated) for _ in range(50)]
                checks += [(a, d) for d in (False, True) for a in samples(f"{case.id}:{d}", 2000)]
                for amount, dated in checks:
                    if LOW <= amount <= HIGH:
                        self.assertEqual(differs(target, amount, dated), case.discrepant(amount, dated),
                                         f"{case.id} at {amount} dated={dated}")

    def test_corpus_integrity(self):
        ids = [case.id for case in CASES]
        self.assertEqual(len(ids), len(set(ids)))
        for case in CASES:
            if case.group == CORRECT:
                self.assertFalse(case.defective, case.id)
                self.assertEqual(case.expected_exit, 0, case.id)
            if case.group == DEFECT:
                self.assertTrue(case.defective, case.id)
                self.assertEqual(case.expected_exit, 3, case.id)


class ScoringTests(unittest.TestCase):
    def test_detected_and_exactly_located(self):
        row = bench.run_case(by_id("exclusive-boundary"), POLICY_TEXT, isolated=False)
        self.assertTrue(row["detected"])
        self.assertEqual(row["exit_code"], 3)
        self.assertEqual(row["spurious_claims"], 0)
        self.assertEqual(row["intervals"][0]["found"], True)
        self.assertEqual(row["intervals"][0]["exactly_located"], True)
        self.assertEqual(row["points_judged"], row["points_correct"])

    def test_correct_target_has_no_claims(self):
        row = bench.run_case(by_id("fixed-engine"), POLICY_TEXT, isolated=False)
        self.assertEqual((row["exit_code"], row["confirmed_findings"], row["claims"]), (0, 0, 0))

    def test_wrong_ground_truth_is_scored_as_spurious(self):
        wrong = Case("wrong", DEFECT, "examples.buggy_engine:evaluate_meal_claim", "", 3,
                     ((True, Decimal("50.00"), Decimal("50.00")),))
        row = bench.run_case(wrong, POLICY_TEXT, isolated=False)
        self.assertFalse(row["detected"])
        self.assertGreater(row["spurious_claims"], 0)
        self.assertFalse(row["intervals"][0]["found"])

    def test_same_seed_same_report(self):
        case = by_id("loophole-1000-4999")
        a = bench.run_case(case, POLICY_TEXT, isolated=False)
        b = bench.run_case(case, POLICY_TEXT, isolated=False)
        self.assertEqual(a["report_sha256"], b["report_sha256"])


if __name__ == "__main__":
    unittest.main()
