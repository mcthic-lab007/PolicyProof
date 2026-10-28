"""Offline tests for the Muse probe experiment harness (benchmark/muse_probes).
Every response here is synthetic and labelled so; no network call is made."""

import contextlib
import io
import json
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest import mock

from benchmark import muse_probes as mp
from benchmark import run as bench
from benchmark.corpus import by_id
from src.policyproof.muse_client import FIXTURE_NOTE_KEY, RECORDING_KEY, MuseClient

D = Decimal
POLICY_TEXT = bench.POLICY.read_text(encoding="utf-8")
FAKE_KEY = "test-key-not-real-0123456789"


def body_for(amounts, note=True):
    text = json.dumps({"amounts": [{"amount": a, "reason": "synthetic"} for a in amounts]})
    body = {"id": "resp_synthetic", "status": "completed", "usage": {"total_tokens": 0},
            "output": [{"type": "message", "role": "assistant",
                        "content": [{"type": "output_text", "text": text}]}]}
    if note:
        body[FIXTURE_NOTE_KEY] = "synthetic test response, not Muse Spark output"
    return body


class FakeResponse:
    status_code = 200

    def __init__(self, body):
        self._body = body

    def json(self):
        return self._body


class PromptTests(unittest.TestCase):
    def test_prompt_hides_comments_docstrings_and_names(self):
        from src.policyproof.source_literals import source_excerpt
        code = source_excerpt(bench._import("benchmark.targets:narrow_computed_range"))
        prompt = mp.build_probe_prompt(POLICY_TEXT, code)
        for leak in ("2000.37", "2000.52", "Approves dated", "narrow_computed_range", "computed"):
            self.assertNotIn(leak, code)
        self.assertIn("_LOW = _BASE + Decimal(37) * CENT", prompt)
        self.assertIn("def decide(case):", prompt)
        self.assertIn(POLICY_TEXT, prompt)

    def test_reserved_delimiters_are_refused(self):
        with self.assertRaises(ValueError):
            mp.build_probe_prompt(POLICY_TEXT, f"x = 1  # {mp.CODE_END}")


class ParseTests(unittest.TestCase):
    def test_valid_and_invalid_entries(self):
        amounts, issues = mp.parse_proposals(body_for(
            ["777.77", "2000.37", 12.5, "1.005", "-3", "2000000.00", "abc", "777.77"]))
        self.assertEqual(amounts, (D("12.50"), D("777.77"), D("2000.37")))
        self.assertEqual(len(issues), 4)

    def test_unusable_response_gives_no_probes(self):
        bad = body_for([])
        bad["output"][0]["content"][0]["text"] = "not json"
        self.assertEqual(mp.parse_proposals(bad)[0], ())
        self.assertEqual(mp.parse_proposals({"status": "failed"})[0], ())


class RecordTests(unittest.TestCase):
    def test_record_refuses_without_a_key_and_calls_nothing(self):
        with mock.patch.dict("os.environ", {}, clear=True), \
                mock.patch("requests.post") as post, tempfile.TemporaryDirectory() as tmp:
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                code = mp.main(["record", "--dir", tmp, "--trials", "1"])
            self.assertEqual(code, 1)
            self.assertIn("no call was made", err.getvalue())
            post.assert_not_called()
            self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_record_saves_prompt_usage_and_provenance_and_never_overwrites(self):
        calls = []

        def transport(url, **kwargs):
            calls.append(kwargs["json"])
            return FakeResponse(body_for(["2000.37"], note=False))
        client = MuseClient(FAKE_KEY, transport=transport)
        with tempfile.TemporaryDirectory() as tmp:
            saved = mp.record(client, POLICY_TEXT, Path(tmp), trials=1)
            self.assertEqual(len(saved), len(calls))
            self.assertGreater(len(saved), 10)
            data = json.loads(saved[0].read_text(encoding="utf-8"))
            self.assertIn(RECORDING_KEY, data)
            self.assertEqual(data[mp.INPUT_KEY]["prompt"], calls[0]["input"])
            self.assertEqual(data["usage"], {"total_tokens": 0})
            self.assertNotIn(FAKE_KEY, saved[0].read_text(encoding="utf-8"))
            self.assertEqual(mp.record(client, POLICY_TEXT, Path(tmp), trials=1), [])
            self.assertEqual(len(saved), len(calls))


class EvaluateTests(unittest.TestCase):
    def write(self, tmp, spec, body, trial=1):
        path = Path(tmp) / mp.targets()[spec] / f"trial-{trial}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        body = dict(body)
        body[mp.INPUT_KEY] = {"target": spec, "trial": trial}
        path.write_text(json.dumps(body), encoding="utf-8")

    def test_synthetic_files_are_refused_unless_allowed_and_then_labelled(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.write(tmp, "examples.fixed_engine:evaluate_meal_claim", body_for(["777.77"]))
            with self.assertRaises(ValueError):
                mp.load_trials(Path(tmp), allow_synthetic=False)
            _, provenance = mp.load_trials(Path(tmp), allow_synthetic=True)
            self.assertEqual(provenance, "REPLAY_SYNTHETIC")

    def test_files_of_unknown_origin_are_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.write(tmp, "examples.fixed_engine:evaluate_meal_claim", body_for(["1.00"], note=False))
            with self.assertRaises(ValueError):
                mp.load_trials(Path(tmp), allow_synthetic=True)

    def test_proposals_are_probes_never_findings(self):
        cases = (by_id("fixed-engine"), by_id("narrow-computed-range"))
        trials = {1: {
            "examples.fixed_engine:evaluate_meal_claim": body_for(["777.77", "2000.37"]),
            "benchmark.targets:narrow_computed_range": body_for(["2000.37"]),
        }}
        with mock.patch.object(mp, "CASES", cases):
            results = mp.evaluate(trials, "REPLAY_SYNTHETIC", POLICY_TEXT)
        for method in ("C", "D"):
            rows = {r["case"]: r for r in results["trials"]["1"]["methods"][method]["cases"]}
            self.assertEqual(rows["fixed-engine"]["confirmed_findings"], 0)
            self.assertEqual(rows["fixed-engine"]["level"], "L3")
            computed = rows["narrow-computed-range"]
            self.assertTrue(computed["intervals"][0]["exactly_located"], method)
        self.assertEqual(results["provenance"], "REPLAY_SYNTHETIC")


if __name__ == "__main__":
    unittest.main()
