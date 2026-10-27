import contextlib
import copy
import io
import json
import re
import socket
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import requests

from src.policyproof import demo, viewer
from src.policyproof.muse_client import replay_proposal
from src.policyproof.verification import _registry, verify
from src.policyproof.viewer import Alternative, ViewerError, render_report


ROOT = Path(__file__).resolve().parent.parent
POLICY_TEXT = (ROOT / "examples" / "democo_meal_policy.txt").read_text(encoding="utf-8")
FIXTURE = replay_proposal(ROOT / "tests" / "fixtures" / "muse_democo_meal_response.json", POLICY_TEXT)
REFERENCES, TARGETS = _registry()


def report_for(target=None, reference="democo-meal"):
    result = verify(
        FIXTURE.document, POLICY_TEXT, proposal=FIXTURE,
        reference=REFERENCES.get(reference), target=TARGETS.get(target),
    )
    return json.loads(result.to_json())


BUGGY = report_for("democo-buggy")
FIXED = report_for("democo-fixed")
NO_REFERENCE = report_for("democo-buggy", reference=None)


def shown_level(page):
    return re.search(r'id="verification-level">([^<]*)<', page).group(1)


def shown_codes(page):
    return re.findall(r'<span class="finding-code">([^<]*)</span>', page)


def shown_provenance(page):
    return re.search(r'id="provenance-label">(.*?)</span>', page).group(1)


class FaithfulRenderingTests(unittest.TestCase):
    def test_confirmed_forty_dollar_case(self):
        page = render_report(BUGGY)
        self.assertEqual(shown_level(page), "L2")
        target_section = page.split('id="headline"')[1].split("</section>")[0]
        self.assertEqual(shown_codes(target_section), ["TARGET_DISCREPANCY_CONFIRMED"])
        self.assertIn("Point <code>point-40.00-dated</code>: $40.00 with a service date", target_section)
        perspectives = re.search(r'<div class="perspectives">(.*?)</div>\s*<h4>', target_section, re.S).group(1)
        self.assertRegex(perspectives, r"Independent reference</p><span class=\"decision decision-approve\">APPROVE")
        self.assertRegex(perspectives, r"Proposed rules, executed</p><span class=\"decision decision-approve\">APPROVE")
        self.assertRegex(perspectives, r"Target under test</p><span class=\"decision decision-reject\">REJECT")
        self.assertIn("<blockquote>Meal claims of $40.00 or less are approved automatically.</blockquote>", target_section)
        self.assertIn("characters [212, 269)", target_section)
        self.assertIn("<code>democo-meal-approve-40</code>", target_section)
        self.assertIn("The model's own test case <code>exact-threshold</code>", target_section)
        self.assertIn("Amount stated in the policy text: threshold 40.00", target_section)
        self.assertIn("<strong>decides</strong> (first matching rule)", target_section)

    def test_fixed_target_case(self):
        page = render_report(FIXED)
        self.assertEqual(shown_level(page), "L3")
        self.assertNotIn("TARGET_DISCREPANCY", page)
        self.assertIn("No target discrepancy", page)

    def test_model_only_case(self):
        page = render_report(NO_REFERENCE)
        self.assertEqual(shown_level(page), "L1")
        self.assertIn("TARGET_DISCREPANCY_MODEL_ONLY", page)
        self.assertNotIn("TARGET_DISCREPANCY_CONFIRMED", page)
        self.assertIn("not independent evidence", page)

    def test_levels_and_findings_are_never_changed(self):
        for report in (BUGGY, FIXED, NO_REFERENCE):
            page = render_report(report)
            self.assertEqual(shown_level(page), report["verification"]["level"])
            all_findings = page.split('id="findings"')[1].split("</section>")[0]
            self.assertEqual(shown_codes(all_findings), [f["code"] for f in report["findings"]])

    def test_contradictory_report_is_shown_as_written(self):
        report = copy.deepcopy(BUGGY)
        report["verification"]["level"] = "L3"   # inconsistent with its own findings
        page = render_report(report)
        self.assertEqual(shown_level(page), "L3")
        self.assertEqual(shown_codes(page.split('id="headline"')[1].split("</section>")[0]),
                         ["TARGET_DISCREPANCY_CONFIRMED"])

    def test_report_is_not_mutated_and_output_is_deterministic(self):
        before = copy.deepcopy(BUGGY)
        first = render_report(BUGGY)
        self.assertEqual(BUGGY, before)
        self.assertEqual(first, render_report(json.loads(json.dumps(BUGGY))))

    def test_shared_assumption_and_limits_are_explained(self):
        page = render_report(BUGGY)
        self.assertIn("It encodes the same missing-date precedence assumption", page)
        self.assertIn("Interpretation assumption: this takes precedence over the amount rules", page)
        self.assertIn("A confirmed discrepancy is specific to its point", page)
        self.assertIn("semantic correctness", page)

    def test_precedence_findings_are_rendered(self):
        report = copy.deepcopy(FIXED)
        report["findings"].insert(0, {
            "code": "PRECEDENCE_DEPENDENT", "severity": "info",
            "summary": "review overrides approve only because of its priority.",
            "points": ["point-20.00-undated"], "rules": ["a", "b"],
            "details": {"reference_agrees_with_priority_result": True},
        })
        page = render_report(report)
        section = page.split('id="assumptions"')[1].split("</section>")[0]
        self.assertIn("review overrides approve only because of its priority.", section)
        self.assertIn("Reference agrees with the priority-based result: true", section)


class ProvenanceTests(unittest.TestCase):
    def test_label_is_taken_from_the_report_only(self):
        self.assertEqual(shown_provenance(render_report(BUGGY)), "REPLAY_SYNTHETIC")
        report = copy.deepcopy(BUGGY)
        report["proposal"]["model_reported"] = "muse-spark-1.3"
        report["proposal"]["response_id"] = "resp_looks_real_123"
        page = render_report(report)
        self.assertEqual(shown_provenance(page), "REPLAY_SYNTHETIC")
        self.assertIn('<section class="provenance provenance-synthetic"', page)
        self.assertNotIn('class="provenance provenance-live"', page)

    def test_missing_unknown_and_forged_labels(self):
        cases = [
            (None, "NOT STATED"),
            ("LIVE-ISH", "UNRECOGNISED: LIVE-ISH"),
            ("<b>LIVE</b>", "UNRECOGNISED: &lt;b&gt;LIVE&lt;/b&gt;"),
        ]
        for label, shown in cases:
            with self.subTest(label=label):
                report = copy.deepcopy(BUGGY)
                report["proposal"]["provenance_label"] = label
                page = render_report(report)
                self.assertEqual(shown_provenance(page), shown)
                self.assertIn('<section class="provenance provenance-unknown"', page)
        report = copy.deepcopy(BUGGY)
        del report["proposal"]
        self.assertEqual(shown_provenance(render_report(report)), "NOT STATED")

    def test_live_label_is_shown_when_the_report_says_live(self):
        report = copy.deepcopy(BUGGY)
        report["proposal"]["provenance_label"] = "LIVE"
        self.assertEqual(shown_provenance(render_report(report)), "LIVE")


class UntrustedContentTests(unittest.TestCase):
    PAYLOADS = [
        "<script>alert(1)</script>",
        "\"><img src=x onerror=alert(1)>",
        "<a href=\"javascript:alert(1)\">x</a>",
        "</style><script>alert(2)</script>",
        "<iframe src=https://evil.example></iframe>",
    ]

    def hostile_report(self, payload):
        report = copy.deepcopy(BUGGY)
        report["policy"]["policy_id"] = payload
        report["proposal"]["provenance"] = payload
        report["reference"]["description"] = payload
        report["verification"]["scope"] = payload
        report["verification"]["not_established"].append(payload)
        rule = report["rules"][1]
        rule["evidence"]["quote"] = payload
        rule["description"] = payload + " assumption"
        report["findings"][0]["summary"] = payload
        report["points"][0]["id"] = payload
        report["points"][6]["sources"].append({"kind": payload, "x": payload})
        report["points"][6]["target"]["error"] = payload
        report["findings"].append({"code": payload, "severity": payload, "summary": payload,
                                   "points": [payload]})
        return report

    def test_untrusted_text_is_escaped_never_markup(self):
        for payload in self.PAYLOADS:
            with self.subTest(payload=payload):
                page = render_report(self.hostile_report(payload),
                                     [Alternative(payload, self.hostile_report(payload), None)])
                lowered = page.lower()
                self.assertNotIn("<script", lowered)
                self.assertNotIn("<img", lowered)
                self.assertNotIn("<iframe", lowered)
                self.assertNotIn('href="javascript', lowered)
                self.assertNotIn("</style><", lowered)
                self.assertIn("&lt;", page)

    def test_page_cannot_run_scripts_or_load_remote_resources(self):
        page = render_report(self.hostile_report(self.PAYLOADS[0]))
        self.assertIn("default-src 'none'", page)
        self.assertNotIn("<script", page.lower())
        self.assertIsNone(re.search(r'(src|href)="(https?:)?//', page))

    def test_alternative_links_are_restricted_to_local_pages(self):
        for href, linked in [("evidence-fixed.html", True), ("javascript:alert(1)", False),
                             ("https://evil.example/x.html", False), ("../x.html", False),
                             ("a b.html", False), (None, False)]:
            with self.subTest(href=href):
                page = render_report(BUGGY, [Alternative("Fixed", FIXED, href)])
                self.assertEqual('<a href="' in page, linked)


class MalformedReportTests(unittest.TestCase):
    def test_non_object_reports_are_rejected(self):
        for value in [None, [], "report", 3]:
            with self.subTest(value=value), self.assertRaises(ViewerError):
                render_report(value)

    def test_empty_report_renders_placeholders(self):
        page = render_report({})
        self.assertEqual(shown_level(page), "UNRECOGNISED")
        self.assertEqual(shown_provenance(page), "NOT STATED")
        self.assertIn("No findings in report.", page)
        self.assertIn("No points in report.", page)
        self.assertIn("not_established list not in report", page)

    def test_wrong_types_and_missing_fields(self):
        report = copy.deepcopy(BUGGY)
        report["verification"]["level"] = "L9"
        report["verification"]["criteria"]["L2"]["met"] = "yes"
        report["findings"][0]["points"].append("point-missing")
        point = next(p for p in report["points"] if p["id"] == "point-40.00-dated")
        del point["interpreted"]["trace"]
        point["sources"] = "not a list"
        report["rules"][1]["evidence"]["span"] = ["212", None]
        page = render_report(report)
        self.assertEqual(shown_level(page), "UNRECOGNISED (L9)")
        self.assertIn("<strong>L2</strong> <span class=\"missing\">unknown</span>", page)
        self.assertIn("Point point-missing is not in the report.", page)
        self.assertIn("No decision trace in report.", page)
        self.assertIn("no sources in report", page)
        self.assertIn("position not in report", page)

    def test_unexpected_data_is_displayed_as_text(self):
        report = copy.deepcopy(BUGGY)
        report["unexpected"] = {"nested": [1, 2, {"x": "<b>"}]}
        report["findings"] = "not a list"
        report["points"] = [42, "text", None, {"id": None}]
        report["rules"] = {"not": "a list"}
        page = render_report(report)
        self.assertIn("No findings in report.", page)
        self.assertNotIn("<b>", page)

    def test_large_text_is_rendered_safely(self):
        report = copy.deepcopy(BUGGY)
        report["findings"][0]["summary"] = "<" * 100_000
        page = render_report(report)
        self.assertIn("&lt;" * 1000, page)


class IntegratedReportRenderingTests(unittest.TestCase):
    """Rendering of what the search, isolation and semantics work added."""

    def shown_verdict(self, page):
        return re.search(r'id="verdict">([^<]*)<', page).group(1)

    def test_verdict_matches_the_report(self):
        for report in (BUGGY, FIXED, NO_REFERENCE):
            page = render_report(report)
            self.assertEqual(self.shown_verdict(page), report["verification"]["result"]["label"])
            self.assertIn(f"exit code {report['verification']['result']['exit_code']}", page)

    def test_loophole_range_and_search_evidence(self):
        page = render_report(report_for("democo-loophole"))
        self.assertIn("<strong>Range found by the target search:</strong> $1000.00 to $4999.99 with a service date", page)
        self.assertIn("the lower edge is verified to the cent (agrees at $999.99)", page)
        self.assertIn("the upper edge is verified to the cent (agrees at $5000.00)", page)
        self.assertIn("Found by the target search (seed 20261104): lowest disagreeing amount of the range", page)
        self.assertIn("<strong>Target search.</strong> 1500 target calls", page)
        self.assertNotIn('"kind": "target_search"', page)  # no raw-JSON fallback any more

    def test_timeout_outcome_and_isolated_execution(self):
        from src.policyproof.verification import Implementation
        hang = Implementation("hang", "", lambda c: None, "tests.isolation_targets:hangs_at_forty")
        refs, _ = _registry()
        report = json.loads(verify(FIXTURE.document, POLICY_TEXT, proposal=FIXTURE, reference=refs["democo-meal"],
                                   target=hang, target_timeout=0.5, search_budget=30).to_json())
        page = render_report(report)
        target = page.split('id="headline"')[1].split("</section>")[0]
        self.assertIn('<span class="failure">timeout</span>', target)
        self.assertIn("timed out after 0.5 s; the worker process was killed", target)
        self.assertIn("ran in a separate worker process with a 0.5 s timeout per call", page)
        self.assertIn("not a security sandbox", page)

    def test_disputed_reasons_are_shown(self):
        report = copy.deepcopy(BUGGY)
        finding = next(f for f in report["findings"] if f["code"] == "TARGET_DISCREPANCY_CONFIRMED")
        finding["code"], finding["severity"] = "TARGET_DISCREPANCY_DISPUTED", "warning"
        finding["details"]["disputed_because"] = ["the proposal's own expected decision (APPROVE) contradicts the reference"]
        page = render_report(report)
        self.assertIn("<strong>Why not confirmed:</strong>", page)
        self.assertIn("the proposal&#x27;s own expected decision (APPROVE) contradicts the reference", page)

    def test_new_fields_are_escaped(self):
        payload = "<script>alert(1)</script>"
        report = copy.deepcopy(report_for("democo-loophole"))
        report["verification"]["result"]["meaning"] = payload
        report["target_execution"]["note"] = payload
        report["target_search"]["seed"] = payload
        rng = next(f for f in report["findings"] if f["details"].get("kind") == "range")
        rng["details"]["start"] = payload
        rng["details"]["disputed_because"] = [payload]
        point = next(p for p in report["points"] if p["id"] == rng["points"][1])
        point["target"]["failure"] = payload
        point["sources"][0]["role"] = payload
        page = render_report(report)
        self.assertNotIn("<script", page.lower())
        self.assertGreaterEqual(page.count("&lt;script&gt;"), 7)

    def test_unknown_or_missing_verdict(self):
        for value in (None, {"label": "<b>PASS</b>"}, "OK"):
            with self.subTest(value=value):
                report = copy.deepcopy(BUGGY)
                report["verification"]["result"] = value
                self.assertEqual(self.shown_verdict(render_report(report)), "Run result not in report")

    def test_rendering_is_deterministic(self):
        report = report_for("democo-loophole")
        self.assertEqual(render_report(report), render_report(json.loads(json.dumps(report))))


class CommandLineTests(unittest.TestCase):
    def run_main(self, module, argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = module.main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_viewer_cli_writes_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "report.json"
            report.write_text(json.dumps(BUGGY), encoding="utf-8")
            other = Path(tmp) / "fixed.json"
            other.write_text(json.dumps(FIXED), encoding="utf-8")
            page = Path(tmp) / "page.html"
            code, _, _ = self.run_main(viewer, [str(report), "--output", str(page),
                                                "--alternative", f"Fixed={other}"])
            self.assertEqual(code, 0)
            self.assertEqual(page.read_text(encoding="utf-8"),
                             render_report(BUGGY, [Alternative("Fixed", FIXED)]))
            code, _, err = self.run_main(viewer, [str(report), "--output", str(page)])
            self.assertEqual(code, 1)
            self.assertIn("--overwrite", err)
            self.assertEqual(self.run_main(viewer, [str(report), "--output", str(page), "--overwrite"])[0], 0)

    def test_viewer_cli_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "bad.json"
            bad.write_text("{not json", encoding="utf-8")
            array = Path(tmp) / "array.json"
            array.write_text("[]", encoding="utf-8")
            out = str(Path(tmp) / "out.html")
            for argv, fragment in [
                ([str(bad), "--output", out], "not valid JSON"),
                ([str(array), "--output", out], "must be a JSON object"),
                ([str(Path(tmp) / "missing.json"), "--output", out], "cannot read"),
                ([str(array), "--output", out, "--alternative", "no-equals-sign"], "LABEL=REPORT.json"),
            ]:
                with self.subTest(fragment=fragment):
                    code, _, err = self.run_main(viewer, argv)
                    self.assertEqual(code, 1)
                    self.assertIn(fragment, err)
            self.assertFalse(Path(out).exists())


class DemoTests(unittest.TestCase):
    def test_demo_runs_offline_and_reproduces_the_documented_results(self):
        attempts = []

        def blocked(*args, **kwargs):
            attempts.append(args)
            raise OSError("network blocked")

        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(socket, "getaddrinfo", blocked), \
                mock.patch.object(socket.socket, "connect", blocked), \
                mock.patch.object(requests.Session, "send", blocked), \
                mock.patch.dict("os.environ", {}, clear=True):
            out_dir = Path(tmp) / "demo"
            code, out, _ = self.run_demo(["--output-dir", str(out_dir)])
            self.assertEqual(code, 0)
            self.assertEqual(out.count("verification exit code: 3 (documented: 3)"), 2)
            self.assertEqual(out.count("verification exit code: 0 (documented: 0)"), 1)
            self.assertEqual(out.count("verification exit code: 4 (documented: 4)"), 1)

            buggy = json.loads((out_dir / "report-buggy.json").read_text(encoding="utf-8"))
            confirmed = [f for f in buggy["findings"] if f["code"] == "TARGET_DISCREPANCY_CONFIRMED"]
            self.assertEqual([f["points"] for f in confirmed], [["point-40.00-dated"]])
            self.assertEqual(buggy["proposal"]["provenance_label"], "REPLAY_SYNTHETIC")
            names = ("buggy", "fixed", "no-reference", "loophole")
            reports = {name: json.loads((out_dir / f"report-{name}.json").read_text(encoding="utf-8")) for name in names}
            self.assertEqual({n: r["verification"]["level"] for n, r in reports.items()},
                             {"buggy": "L2", "fixed": "L3", "no-reference": "L1", "loophole": "L2"})
            self.assertEqual({n: r["verification"]["result"]["label"] for n, r in reports.items()},
                             {"buggy": "FAILED", "fixed": "OK", "no-reference": "INCONCLUSIVE", "loophole": "FAILED"})
            loophole = [f["details"] for f in reports["loophole"]["findings"] if f["details"].get("kind") == "range"]
            self.assertEqual([(d["start"], d["end"]) for d in loophole], [("1000.00", "4999.99")])

            page = (out_dir / "evidence-buggy.html").read_text(encoding="utf-8")
            for other in ("fixed", "no-reference", "loophole"):
                self.assertIn(f'<a href="evidence-{other}.html">', page)
            first = {p.name: p.read_bytes() for p in out_dir.iterdir()}

            code, _, err = self.run_demo(["--output-dir", str(out_dir)])
            self.assertEqual(code, 1)
            self.assertIn("--overwrite", err)
            self.assertEqual({p.name: p.read_bytes() for p in out_dir.iterdir()}, first)

            code, _, _ = self.run_demo(["--output-dir", str(out_dir), "--overwrite"])
            self.assertEqual(code, 0)
            self.assertEqual({p.name: p.read_bytes() for p in out_dir.iterdir()}, first)
        self.assertEqual(attempts, [])

    def run_demo(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = demo.main(argv)
        return code, out.getvalue(), err.getvalue()


if __name__ == "__main__":
    unittest.main()
