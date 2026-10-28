"""Static HTML evidence viewer for PolicyProof JSON reports.

The JSON report is the only source of truth. The viewer reads it and lays
it out; it never re-runs rules, recomputes findings or changes a level.
Explanatory sentences are fixed text describing what each part means.

Every value taken from the report is HTML-escaped. The page contains no
JavaScript and declares a Content Security Policy that forbids scripts,
remote resources and form submission, so text from a policy or a model can
never execute and the page makes no network requests.

Usage:
    python -m src.policyproof.viewer REPORT.json --output PAGE.html
        [--alternative "LABEL=OTHER_REPORT.json" ...] [--overwrite]
"""

import argparse
import html
import json
import re
import sys
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any


KNOWN_LEVELS = ("NONE", "L0", "L1", "L2", "L3")
PROVENANCE_LABELS = {
    "LIVE": ("Live Muse Spark call", "live"),
    "REPLAY_SAVED_LIVE_RESPONSE": ("Replay of a saved response", "saved"),
    "REPLAY_SYNTHETIC": ("Replay of a synthetic fixture: not Muse Spark output", "synthetic"),
    "REPLAY_UNKNOWN_ORIGIN": ("Replay of a response of unknown origin", "unknown"),
    "UNKNOWN": ("Origin not recorded", "unknown"),
}
TARGET_CODES = (
    "TARGET_DISCREPANCY_CONFIRMED",
    "TARGET_DISCREPANCY_DISPUTED",
    "TARGET_DISCREPANCY_MODEL_ONLY",
)
SAFE_LINK = re.compile(r"[A-Za-z0-9._-]+\.html")
MISSING = "not in report"

CONTENT_SECURITY_POLICY = (
    "default-src 'none'; style-src 'unsafe-inline'; img-src 'none'; "
    "form-action 'none'; base-uri 'none'"
)


class ViewerError(ValueError):
    pass


@dataclass(frozen=True)
class Alternative:
    label: str
    report: Any
    href: str | None = None


def render_report(report: Any, alternatives: Iterable[Alternative] = ()) -> str:
    """Render one report, with optional summaries of alternative runs, as a
    self-contained HTML page. Raises ViewerError if the report is not a
    JSON object; anything else missing is shown as missing."""
    if not isinstance(report, dict):
        raise ViewerError("report must be a JSON object")
    alternatives = tuple(alternatives)
    points = {
        p.get("id"): p for p in _list(report.get("points")) if isinstance(p, dict)
    }
    rules = {
        r.get("id"): r for r in _list(report.get("rules")) if isinstance(r, dict)
    }
    findings = [f for f in _list(report.get("findings")) if isinstance(f, dict)]
    sections = [
        _header(report),
        _provenance(report),
        _executive(report, findings),
        _headline(findings, points, rules, report),
        _all_findings(findings),
        _assumptions(report, findings, rules),
        _points_table(points),
        _rules_table(rules),
        _limits(report),
        _alternatives(alternatives),
        _footer(report),
    ]
    policy_id = _get(report, "policy", "policy_id")
    title = f"PolicyProof evidence: {policy_id}" if policy_id else "PolicyProof evidence"
    return (
        "<!doctype html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n"
        f"<meta http-equiv=\"Content-Security-Policy\" content=\"{CONTENT_SECURITY_POLICY}\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        "<meta name=\"referrer\" content=\"no-referrer\">\n"
        f"<title>{_e(title)}</title>\n<style>{_CSS}</style>\n</head>\n<body>\n<main>\n"
        + "\n".join(section for section in sections if section)
        + "\n</main>\n</body>\n</html>\n"
    )


# ---------------------------------------------------------------- helpers


def _e(value: Any) -> str:
    if value is None:
        return f"<span class=\"missing\">{MISSING}</span>"
    if isinstance(value, bool):
        return "true" if value else "false"
    return html.escape(str(value), quote=True)


def _get(data: Any, *keys: str) -> Any:
    for key in keys:
        if not isinstance(data, dict):
            return None
        data = data.get(key)
    return data


def _list(value: Any) -> list:
    return value if isinstance(value, list) else []


def _slug(value: Any) -> str:
    return re.sub(r"[^a-z0-9-]", "", str(value).lower().replace("_", "-"))[:40]


def _decision(value: Any) -> str:
    if value in ("APPROVE", "REJECT", "REVIEW"):
        return f"<span class=\"decision decision-{_slug(value)}\">{_e(value)}</span>"
    if value is None:
        return "<span class=\"decision decision-none\">no decision</span>"
    return f"<span class=\"decision decision-none\">{_e(value)}</span>"


def _span(value: Any) -> str:
    if (
        isinstance(value, list) and len(value) == 2
        and all(isinstance(v, int) and not isinstance(v, bool) for v in value)
    ):
        return f"characters [{value[0]}, {value[1]})"
    return "<span class=\"missing\">position not in report</span>"


def _level(report: dict) -> str:
    level = _get(report, "verification", "level")
    if level in KNOWN_LEVELS:
        return str(level)
    return f"UNRECOGNISED ({level})" if level is not None else "UNRECOGNISED"


def _met(value: Any) -> str:
    if value is True:
        return "<span class=\"met\">met</span>"
    if value is False:
        return "<span class=\"not-met\">not met</span>"
    return "<span class=\"missing\">unknown</span>"


# --------------------------------------------------------------- sections


def _header(report: dict) -> str:
    policy = report.get("policy") if isinstance(report.get("policy"), dict) else {}
    return (
        "<header>\n<p class=\"eyebrow\">PolicyProof evidence report</p>\n"
        "<h1>Muse proposes. PolicyProof verifies. Every finding has evidence.</h1>\n"
        "<dl class=\"meta\">"
        f"<div><dt>Policy</dt><dd>{_e(policy.get('policy_id'))}</dd></div>"
        f"<div><dt>Policy SHA-256</dt><dd><code>{_e(policy.get('sha256'))}</code></dd></div>"
        f"<div><dt>Reference</dt><dd>{_e(_get(report, 'reference', 'name') or 'none supplied')}</dd></div>"
        f"<div><dt>Target</dt><dd>{_e(_get(report, 'target', 'name') or 'none supplied')}</dd></div>"
        "</dl>\n</header>"
    )


def _provenance(report: dict) -> str:
    proposal = report.get("proposal") if isinstance(report.get("proposal"), dict) else {}
    label = proposal.get("provenance_label")
    if label in PROVENANCE_LABELS:
        meaning, style = PROVENANCE_LABELS[label]
        shown = _e(label)
    else:
        meaning, style = "Unrecognised provenance label: treat the origin as unknown", "unknown"
        shown = f"UNRECOGNISED: {_e(label)}" if label is not None else "NOT STATED"
    return (
        f"<section class=\"provenance provenance-{style}\" aria-label=\"Provenance\">\n"
        f"<p><span class=\"badge\" id=\"provenance-label\">{shown}</span> {_e(meaning)}</p>\n"
        f"<p>{_e(proposal.get('provenance'))}</p>\n"
        "<p class=\"small\">"
        f"Response id: <code>{_e(proposal.get('response_id'))}</code> · "
        f"Model named in the response: <code>{_e(proposal.get('model_reported'))}</code>. "
        f"{_e(proposal.get('note'))}</p>\n</section>"
    )


def _executive(report: dict, findings: list[dict]) -> str:
    verification = report.get("verification") if isinstance(report.get("verification"), dict) else {}
    criteria = verification.get("criteria") if isinstance(verification.get("criteria"), dict) else {}
    rows = "".join(
        f"<li><strong>{_e(name)}</strong> {_met(_get(criteria, name, 'met'))}"
        f" <span class=\"small\">{_e(_get(criteria, name, 'detail'))}</span></li>"
        for name in ("L0", "L1", "L2", "L3")
    )
    severities = Counter(str(f.get("severity")) for f in findings)
    counts = ", ".join(
        f"{severities[s]} {s}" for s in ("error", "warning", "info") if severities[s]
    ) or "none"
    return (
        "<section aria-labelledby=\"result\">\n<h2 id=\"result\">Result</h2>\n"
        f"{_verdict(verification.get('result'))}\n"
        "<div class=\"result\">\n"
        f"<p class=\"level\"><span class=\"small\">Verification level</span>"
        f"<span id=\"verification-level\">{_e(_level(report))}</span></p>\n"
        f"<div><p>{_e(verification.get('level_meaning'))}</p>\n"
        f"<ul class=\"criteria\">{rows}</ul>\n"
        f"<p class=\"small\">Findings in this report: {_e(counts)}.</p></div>\n"
        "</div>\n"
        f"<p><strong>What was checked.</strong> {_e(verification.get('scope'))}</p>\n"
        f"{_execution_summary(report.get('target_execution'))}"
        f"{_search_summary(report.get('target_search'))}</section>"
    )


VERDICT_LABELS = ("OK", "FAILED", "INCONCLUSIVE", "INSUFFICIENT_EVIDENCE", "REJECTED", "ERROR")


def _verdict(result: Any) -> str:
    if not isinstance(result, dict) or result.get("label") not in VERDICT_LABELS:
        return "<p class=\"verdict\"><span id=\"verdict\">Run result not in report</span></p>"
    label = result["label"]
    return (
        f"<p class=\"verdict verdict-{_slug(label)}\"><span id=\"verdict\">{_e(label)}</span> "
        f"<span class=\"small\">exit code {_e(result.get('exit_code'))}: {_e(result.get('meaning'))}</span></p>"
    )


def _execution_summary(execution: Any) -> str:
    if not isinstance(execution, dict) or execution.get("mode") in (None, "none"):
        return ""
    if execution.get("mode") == "isolated-worker-process":
        text = (
            f"The target ran in a separate worker process with a {_e(execution.get('timeout_seconds'))} s "
            f"timeout per call: {_e(execution.get('calls'))} calls, {_e(execution.get('timeouts'))} timeout(s), "
            f"{_e(execution.get('worker_crashes'))} crash(es), {_e(execution.get('not_run'))} skipped. "
        )
    else:
        text = f"Target execution: {_e(execution.get('mode'))}. "
    return f"<p class=\"small\"><strong>Target execution.</strong> {text}{_e(execution.get('note'))}</p>\n"


def _search_summary(search: Any) -> str:
    if not isinstance(search, dict) or search.get("performed") is not True:
        return ""
    return (
        "<p class=\"small\"><strong>Target search.</strong> "
        f"{_e(search.get('target_calls'))} target calls (budget {_e(search.get('budget'))}, seed "
        f"{_e(search.get('seed'))}) between the evaluated points; {_e(search.get('ranges_found'))} "
        "discrepancy range(s) found"
        + (f"; {_e(search.get('unjudged_evaluations'))} call(s) could not be judged, so nothing is "
           "concluded there" if search.get("unjudged_evaluations") else "")
        + ". This is sampling, not exhaustive checking.</p>\n"
    )


def _headline(findings, points, rules, report) -> str:
    targeted = [f for f in findings if f.get("code") in TARGET_CODES]
    unfinished = _unfinished(findings)
    if not targeted:
        if _get(report, "target") is None:
            note = "No target was supplied, so no implementation was checked."
        elif unfinished:
            note = "No target discrepancy was established, but the check is incomplete (below)."
        else:
            note = "No target discrepancy: the target agreed wherever it was compared."
        return (
            "<section aria-labelledby=\"headline\">\n<h2 id=\"headline\">Target findings</h2>\n"
            f"<p class=\"callout\">{_e(note)}</p>\n{unfinished}</section>"
        )
    cards = "\n".join(_target_card(f, points, rules, report) for f in targeted)
    return (
        "<section aria-labelledby=\"headline\">\n<h2 id=\"headline\">Target findings</h2>\n"
        f"{cards}\n{unfinished}</section>"
    )


def _unfinished(findings) -> str:
    """Points where the target call never finished, with their cause: never
    presented as agreement, nor as a wrong decision."""
    for finding in findings:
        details = finding.get("details") or {}
        if finding.get("code") != "UNSUPPORTED" or "failures" not in details:
            continue
        errors = details.get("errors") or {}
        kinds = ", ".join(f"<span class=\"failure\">{_e(kind)}</span> × {_e(n)}"
                          for kind, n in sorted((details.get("failures") or {}).items()))
        items = "".join(f"<li>{_e(point_id)}: {_e(error)}</li>" for point_id, error in errors.items())
        return (
            f"<p>The target did not finish at {len(errors)} point(s): {kinds}. That is not "
            "evidence of a wrong decision, and nothing is concluded about the target there.</p>\n"
            f"<ul>{items}</ul>\n"
        )
    return ""


def _target_card(finding, points, rules, report) -> str:
    code = finding.get("code")
    explanation = {
        "TARGET_DISCREPANCY_CONFIRMED": "Confirmed at this point: the independent reference and "
        "the executed proposed rules agree with each other, and the target differs.",
        "TARGET_DISCREPANCY_DISPUTED": "Disputed: the perspectives needed to confirm this do not "
        "agree here (reasons below), so a person must decide what the policy requires.",
        "TARGET_DISCREPANCY_MODEL_ONLY": "Model-only: no usable reference here. Only the "
        "model's rules contradict the target, which is not independent evidence.",
    }[code]
    parts = [
        f"<article class=\"finding severity-{_slug(finding.get('severity'))}\">",
        f"<p><span class=\"finding-code\">{_e(code)}</span> "
        f"<span class=\"severity\">{_e(finding.get('severity'))}</span></p>",
        f"<p class=\"summary\">{_e(finding.get('summary'))}</p>",
        f"<p class=\"small\">{_e(explanation)}</p>",
    ]
    details = finding.get("details") if isinstance(finding.get("details"), dict) else {}
    reasons = [r for r in _list(details.get("disputed_because")) if r]
    if reasons:
        parts.append("<p><strong>Why not confirmed:</strong></p><ul class=\"reasons\">"
                     + "".join(f"<li>{_e(r)}</li>" for r in reasons) + "</ul>")
    if details.get("kind") == "range":
        dated = details.get("has_service_date")
        where = "with" if dated is True else "without" if dated is False else "unknown"

        def edge(verified: Any, outside: Any, side: str) -> str:
            if outside is None:
                return f"the {side} edge reaches the end of the domain"
            state = "verified to the cent" if verified is True else "not located to the cent"
            return f"the {side} edge is {state} (agrees at ${_e(outside)})"

        parts.append(
            f"<p class=\"range\"><strong>Range found by the target search:</strong> "
            f"${_e(details.get('start'))} to ${_e(details.get('end'))} {_e(where)} a service date; "
            f"{edge(details.get('lower_edge_verified'), details.get('agrees_below'), 'lower')}; "
            f"{edge(details.get('upper_edge_verified'), details.get('agrees_above'), 'upper')}. "
            f"{_e(details.get('disagreeing_amounts_evaluated'))} disagreeing amounts evaluated inside; "
            "the rest of the range was sampled, not checked.</p>"
        )
    for point_id in _list(finding.get("points")):
        point = points.get(point_id)
        if point is None:
            parts.append(f"<p class=\"missing\">Point {_e(point_id)} is not in the report.</p>")
            continue
        parts.append(_perspectives(point))
        parts.append(_evidence_chain(point, rules, report))
        parts.append(_trace(point))
    parts.append("</article>")
    return "\n".join(parts)


def _perspectives(point: dict) -> str:
    interpreted = point.get("interpreted") if isinstance(point.get("interpreted"), dict) else {}
    expectations = [e for e in _list(point.get("model_expectations")) if isinstance(e, dict)]
    expected = " ".join(_decision(e.get("expected_decision")) for e in expectations) or "<span class=\"small\">none proposed</span>"
    reference = point.get("reference")
    target = point.get("target")

    def outcome(value: Any) -> str:
        if not isinstance(value, dict):
            return "<span class=\"small\">not supplied</span>"
        text = _decision(value.get("decision"))
        if value.get("failure"):
            text += f"<br><span class=\"failure\">{_e(value.get('failure'))}</span>"
        if value.get("error"):
            text += f"<br><span class=\"small\">{_e(value.get('error'))}</span>"
        return text

    dated = point.get("has_service_date")
    where = "with a service date" if dated is True else "without a service date" if dated is False else "service date unknown"
    return (
        f"<h3>Point <code>{_e(point.get('id'))}</code>: ${_e(point.get('amount'))} {_e(where)}</h3>\n"
        "<div class=\"perspectives\">"
        f"<div><p class=\"small\">Independent reference</p>{outcome(reference)}</div>"
        f"<div><p class=\"small\">Proposed rules, executed</p>{_decision(interpreted.get('decision'))}"
        f"<br><span class=\"small\">rule {_e(interpreted.get('decided_by'))}</span></div>"
        f"<div><p class=\"small\">Target under test</p>{outcome(target)}</div>"
        f"<div><p class=\"small\">Model's expected decision</p>{expected}</div>"
        "</div>"
    )


def _evidence_chain(point: dict, rules: dict, report: dict) -> str:
    interpreted = point.get("interpreted") if isinstance(point.get("interpreted"), dict) else {}
    rule = rules.get(interpreted.get("decided_by"))
    items = []
    if rule is None:
        items.append("<li class=\"missing\">The deciding rule is not in the report.</li>")
    else:
        evidence = rule.get("evidence") if isinstance(rule.get("evidence"), dict) else {}
        items.append(
            f"<li><strong>Policy text</strong> ({_span(evidence.get('span'))} of the policy "
            f"with SHA-256 <code>{_e(_short(_get(report, 'policy', 'sha256')))}</code>)"
            f"<blockquote>{_e(evidence.get('quote'))}</blockquote></li>"
        )
        items.append(
            f"<li><strong>Rule</strong> <code>{_e(rule.get('id'))}</code> "
            f"(priority {_e(rule.get('priority'))}): if {_conditions(rule)} then "
            f"{_decision(rule.get('decision'))}</li>"
        )
    sources = "".join(f"<li>{_source(s)}</li>" for s in _list(point.get("sources")))
    sources = sources or "<li class=\"missing\">no sources in report</li>"
    items.append(f"<li><strong>Why this point was tested</strong><ul>{sources}</ul></li>")
    return f"<h4>Evidence chain</h4>\n<ol class=\"chain\">{''.join(items)}</ol>"


def _short(value: Any) -> Any:
    return f"{value[:12]}…" if isinstance(value, str) and len(value) > 12 else value


def _conditions(rule: dict) -> str:
    conditions = [c for c in _list(rule.get("conditions")) if isinstance(c, dict)]
    if not conditions:
        return "<em>always</em>"
    return " and ".join(
        f"<code>{_e(c.get('field'))} {_e(c.get('operator'))} {_e(c.get('value'))}</code>"
        for c in conditions
    )


def _source(source: Any) -> str:
    if not isinstance(source, dict):
        return _e(source)
    kind = source.get("kind")
    if kind == "rule_threshold":
        return (f"Boundary of rule <code>{_e(source.get('rule_id'))}</code> condition "
                f"{_e(source.get('condition_index'))}: threshold {_e(source.get('threshold'))}, "
                f"offset {_e(source.get('offset'))}")
    if kind == "policy_text_amount":
        return (f"Amount stated in the policy text: threshold {_e(source.get('threshold'))}, "
                f"offset {_e(source.get('offset'))} ({_e(source.get('label'))})")
    if kind == "model_test_case":
        return f"The model's own test case <code>{_e(source.get('case_id'))}</code>"
    if kind == "target_search":
        return (f"Found by the target search (seed {_e(source.get('seed'))}): "
                f"{_e(source.get('role'))}")
    if kind == "domain_bound":
        return f"Domain bound: {_e(source.get('label'))}"
    return f"{_e(kind)}: {_e(json.dumps(source, sort_keys=True, default=str))}"


def _trace(point: dict) -> str:
    interpreted = point.get("interpreted") if isinstance(point.get("interpreted"), dict) else {}
    traces = [t for t in _list(interpreted.get("trace")) if isinstance(t, dict)]
    if not traces:
        return "<h4>Rule trace</h4>\n<p class=\"missing\">No decision trace in report.</p>"
    decider = next((t.get("rule_id") for t in traces if t.get("decided") is True), None)
    rows = []
    for trace in traces:
        conditions = [c for c in _list(trace.get("conditions")) if isinstance(c, dict)]
        checks = "<br>".join(
            f"<code>{_e(c.get('field'))} {_e(c.get('operator'))} {_e(c.get('expected'))}</code>"
            f" with {_e(c.get('actual'))}: {'holds' if c.get('holds') is True else 'fails' if c.get('holds') is False else 'unknown'}"
            for c in conditions
        ) or "<em>no conditions: always matches</em>"
        if trace.get("decided") is True:
            outcome = "<strong>decides</strong> (first matching rule)"
        elif trace.get("matched") is True:
            outcome = f"matches, but overridden by higher-priority rule <code>{_e(decider)}</code>"
        elif trace.get("matched") is False:
            outcome = "does not match"
        else:
            outcome = "<span class=\"missing\">unknown</span>"
        rows.append(
            f"<tr><td>{_e(trace.get('priority'))}</td><td><code>{_e(trace.get('rule_id'))}</code></td>"
            f"<td>{_decision(trace.get('decision'))}</td><td>{checks}</td><td>{outcome}</td></tr>"
        )
    return (
        "<h4>Rule trace</h4>\n<p class=\"small\">Rules are evaluated in priority order; "
        "the first rule whose conditions all hold decides. Every rule is still traced.</p>\n"
        "<div class=\"scroll\"><table><thead><tr><th scope=\"col\">Priority</th>"
        "<th scope=\"col\">Rule</th><th scope=\"col\">Decision</th><th scope=\"col\">Conditions at this point</th>"
        f"<th scope=\"col\">Outcome</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div>"
    )


def _all_findings(findings: list[dict]) -> str:
    if not findings:
        return ("<section aria-labelledby=\"findings\">\n<h2 id=\"findings\">All findings</h2>\n"
                "<p class=\"missing\">No findings in report.</p>\n</section>")
    items = "".join(
        f"<li class=\"severity-{_slug(f.get('severity'))}\"><span class=\"finding-code\">{_e(f.get('code'))}</span> "
        f"<span class=\"severity\">{_e(f.get('severity'))}</span><br>{_e(f.get('summary'))}"
        + (f"<br><span class=\"small\">Points: {_e(', '.join(map(str, _list(f.get('points')))))}</span>"
           if _list(f.get("points")) else "")
        + "</li>"
        for f in findings
    )
    return (f"<section aria-labelledby=\"findings\">\n<h2 id=\"findings\">All findings</h2>\n"
            f"<ul class=\"findings\">{items}</ul>\n</section>")


def _assumptions(report: dict, findings: list[dict], rules: dict) -> str:
    precedence = [f for f in findings if f.get("code") == "PRECEDENCE_DEPENDENT"]
    recorded = [
        r for r in rules.values()
        if isinstance(r.get("description"), str) and "assumption" in r["description"].lower()
    ]
    parts = [
        "<section aria-labelledby=\"assumptions\">\n<h2 id=\"assumptions\">Interpretation assumptions</h2>",
        "<p>When several rules match the same input with different decisions, only their "
        "priority decides. If the policy text does not state that order, the result rests on "
        "an assumption, and PolicyProof reports it rather than hiding it.</p>",
    ]
    if precedence:
        for finding in precedence:
            details = finding.get("details") if isinstance(finding.get("details"), dict) else {}
            agrees = details.get("reference_agrees_with_priority_result")
            parts.append(
                f"<article class=\"finding severity-{_slug(finding.get('severity'))}\">"
                f"<p><span class=\"finding-code\">PRECEDENCE_DEPENDENT</span> "
                f"<span class=\"severity\">{_e(finding.get('severity'))}</span></p>"
                f"<p>{_e(finding.get('summary'))}</p>"
                f"<p class=\"small\">Points: {_e(', '.join(map(str, _list(finding.get('points')))))}. "
                f"Reference agrees with the priority-based result: {_e(agrees)}.</p></article>"
            )
    else:
        parts.append("<p class=\"callout\">No evaluated point was decided only by priority in this run.</p>")
    if recorded:
        quotes = "".join(
            f"<li><code>{_e(r.get('id'))}</code>: {_e(r.get('description'))}</li>" for r in recorded
        )
        parts.append(f"<h3>Assumptions recorded in the proposed rules</h3><ul>{quotes}</ul>")
    parts.append(
        "<h3>About the reference</h3>"
        f"<p>{_e(_get(report, 'reference', 'description') or 'No reference was supplied.')}</p>"
        "<p class=\"small\">A reference that shares an assumption with the proposed rules does "
        "not independently confirm that assumption.</p>\n</section>"
    )
    return "\n".join(parts)


def _points_table(points: dict) -> str:
    rows = []
    for point in points.values():
        interpreted = point.get("interpreted") if isinstance(point.get("interpreted"), dict) else {}
        expected = " ".join(
            _decision(e.get("expected_decision"))
            for e in _list(point.get("model_expectations")) if isinstance(e, dict)
        ) or "<span class=\"small\">—</span>"
        sources = ", ".join(
            sorted({str(s.get("kind")) for s in _list(point.get("sources")) if isinstance(s, dict)})
        )
        reference = point.get("reference")
        target = point.get("target")
        rows.append(
            f"<tr><td><code>{_e(point.get('id'))}</code></td><td>{_e(point.get('amount'))}</td>"
            f"<td>{_e(point.get('has_service_date'))}</td>"
            f"<td>{_decision(interpreted.get('decision'))}</td>"
            f"<td>{expected}</td>"
            f"<td>{_decision(reference.get('decision')) if isinstance(reference, dict) else '—'}</td>"
            f"<td>{_decision(target.get('decision')) if isinstance(target, dict) else '—'}</td>"
            f"<td class=\"small\">{_e(sources)}</td></tr>"
        )
    body = "".join(rows) or "<tr><td colspan=\"8\" class=\"missing\">No points in report.</td></tr>"
    return (
        "<section aria-labelledby=\"points\">\n<h2 id=\"points\">Every evaluated point</h2>\n"
        "<div class=\"scroll\"><table><thead><tr><th scope=\"col\">Point</th><th scope=\"col\">Amount</th>"
        "<th scope=\"col\">Service date</th><th scope=\"col\">Proposed rules</th><th scope=\"col\">Model expected</th>"
        "<th scope=\"col\">Reference</th><th scope=\"col\">Target</th><th scope=\"col\">Sources</th></tr></thead>"
        f"<tbody>{body}</tbody></table></div>\n</section>"
    )


def _rules_table(rules: dict) -> str:
    rows = "".join(
        f"<tr><td>{_e(r.get('priority'))}</td><td><code>{_e(r.get('id'))}</code></td>"
        f"<td>{_conditions(r)}</td><td>{_decision(r.get('decision'))}</td>"
        f"<td><blockquote>{_e(_get(r, 'evidence', 'quote'))}</blockquote>"
        f"<span class=\"small\">{_span(_get(r, 'evidence', 'span'))}</span></td></tr>"
        for r in rules.values()
    ) or "<tr><td colspan=\"5\" class=\"missing\">No rules in report.</td></tr>"
    return (
        "<section aria-labelledby=\"rules\">\n<h2 id=\"rules\">Proposed rules and their evidence</h2>\n"
        "<div class=\"scroll\"><table><thead><tr><th scope=\"col\">Priority</th><th scope=\"col\">Rule</th>"
        "<th scope=\"col\">Conditions</th><th scope=\"col\">Decision</th><th scope=\"col\">Quoted policy text</th>"
        f"</tr></thead><tbody>{rows}</tbody></table></div>\n</section>"
    )


def _limits(report: dict) -> str:
    items = "".join(f"<li>{_e(item)}</li>" for item in _list(_get(report, "verification", "not_established")))
    items = items or "<li class=\"missing\">not_established list not in report</li>"
    return (
        "<section aria-labelledby=\"limits\">\n<h2 id=\"limits\">What this does not establish</h2>\n"
        "<p>A confirmed discrepancy is specific to its point: two independent perspectives "
        "agree there and the target differs. It is not a claim that the proposed rules are "
        "right everywhere, and no level claims that the rules or the target are semantically "
        "correct.</p>\n"
        f"<ul>{items}</ul>\n</section>"
    )


def _alternatives(alternatives: tuple[Alternative, ...]) -> str:
    if not alternatives:
        return ""
    rows = []
    for alt in alternatives:
        report = alt.report if isinstance(alt.report, dict) else {}
        findings = [f for f in _list(report.get("findings")) if isinstance(f, dict)]
        codes = Counter(str(f.get("code")) for f in findings if f.get("code") != "CHECKED")
        summary = ", ".join(f"{count} × {code}" for code, count in sorted(codes.items())) or "only CHECKED"
        label = _e(alt.label)
        if alt.href and SAFE_LINK.fullmatch(alt.href):
            label = f"<a href=\"{_e(alt.href)}\">{label}</a>"
        rows.append(
            f"<tr><td>{label}</td><td>{_e(_get(report, 'reference', 'name') or 'none')}</td>"
            f"<td>{_e(_get(report, 'target', 'name') or 'none')}</td>"
            f"<td>{_e(_level(report))}</td><td>{_e(summary)}</td></tr>"
        )
    return (
        "<section aria-labelledby=\"alternatives\">\n<h2 id=\"alternatives\">Same proposal, other runs</h2>\n"
        "<p class=\"small\">Each row is a separate report generated from the same replayed proposal.</p>\n"
        "<div class=\"scroll\"><table><thead><tr><th scope=\"col\">Run</th><th scope=\"col\">Reference</th>"
        "<th scope=\"col\">Target</th><th scope=\"col\">Level</th><th scope=\"col\">Findings (excluding CHECKED)</th>"
        f"</tr></thead><tbody>{''.join(rows)}</tbody></table></div>\n</section>"
    )


def _footer(report: dict) -> str:
    return (
        "<footer><p class=\"small\">Rendered from a "
        f"{_e(report.get('tool'))} report (version {_e(report.get('report_version'))}). "
        "The viewer displays the report as written and recomputes nothing. "
        "Semantics: " + _e(report.get("semantics")) + "</p></footer>"
    )


_CSS = """
:root{--bg:#f7f7f5;--panel:#fff;--text:#1d1d1f;--muted:#5b5b63;--line:#dcdce0;
--red:#b42318;--red-bg:#fdecea;--amber:#8a5a00;--amber-bg:#fff4dc;--blue:#1d4ed8;
--blue-bg:#e8efff;--green:#166534;--green-bg:#e6f4ea;--grey-bg:#eeeef0;}
@media (prefers-color-scheme:dark){:root{--bg:#121214;--panel:#1c1c20;--text:#ececf1;
--muted:#a5a5b0;--line:#33333a;--red:#ff8a80;--red-bg:#3a1714;--amber:#ffcc66;
--amber-bg:#332508;--blue:#9db6ff;--blue-bg:#18213d;--green:#86e0a1;--green-bg:#123020;
--grey-bg:#2a2a30;}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);
font:16px/1.55 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
main{max-width:1040px;margin:0 auto;padding:24px 16px 64px}
header h1{font-size:clamp(1.4rem,3vw,2rem);line-height:1.2;margin:.2em 0 .6em}
.eyebrow{text-transform:uppercase;letter-spacing:.08em;font-size:.8rem;color:var(--muted);margin:0}
.meta{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:8px 24px;margin:0}
.meta dt{font-size:.8rem;color:var(--muted)}.meta dd{margin:0;overflow-wrap:anywhere}
section{background:var(--panel);border:1px solid var(--line);border-radius:12px;
padding:20px;margin-top:20px}
h2{margin-top:0;font-size:1.25rem}h3{font-size:1.05rem}h4{font-size:.95rem;margin-bottom:.4em}
.small{font-size:.85rem;color:var(--muted)}
code{font-family:ui-monospace,"Cascadia Code",Consolas,monospace;font-size:.9em;
background:var(--grey-bg);padding:1px 5px;border-radius:4px;overflow-wrap:anywhere}
.provenance{border-left:6px solid var(--line)}
.provenance-synthetic{border-left-color:var(--amber);background:var(--amber-bg)}
.provenance-live{border-left-color:var(--green)}
.provenance-saved{border-left-color:var(--blue)}
.provenance-unknown{border-left-color:var(--red)}
.badge,.finding-code{font-weight:700;font-family:ui-monospace,Consolas,monospace;font-size:.85rem;
background:var(--grey-bg);padding:2px 8px;border-radius:6px}
.result{display:grid;grid-template-columns:minmax(140px,180px) 1fr;gap:20px;align-items:start}
@media (max-width:640px){.result{grid-template-columns:1fr}}
.level{display:flex;flex-direction:column;align-items:center;justify-content:center;
border:2px solid var(--line);border-radius:12px;padding:16px;margin:0}
#verification-level{font-size:2.6rem;font-weight:800;line-height:1.1}
.criteria{list-style:none;padding:0;margin:.4em 0}.criteria li{margin:.3em 0}
.met{color:var(--green);font-weight:700}.not-met{color:var(--red);font-weight:700}
.missing{color:var(--muted);font-style:italic}
.finding{border:1px solid var(--line);border-left:6px solid var(--line);border-radius:10px;
padding:16px;margin-top:14px}
.severity-error{border-left-color:var(--red)}.severity-warning{border-left-color:var(--amber)}
.severity-info{border-left-color:var(--blue)}
.severity{font-size:.8rem;text-transform:uppercase;color:var(--muted);letter-spacing:.05em}
.summary{font-size:1.05rem;font-weight:600}
.perspectives{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:10px}
.perspectives>div{border:1px solid var(--line);border-radius:10px;padding:10px 12px}
.perspectives p{margin:0 0 4px}
.decision{display:inline-block;font-weight:700;padding:2px 10px;border-radius:999px;font-size:.9rem}
.decision-approve{color:var(--green);background:var(--green-bg)}
.decision-reject{color:var(--red);background:var(--red-bg)}
.decision-review{color:var(--blue);background:var(--blue-bg)}
.decision-none{color:var(--muted);background:var(--grey-bg)}
blockquote{margin:.4em 0;padding:8px 12px;border-left:4px solid var(--blue);
background:var(--blue-bg);border-radius:4px}
.chain{padding-left:1.2em}.chain>li{margin:.5em 0}
.findings{list-style:none;padding:0}.findings li{border-left:4px solid var(--line);
padding:6px 12px;margin:8px 0}
.callout{padding:10px 12px;background:var(--grey-bg);border-radius:8px}
.verdict{font-size:1.05rem;margin-top:0}
#verdict{font-weight:800;padding:2px 10px;border-radius:6px;background:var(--grey-bg)}
.verdict-ok #verdict{color:var(--green);background:var(--green-bg)}
.verdict-failed #verdict,.verdict-rejected #verdict,.verdict-error #verdict{color:var(--red);background:var(--red-bg)}
.verdict-inconclusive #verdict,.verdict-insufficient-evidence #verdict{color:var(--amber);background:var(--amber-bg)}
.failure{font-family:ui-monospace,Consolas,monospace;font-size:.8rem;color:var(--red)}
.range{padding:8px 12px;border-left:4px solid var(--amber);background:var(--amber-bg);border-radius:4px}
.scroll{overflow-x:auto}
table{border-collapse:collapse;width:100%;font-size:.9rem}
th,td{text-align:left;vertical-align:top;padding:6px 8px;border-bottom:1px solid var(--line)}
th{font-size:.8rem;color:var(--muted);font-weight:600}
a{color:var(--blue)}
footer{margin-top:24px}
"""


# -------------------------------------------------------------------- CLI


def load_report(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError) as exc:
        raise ViewerError(f"cannot read {path}: {exc}") from None
    except (ValueError, RecursionError):
        raise ViewerError(f"{path} is not valid JSON") from None


def write_page(page: str, output: Path, *, overwrite: bool) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w" if overwrite else "x", encoding="utf-8") as handle:
        handle.write(page)


def main(argv: list[str] | None = None) -> int:
    """Exit codes: 0 page written, 1 error."""
    parser = argparse.ArgumentParser(description="Render a PolicyProof JSON report as an HTML page.")
    parser.add_argument("report", type=Path, help="JSON report written by policyproof.verification")
    parser.add_argument("--output", type=Path, required=True, help="HTML file to write")
    parser.add_argument("--alternative", action="append", default=[], metavar="LABEL=REPORT.json",
                        help="summarise another report of the same proposal")
    parser.add_argument("--overwrite", action="store_true", help="allow replacing --output")
    args = parser.parse_args(argv)

    if args.output.exists() and not args.overwrite:
        return _fail(f"{args.output} already exists; pass --overwrite to replace it")
    try:
        alternatives = []
        for item in args.alternative:
            label, sep, path = item.partition("=")
            if not sep or not label or not path:
                raise ViewerError(f"--alternative must be LABEL=REPORT.json, got {item!r}")
            alternatives.append(Alternative(label, load_report(Path(path))))
        page = render_report(load_report(args.report), alternatives)
        write_page(page, args.output, overwrite=args.overwrite)
    except (ViewerError, OSError) as exc:
        return _fail(str(exc))
    print(f"Evidence page written to {args.output}")
    return 0


def _fail(message: str) -> int:
    print(f"error: {message}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
