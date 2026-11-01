"""Ground-truth checks for the generalization corpus g1
(benchmark/corpus_gen.py). They check only the declared truth against the
targets; they measure no verification method."""

import random
import unittest
from decimal import Decimal

from benchmark import corpus, corpus_gen
from benchmark import run as bench
from tests.test_benchmark import CENT, HIGH, LOW, differs, samples

WINDOW = Decimal("50.00")  # every cent this far either side of an interval


class CorpusGenTests(unittest.TestCase):
    def test_independent_of_v2_and_v3(self):
        self.assertEqual(corpus_gen.CORPUS_VERSION, "g1")
        self.assertEqual(len(corpus_gen.CASES), 23)
        ids = [c.id for c in corpus_gen.CASES]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(all(c.target.startswith("benchmark.targets_gen:") for c in corpus_gen.CASES))

    def test_every_case_has_a_role_and_every_defect_a_prediction(self):
        self.assertEqual(set(corpus_gen.ROLE), {c.id for c in corpus_gen.CASES})
        counts = {}
        for case in corpus_gen.CASES:
            role = corpus_gen.ROLE[case.id]
            counts[role] = counts.get(role, 0) + 1
            with self.subTest(case=case.id):
                self.assertEqual(case.group == corpus.CORRECT, role == corpus_gen.CONTROL)
                self.assertEqual(case.expected_exit, 0 if case.group == corpus.CORRECT else 3)
                if case.group == corpus.DEFECT:
                    self.assertTrue({"A", "G", "H"} <= set(corpus_gen.PREDICTIONS[case.id]))
        self.assertEqual(counts, {corpus_gen.G_POS: 5, corpus_gen.H_POS: 5, corpus_gen.OUT: 5,
                                  corpus_gen.CONTROL: 8})
        self.assertEqual(len(corpus_gen.ACCEPTANCE), 7)

    def test_declarations_match_targets_at_edges_and_samples(self):
        for case in corpus_gen.CASES:
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

    def test_every_cent_around_each_interval_and_the_threshold(self):
        for case in corpus_gen.CASES:
            target = bench._import(case.target)
            windows = [(Decimal("0.00"), Decimal("100.00"))]
            windows += [(max(LOW, first - WINDOW), min(HIGH, last + WINDOW))
                        for _, first, last in case.intervals]
            with self.subTest(case=case.id):
                for start, end in windows:
                    for cents in range(int(start / CENT), int(end / CENT) + 1):
                        amount = Decimal(cents) * CENT
                        for dated in (True, False):
                            if differs(target, amount, dated) != case.discrepant(amount, dated):
                                self.fail(f"{case.id} at {amount} dated={dated}")


class RunnerTests(unittest.TestCase):
    def test_corpus_flag_selects_g1(self):
        import contextlib
        import io
        import tempfile
        from unittest import mock
        seen = []

        def fake_run_case(case, policy_text, **kwargs):
            seen.append((bench.CORPUS_VERSION, case.id))
            return {"case": case.id, "report_sha256": "x"}
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(bench, "CASES", bench.CASES), \
                mock.patch.object(bench, "CORPUS_VERSION", bench.CORPUS_VERSION), \
                mock.patch.object(bench, "run_case", fake_run_case), \
                mock.patch.object(bench, "summarize", lambda rows: {}), \
                mock.patch.object(bench, "render", lambda results: ""), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(bench.main(["--output-dir", tmp, "--skip-sweep", "--corpus", "g1"]), 0)
        self.assertEqual(seen, [("g1", c.id) for c in corpus_gen.CASES] * 2)
        self.assertEqual(bench.CORPUS_VERSION, "2")


if __name__ == "__main__":
    unittest.main()
