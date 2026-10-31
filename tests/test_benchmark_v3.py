"""Ground-truth checks for corpus v3 (benchmark/corpus_v3.py).

These check only the declared truth against the targets; they measure no
verification method."""

import random
import unittest
from decimal import Decimal

from benchmark import corpus, corpus_v3
from benchmark import run as bench
from tests.test_benchmark import CENT, HIGH, LOW, differs, samples

WINDOW = Decimal("50.00")  # every cent this far either side of an interval


class CorpusV3Tests(unittest.TestCase):
    def test_v2_is_unchanged_and_v3_extends_it(self):
        self.assertEqual(corpus.CORPUS_VERSION, "2")
        self.assertEqual(corpus_v3.CORPUS_VERSION, "3")
        self.assertEqual(corpus_v3.CASES[:len(corpus.CASES)], corpus.CASES)
        self.assertEqual(len(corpus_v3.NEW_CASES), 8)
        ids = [c.id for c in corpus_v3.CASES]
        self.assertEqual(len(ids), len(set(ids)))

    def test_every_new_case_is_labelled_and_predicted_before_measurement(self):
        for case in corpus_v3.NEW_CASES:
            with self.subTest(case=case.id):
                self.assertIn(corpus_v3.MECHANISM[case.id], ("realistic mechanism", "artificial fixture"))
                self.assertEqual(set(corpus_v3.PREDICTIONS[case.id]), {"A", "B", "E", "Muse"})
                self.assertEqual(case.expected_exit, 0 if case.group == corpus.CORRECT else 3)
                self.assertEqual(case.defective, case.group == corpus.DEFECT)

    def test_declarations_match_targets_at_edges_and_samples(self):
        for case in corpus_v3.NEW_CASES:
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
        for case in corpus_v3.NEW_CASES:
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
    def test_corpus_flag_selects_v3_and_v2_stays_default(self):
        import contextlib
        import io
        import tempfile
        from unittest import mock
        seen = {}

        def fake_run_case(case, policy_text, **kwargs):
            seen.setdefault(bench.CORPUS_VERSION, []).append(case.id)
            return {"case": case.id, "report_sha256": "x"}
        for version, expected in (("3", corpus_v3.CASES), ("2", corpus.CASES)):
            with self.subTest(version=version), tempfile.TemporaryDirectory() as tmp, \
                    mock.patch.object(bench, "CASES", bench.CASES), \
                    mock.patch.object(bench, "CORPUS_VERSION", bench.CORPUS_VERSION), \
                    mock.patch.object(bench, "run_case", fake_run_case), \
                    mock.patch.object(bench, "summarize", lambda rows: {}), \
                    mock.patch.object(bench, "render", lambda results: ""), \
                    contextlib.redirect_stdout(io.StringIO()):
                seen.clear()
                argv = ["--output-dir", tmp, "--skip-sweep"] + (["--corpus", version] if version == "3" else [])
                self.assertEqual(bench.main(argv), 0)
                self.assertEqual(list(seen), [version])
                self.assertEqual(seen[version], [c.id for c in expected] * 2)  # two primary passes
        self.assertEqual(bench.CORPUS_VERSION, "2")


if __name__ == "__main__":
    unittest.main()
