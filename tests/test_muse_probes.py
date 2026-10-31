"""Offline tests for the Muse probe experiment harness (benchmark/muse_probes).
Every response here is synthetic and labelled so; no network call is made."""

import contextlib
import io
import json
import os
import re
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
        # DOTENV points at a missing file so the developer's real .env is never read.
        with mock.patch.dict("os.environ", {}, clear=True), \
                mock.patch("requests.post") as post, tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(mp, "DOTENV", Path(tmp) / "missing.env"):
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                code = mp.main(["record", "--dir", tmp, "--trials", "1"])
            self.assertEqual(code, 1)
            self.assertIn("no call was made", err.getvalue())
            post.assert_not_called()
            self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_record_reads_the_key_from_dotenv_without_printing_it(self):
        seen = {}

        def fake_from_env():
            seen["key"] = os.environ.get("META_MUSE_API_KEY")
            raise mp.MuseClientError("stop before any call")
        with tempfile.TemporaryDirectory() as tmp:
            dotenv = Path(tmp) / ".env"
            dotenv.write_text(f"META_MUSE_API_KEY={FAKE_KEY}\n", encoding="utf-8")
            out, err = io.StringIO(), io.StringIO()
            with mock.patch.dict("os.environ", {}, clear=True), \
                    mock.patch.object(mp, "DOTENV", dotenv), \
                    mock.patch.object(mp.MuseClient, "from_env", fake_from_env), \
                    mock.patch("requests.post") as post, \
                    contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = mp.main(["record", "--dir", tmp, "--trials", "1"])
            self.assertEqual(code, 1)
            self.assertEqual(seen["key"], FAKE_KEY)
            post.assert_not_called()
            self.assertNotIn(FAKE_KEY, out.getvalue() + err.getvalue())

    def test_evaluate_never_reads_dotenv(self):
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(mp, "load_api_key_from_dotenv") as load, \
                contextlib.redirect_stderr(io.StringIO()):
            mp.main(["evaluate", "--dir", tmp, "--output", str(Path(tmp) / "o.json")])
            load.assert_not_called()

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


    def test_pilot_records_one_target_only(self):
        calls = []

        def transport(url, **kwargs):
            calls.append(kwargs["json"]["input"])
            return FakeResponse(body_for(["2000.37"], note=False))
        client = MuseClient(FAKE_KEY, transport=transport)
        with tempfile.TemporaryDirectory() as tmp:
            saved = mp.record(client, POLICY_TEXT, Path(tmp), trials=1,
                              only="benchmark.targets:narrow_computed_range")
            self.assertEqual((len(saved), len(calls)), (1, 1))
            self.assertIn("_LOW = _BASE + Decimal(37) * CENT", calls[0])
            with self.assertRaises(ValueError):
                mp.record(client, POLICY_TEXT, Path(tmp), trials=1, only="no.such:target")
            self.assertEqual(len(calls), 1)


def input_record(spec, trial=1, prompt="synthetic prompt"):
    return {"target": spec, "trial": trial, "corpus_version": mp.CORPUS_VERSION,
            "model": mp.MODEL_ID, "prompt": prompt,
            "prompt_sha256": mp.hashlib.sha256(prompt.encode("utf-8")).hexdigest()}


def write_trial(tmp, spec, body, trial=1, meta=None):
    path = Path(tmp) / mp.targets()[spec] / f"trial-{trial}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    body = dict(body)
    body[mp.INPUT_KEY] = input_record(spec, trial) if meta is None else meta
    path.write_text(json.dumps(body), encoding="utf-8")
    return path


class EvaluateTests(unittest.TestCase):
    def write(self, tmp, spec, body, trial=1):
        return write_trial(tmp, spec, body, trial)

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


COMPUTED = "benchmark.targets:narrow_computed_range"
EDGES = ["2000.36", "2000.37", "2000.38", "2000.44", "2000.51", "2000.52", "2000.53"]
SMALL = (by_id("narrow-computed-range"), by_id("fixed-engine"), by_id("integer-cents"))


def live_labelled(amounts):
    """A synthetic body carrying the live-recording label, to test how the
    loader classifies files. It is not Muse output."""
    body = body_for(amounts, note=False)
    body[RECORDING_KEY] = {"source": "test: label only, not a live call"}
    return body


class EvidenceTests(unittest.TestCase):
    def test_live_labelled_file_is_classified_as_replay_of_live_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_trial(tmp, COMPUTED, live_labelled(EDGES))
            trials, provenance = mp.load_trials(Path(tmp), allow_synthetic=False)
            self.assertEqual(provenance, "REPLAY_SAVED_LIVE_RESPONSE")
            self.assertEqual(list(trials[1]), [COMPUTED])

    def test_any_synthetic_file_makes_the_whole_set_synthetic(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_trial(tmp, COMPUTED, live_labelled(EDGES))
            write_trial(tmp, "examples.fixed_engine:evaluate_meal_claim", body_for(["1.00"]))
            self.assertEqual(mp.load_trials(Path(tmp), allow_synthetic=True)[1], "REPLAY_SYNTHETIC")

    def test_malformed_or_inconsistent_evidence_is_refused(self):
        good = input_record(COMPUTED)
        bad_records = {
            "trial missing": {k: v for k, v in good.items() if k != "trial"},
            "trial not int": dict(good, trial="1"),
            "trial zero": dict(good, trial=0),
            "unknown target": dict(good, target="no.such:target"),
            "other model": dict(good, model="some-other-model"),
            "other corpus": dict(good, corpus_version="1"),
            "prompt missing": {k: v for k, v in good.items() if k != "prompt"},
            "prompt tampered": dict(good, prompt="edited after recording"),
            "wrong folder": dict(good, target="examples.fixed_engine:evaluate_meal_claim"),
        }
        for name, meta in bad_records.items():
            with self.subTest(name), tempfile.TemporaryDirectory() as tmp:
                write_trial(tmp, COMPUTED, live_labelled(EDGES), meta=meta)
                with self.assertRaises(ValueError):
                    mp.load_trials(Path(tmp), allow_synthetic=True)
        for name, text in {"not json": "{", "not an object": "[1]"}.items():
            with self.subTest(name), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / mp.targets()[COMPUTED] / "trial-1.json"
                path.parent.mkdir(parents=True)
                path.write_text(text, encoding="utf-8")
                with self.assertRaises(ValueError):
                    mp.load_trials(Path(tmp), allow_synthetic=True)

    def test_sweep_refuses_bad_evidence_and_leaves_files_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_trial(tmp, COMPUTED, body_for(EDGES))  # synthetic, not allowed by default
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                code = mp.main(["sweep", "--dir", tmp, "--output", str(Path(tmp) / "o.json")])
            self.assertEqual(code, 1)
            self.assertIn("synthetic", err.getvalue())
            self.assertFalse((Path(tmp) / "o.json").exists())

    def test_sweep_cli_writes_results_and_never_modifies_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_trial(tmp, COMPUTED, live_labelled(EDGES))
            before = path.read_bytes()
            out = Path(tmp) / "out" / "sweep.json"
            with mock.patch.object(mp, "CASES", SMALL), contextlib.redirect_stdout(io.StringIO()):
                code = mp.main(["sweep", "--dir", tmp, "--output", str(out),
                                "--budgets", "250", "--seeds", "2"])
            self.assertEqual(code, 0)
            self.assertEqual(path.read_bytes(), before)
            data = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(data["provenance"], "REPLAY_SAVED_LIVE_RESPONSE")
            self.assertEqual(list(data["evidence"].values()),
                             [mp.hashlib.sha256(before).hexdigest()])
            self.assertTrue(out.with_suffix(".md").exists())


class SweepTests(unittest.TestCase):
    def sweep(self, amounts, budgets=(1000,), seeds=2, cases=SMALL):
        trials = {1: {COMPUTED: body_for(amounts)}}
        with mock.patch.object(mp, "CASES", cases):
            return mp.seed_sweep(trials, "REPLAY_SYNTHETIC", POLICY_TEXT, budgets, seeds)

    def rows(self, results, **match):
        return [r for r in results["trials"]["1"]["rows"]
                if all(r[k] == v for k, v in match.items())]

    def test_all_methods_run_with_the_right_probe_origins(self):
        results = self.sweep(EDGES)
        target = self.rows(results, case="narrow-computed-range")
        self.assertEqual(sorted({r["method"] for r in target}), ["A", "B", "C", "D", "E", "F"])
        for r in target:
            m = r["method"]
            uses_source, uses_constants, uses_muse = m in "BDEF", m in "EF", m in "CDF"
            self.assertEqual(bool(r["probes"]["source"]), uses_source, m)
            self.assertEqual("2000.37" in r["probes"]["constant"], uses_constants, m)
            self.assertEqual(r["probes"]["muse"], EDGES if uses_muse else [], m)
        for row in results["trials"]["1"]["summary"]:
            self.assertEqual(row["seeds"], 2)

    def test_ten_seeds_are_the_benchmark_sweep_seeds_for_every_method(self):
        results = self.sweep(EDGES, budgets=(0,), seeds=10, cases=SMALL[:1])
        self.assertEqual(results["seeds"], bench.sweep_seeds(10))
        self.assertEqual(len(set(results["seeds"])), 10)
        for method in "ABCDEF":
            seeds = [r["seed"] for r in self.rows(results, method=method)]
            self.assertEqual(seeds, results["seeds"], method)

    def test_same_budget_for_every_method(self):
        results = self.sweep(EDGES, budgets=(250,))
        for r in results["trials"]["1"]["rows"]:
            self.assertLessEqual(r["search_calls"], 250)
            self.assertEqual(r["budget"], 250)

    def test_duplicate_proposals_count_once_and_shared_origins_are_kept(self):
        results = self.sweep(["2000.37", "2000.37", 2000.37, "2000.370", "40.00"])
        trial = results["trials"]["1"]
        self.assertEqual(trial["proposals"][COMPUTED]["amounts"], ["40.00", "2000.37"])
        d = self.rows(results, case="narrow-computed-range", method="D")[0]
        self.assertEqual(d["probes"]["muse"], ["40.00", "2000.37"])
        self.assertIn("40.00", d["probes"]["source"])
        self.assertEqual(d["probes"]["shared"], ["40.00"])

    def test_invalid_proposals_give_no_probes_and_change_nothing(self):
        results = self.sweep(["abc", "-3", "1.005", "2000000.00", None])
        trial = results["trials"]["1"]
        self.assertEqual(trial["proposals"][COMPUTED]["amounts"], [])
        self.assertEqual(len(trial["proposals"][COMPUTED]["issues"]), 5)
        # No usable proposals: the target is not a Muse target, and C/D/F equal A/B/E.
        self.assertEqual(trial["muse_targets"], [])
        for treated, control in (("C", "A"), ("D", "B"), ("F", "E")):
            for t, c in zip(self.rows(results, method=treated), self.rows(results, method=control)):
                self.assertEqual(t["report_sha256"], c["report_sha256"])

    def test_correct_targets_are_never_accused_whatever_is_proposed(self):
        results = self.sweep(EDGES + ["40.00", "40.01", "0.00", "1000000.00"], budgets=(250, 1000))
        controls = self.rows(results, role=mp.CORRECT_CONTROL)
        self.assertEqual(len(controls), 2 * 2 * 2 * len(mp.METHODS))
        for r in controls:
            self.assertEqual(r["confirmed_findings"], 0, r)
            self.assertFalse(r["false_accusation"])
            self.assertEqual(r["exit_code"], 0)

    def test_proposals_are_judged_on_the_target_not_trusted(self):
        # Proposals inside a range the target does NOT have: probed, never claimed.
        results = self.sweep(["3000.00", "3000.01", "5555.55"], budgets=(250,), seeds=1)
        c = self.rows(results, case="narrow-computed-range", method="C")[0]
        self.assertEqual(c["probes"]["muse"], ["3000.00", "3000.01", "5555.55"])
        for claim in c["claimed"]:
            self.assertFalse(Decimal("3000.00") <= Decimal(claim["start"]) <= Decimal("5555.55"))
        self.assertEqual(c["spurious_claims"], 0)

    def test_edge_proposals_locate_the_computed_range_at_every_seed(self):
        results = self.sweep(EDGES, budgets=(250,), seeds=3, cases=SMALL[:1])
        for r in self.rows(results, method="C") + self.rows(results, method="D"):
            self.assertTrue(r["detected"])
            self.assertTrue(r["intervals"][0]["exactly_located"])
            self.assertIn({"has_service_date": True, "start": "2000.37", "end": "2000.52"}, r["claimed"])
        paired = results["trials"]["1"]["paired"]
        self.assertEqual({(p["treated"], p["control"]) for p in paired}, set(mp.PAIRS))
        for p in paired:
            self.assertEqual(p["lost_seeds"], [])

    def test_deterministic_folding_alone_locates_the_computed_range(self):
        results = self.sweep(["3000.00"], budgets=(250,), seeds=3, cases=SMALL[:1])  # no edge proposals
        for r in self.rows(results, method="E"):
            self.assertEqual(r["probes"]["muse"], [])
            self.assertTrue(r["detected"])
            self.assertTrue(r["intervals"][0]["exactly_located"])
        for r in self.rows(results, method="B"):
            self.assertFalse(r["detected"])

    def test_unique_candidates_compare_muse_with_folding(self):
        results = self.sweep(EDGES, budgets=(250,), seeds=1, cases=SMALL[:1])
        unique = results["trials"]["1"]["unique_candidates"]
        self.assertEqual(len(unique), 1)
        u = unique[0]
        self.assertEqual(u["muse_not_in_e"], ["2000.36", "2000.38", "2000.44", "2000.51", "2000.53"])
        self.assertNotIn("2000.37", u["muse_not_in_e"])
        self.assertIn("2000.00", u["e_not_in_muse"])
        # 2000.36 and 2000.38 are already E's probes either side of 2000.37.
        self.assertNotIn("2000.36", u["muse_points_not_in_e"])
        self.assertIn("2000.44", u["muse_points_not_in_e"])

    def test_no_unique_candidates_without_a_search(self):
        results = self.sweep(EDGES, budgets=(0,), seeds=1, cases=SMALL[:1])
        self.assertEqual(results["trials"]["1"]["unique_candidates"], [])

    def test_sweep_is_deterministic_and_offline(self):
        def no_network(*args, **kwargs):
            raise AssertionError("network access attempted")
        with mock.patch("socket.socket.connect", no_network), \
                mock.patch("socket.create_connection", no_network), \
                mock.patch("requests.post", no_network):
            first = self.sweep(EDGES, budgets=(250,))
            second = self.sweep(EDGES, budgets=(250,))
        self.assertEqual(first["fingerprint"], second["fingerprint"])
        self.assertEqual([r["report_sha256"] for r in first["trials"]["1"]["rows"]],
                         [r["report_sha256"] for r in second["trials"]["1"]["rows"]])

    def test_rendered_table_has_one_line_per_seed_and_budget(self):
        results = self.sweep(EDGES, budgets=(0, 250), seeds=2, cases=SMALL[:1])
        text = mp.render_sweep(results)
        per_seed = [line for line in text.splitlines() if re.match(r"\| (0|250) \| \d+ \|", line)]
        self.assertEqual(len(per_seed), 4)
        self.assertIn("REPLAY_SYNTHETIC", text)


if __name__ == "__main__":
    unittest.main()
