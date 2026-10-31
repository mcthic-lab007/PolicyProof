"""End-to-end verification: Muse Spark proposes; PolicyProof verifies.

Four perspectives are recorded separately at every evaluated point:
  1. interpreted  - the proposed rules executed by PolicyProof's interpreter
  2. expected     - the proposal's declared expected decision (its test cases)
  3. reference    - an independent, human-written implementation, if given
  4. target       - the software under test, if given
Model expectations are never treated as ground truth. Findings say "the
proposed rules" rather than naming Muse: where a proposal came from (live,
saved, synthetic) is stated once, by its provenance label.

Evaluated points come from three sources, each recorded on the point:
boundary points derived from the rules' amount thresholds, dollar amounts
found in the policy text (so a threshold the rules omit is still probed),
and the proposal's own test cases. Only "$" amounts are recognised in the
policy text, and at most MAX_POLICY_THRESHOLDS (100) distinct amounts are
used; finding none does not show that no other threshold exists.

Findings (exact conditions):
  VALIDATION_REJECTED  the proposal failed schema validation or grounding.
                       verify() re-validates every document against the
                       supplied policy text, whatever its origin.
  UNSUPPORTED          the interpreter cannot run the document, derivation
                       exceeds its limit, a policy amount cannot be used as
                       a threshold, the reference fails at a point, the
                       target was not evaluated at a point (skipped, not
                       started, timed out or its worker died), or target-search
                       evaluations could not be judged (an error: L3 is not
                       claimed for a search that was partly not judged).
  COVERAGE_GAP         no rule decides a point (status NO_MATCH). Other
                       perspectives at such points are listed in its details
                       instead of producing further findings.
  PRECEDENCE_DEPENDENT a rule decides a point only because of its priority:
                       a lower-priority rule with a different decision also
                       matched. Grouped by deciding and overridden rules.
                       "info" when a rule records the assumption and no
                       reference contradicts it, otherwise "warning". It is
                       not a defect by itself.
  UNREACHABLE_RULE     a rule decides no evaluated point. Derived points
                       show every distinct behaviour of the rule document,
                       so it decides nothing anywhere in the domain.
  SELF_INCONSISTENT    at a decided point, a proposed test case expects another
                       decision, or names another deciding rule.
  REFERENCE_DISAGREEMENT  at a decided point, the reference decides
                       differently from the interpreted rules.
  TARGET_DISCREPANCY_CONFIRMED  the target differs from the reference, and
                       the interpreted rules agree with the reference.
  TARGET_DISCREPANCY_DISPUTED   the target differs from the reference, and
                       the interpreted rules do not agree with the reference.
  TARGET_DISCREPANCY_MODEL_ONLY no usable reference at the point; the target
                       differs from the interpreted rules. Not independent.
  CHECKED              every available perspective gave the same decision.
A target that raises or returns something other than a decision differs
from every decision.

Levels (each requires the previous one):
  L0  the rules passed schema validation and evidence grounding and the
      interpreter supports them.
  L1  the rules decide every evaluated point and agree with every model
      expectation; overlaps are reported, not counted against it.
  L2  a reference was given and the interpreted rules agree with it at
      every evaluated point.
  L3  a target was given and it agrees with the reference at every
      evaluated point.
L2 and L3 hold at the evaluated points inside the schema domain only. No
level states semantic correctness: the reference is one human reading of
the policy, and recorded assumptions remain assumptions.

Usage:
    python -m src.policyproof.verification POLICY.txt --replay RESPONSE.json
        [--reference democo-meal] [--target democo-buggy|democo-fixed]
        [--report OUT.json [--overwrite]]
    python -m src.policyproof.verification POLICY.txt --live [...]
"""

import argparse
import hashlib
import json
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal
from functools import partial
from pathlib import Path
from typing import Any

from src.policyproof.models import Decision, TestCase
from src.policyproof.muse_client import (
    FIXTURE_NOTE_KEY,
    RECORDING_KEY,
    SOURCE_LIVE,
    SOURCE_REPLAY,
    MuseClient,
    MuseClientError,
    MuseProposal,
    ProposalRejectedError,
    describe_provenance,
    replay_proposal,
)
from src.policyproof.rule_engine import (
    NUMERIC_DOMAINS,
    DerivationLimitError,
    Evaluation,
    PointSource,
    RuleEngine,
    UnsupportedRuleError,
    derive_boundary_points,
)
from src.policyproof.schema import (
    CENT,
    DECISIONS,
    ProposedTestCase,
    RuleDocument,
    RuleValidationError,
    find_dollar_amounts,
    validate_rule_payload,
)
from src.policyproof.target_worker import MAX_TIME_LIMIT, MAX_TIMEOUT, TargetWorker
from src.policyproof.target_search import (
    BISECTION_SHARE,
    DEFAULT_BUDGET,
    DEFAULT_SEED,
    MAX_BUDGET,
    Judgement,
    SearchOutcome,
    search as search_target,
)
from src.policyproof.constant_folding import FoldedConstants, fold_constants
from src.policyproof.source_literals import SourceAmounts, source_amounts


REPORT_VERSION = "1"
MAX_POLICY_THRESHOLDS = 100
# Isolated target execution (CLI default): per-call timeout and total limit, seconds.
DEFAULT_TARGET_TIMEOUT = 2.0
DEFAULT_TIME_LIMIT = 120.0
# Target outcomes that mean "not evaluated", as opposed to "evaluated and wrong":
# the call never finished, so it says nothing about the target's decision. A
# timeout cannot tell a hang from a correct but slow target, and a dead worker
# cannot tell a target bug from the environment. A call that finished by
# raising or returning a non-decision is the target's answer and stays judged.
NOT_EVALUATED = frozenset({"not_run", "worker_startup", "timeout", "worker_crash"})
LEVELS = ("L0", "L1", "L2", "L3")
# Findings that leave the verdict on the target unresolved without being
# errors: two perspectives conflict, or only the model contradicts the target.
INCONCLUSIVE_CODES = frozenset({
    "TARGET_DISCREPANCY_DISPUTED",
    "TARGET_DISCREPANCY_MODEL_ONLY",
    "REFERENCE_DISAGREEMENT",
})
# Exit codes, highest precedence first: 1 is the CLI's own operational
# error and never reaches a report; 2, 3 and 4 come from the findings.
EXIT_CODES = (
    (1, "ERROR", "the run could not be completed (unreadable file, missing API key, "
     "refused overwrite, invalid option); no verification result"),
    (2, "REJECTED", "the proposal failed schema and evidence validation; nothing was executed"),
    (3, "FAILED", "error findings: a confirmed target discrepancy, a defect in the proposal, "
     "or part of the verification that could not run"),
    (4, "INCONCLUSIVE", "no error findings, but the target's correctness is unresolved: a "
     "disputed or model-only discrepancy, or the reference and proposed rules disagree. "
     "This is not evidence that the target is wrong"),
    (5, "INSUFFICIENT_EVIDENCE", "no error and no unresolved finding, but the verification "
     "level is below the level required with --require-level (for example L1 without a "
     "reference when L3 is required)"),
    (0, "OK", "no error and no unresolved finding at the evaluated points; the verification "
     "level states how independent that evidence is"),
)
FINDING_ORDER = (
    "VALIDATION_REJECTED",
    "UNSUPPORTED",
    "COVERAGE_GAP",
    "PRECEDENCE_DEPENDENT",
    "UNREACHABLE_RULE",
    "SELF_INCONSISTENT",
    "REFERENCE_DISAGREEMENT",
    "TARGET_DISCREPANCY_CONFIRMED",
    "TARGET_DISCREPANCY_DISPUTED",
    "TARGET_DISCREPANCY_MODEL_ONLY",
    "CHECKED",
)
SEMANTICS = (
    "Rules are evaluated in ascending priority; a rule matches when all of its "
    "conditions hold; the first matching rule decides; no match means no decision."
)
PROVENANCE_NOTE = (
    "Provenance labels come from the call path or the saved response file. "
    "They are not cryptographic proof of origin. model_reported is whatever "
    "model name the response states."
)
LEVEL_MEANING = (
    "The highest level whose criteria, and those of every lower level, are met. "
    "Levels say how far the evidence chain reaches; they are not a quality grade, "
    "and none of them establishes semantic correctness of the rules or the target."
)
NOT_ESTABLISHED = (
    "that the rules interpret the policy as its author intended (semantic correctness)",
    "that the reference matches the policy author's intent; it is one human reading",
    "behaviour of the reference or target at inputs between the evaluated points",
    "thresholds the policy expresses other than as \"$\" amounts",
    "the origin of the proposal beyond its self-reported provenance label",
)


@dataclass(frozen=True)
class Implementation:
    """A trusted, locally selected decision function and how to name it."""

    name: str
    description: str
    decide: Callable[[TestCase], Any]
    # "package.module:function" for running the target in a worker process
    # (target_worker). Without it the target can only run in-process.
    import_path: str | None = None


@dataclass(frozen=True)
class Outcome:
    decision: Decision | None
    error: str | None = None
    # None for a decision; otherwise exception, invalid_output, timeout,
    # worker_crash, worker_startup or not_run (see target_worker).
    failure: str | None = None


@dataclass(frozen=True)
class PointResult:
    id: str
    amount: Decimal
    has_service_date: bool
    sources: tuple[dict[str, Any], ...]
    evaluation: Evaluation
    expectations: tuple[ProposedTestCase, ...]
    reference: Outcome | None
    target: Outcome | None


@dataclass(frozen=True)
class Finding:
    code: str
    severity: str
    summary: str
    points: tuple[str, ...] = ()
    rules: tuple[str, ...] = ()
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class VerificationResult:
    level: str
    findings: tuple[Finding, ...]
    points: tuple[PointResult, ...]
    report: dict[str, Any]
    search: SearchOutcome | None = None

    def codes(self) -> list[str]:
        return [finding.code for finding in self.findings]

    def to_json(self) -> str:
        return json.dumps(self.report, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def verify(
    document: RuleDocument,
    policy_text: str,
    *,
    proposal: MuseProposal | None = None,
    reference: Implementation | None = None,
    target: Implementation | None = None,
    search_budget: int = DEFAULT_BUDGET,
    search_seed: int = DEFAULT_SEED,
    target_timeout: float | None = None,
    target_time_limit: float = DEFAULT_TIME_LIMIT,
    required_level: str | None = None,
    source_probes: bool = True,
    proposed_probes: tuple[Decimal, ...] = (),
    proposed_probes_origin: str | None = None,
    constant_probes: bool = False,
) -> VerificationResult:
    """Verify a rule document against ``policy_text``. The document is
    re-validated against this policy text first, so L0 never rests on where
    the document came from. When a target is given, it is also searched
    between the evaluated points (see target_search) within
    ``search_budget`` target calls; 0 disables the search. With
    ``source_probes``, amounts written in the target's own source are probed
    first (see source_literals); they are probes, never evidence by
    themselves. With ``constant_probes``, constant expressions in the
    target's source are also folded to amounts and probed (see
    constant_folding); the source is parsed, never executed. Problems in the
    model's output become findings; this raises only for invalid arguments."""
    if not isinstance(policy_text, str) or not policy_text.strip():
        raise ValueError("policy_text must be a non-empty string")
    if isinstance(search_budget, bool) or not isinstance(search_budget, int) \
            or not 0 <= search_budget <= MAX_BUDGET:
        raise ValueError(f"search_budget must be an integer from 0 to {MAX_BUDGET}")
    if isinstance(search_seed, bool) or not isinstance(search_seed, int):
        raise ValueError("search_seed must be an integer")
    if required_level is not None and required_level not in LEVELS:
        raise ValueError(f"required_level must be one of {', '.join(LEVELS)}")
    worker = None
    if target is not None and target_timeout is not None:
        if not target.import_path:
            raise ValueError("target_timeout needs a target with an import_path "
                             "('package.module:function') so it can run in a worker process")
        worker = TargetWorker(target.import_path, timeout=target_timeout, time_limit=target_time_limit)
    header = _header(policy_text, document, proposal, reference, target)

    try:
        RuleEngine(document)
    except UnsupportedRuleError as exc:
        return _stopped(header, Finding(
            "UNSUPPORTED", "error",
            "The rule document uses constructs the interpreter does not support.",
            details={"problems": list(exc.problems)},
        ))
    try:
        document = _revalidate(document, policy_text)
    except RuleValidationError as exc:
        return _stopped(header, _rejected_finding(exc.issues))
    engine = RuleEngine(document)

    thresholds, findings = _policy_thresholds(policy_text)
    extra = [
        (value, "policy text " + ", ".join(f"${value} at [{s}, {e})" for s, e in spans))
        for value, spans in thresholds
    ]
    try:
        derivation = derive_boundary_points(document, extra)
    except DerivationLimitError as exc:
        return _stopped(header, Finding("UNSUPPORTED", "error", str(exc)))

    if target is None:
        run_target = None
    elif worker is not None:
        run_target = partial(_run_isolated, worker)
    else:
        run_target = partial(_run, target)

    outcome: SearchOutcome | None = None
    hints: SourceAmounts | None = None
    folded: FoldedConstants | None = None
    proposed: tuple[Decimal, ...] = ()
    search_points: list[PointResult] = []
    try:
        results = tuple(
            _evaluate_point(engine, point_id, amount, dated, sources, cases, reference, run_target)
            for (amount, dated), (point_id, sources, cases) in _collect_points(derivation, document)
        )
        findings += _findings(document, results, reference, target)
        if run_target is not None and search_budget > 0:
            low, high = NUMERIC_DOMAINS["amount"]
            if source_probes:
                hints = source_amounts(target.decide, low, high)
            if constant_probes:
                folded = fold_constants(target.decide, low, high)
            proposed = tuple(sorted({a for a in proposed_probes if low <= a <= high}))
            outcome = _search(engine, results, reference, run_target, search_budget, search_seed,
                              tuple(sorted(set(hints.amounts if hints else ())
                                           | set(folded.amounts if folded else ()) | set(proposed))))
            range_findings, search_points = _range_findings(outcome, results, document, reference)
            findings += range_findings
            if outcome.unjudged:
                findings.append(_unjudged_finding(outcome))
    finally:
        if worker is not None:
            worker.close()  # also on KeyboardInterrupt: never leave a worker behind

    findings.sort(key=lambda f: (FINDING_ORDER.index(f.code), f.points, f.rules, f.summary))
    level, criteria = _level(results, findings, reference, target, outcome)

    report = dict(header)
    report.update(
        verification=_verification_section(level, criteria, len(results), outcome),
        rules=[_rule_record(rule) for rule in sorted(document.rules, key=lambda r: r.priority)],
        policy_thresholds=[
            {"amount": str(value), "spans": [list(span) for span in spans]}
            for value, spans in thresholds
        ],
        excluded_points=list(derivation.excluded),
        points=[_point_record(result) for result in (*results, *search_points)],
        findings=[_finding_record(finding) for finding in findings],
        target_search=_search_section(outcome, target, search_budget, reference, hints,
                                      proposed, proposed_probes_origin, folded),
        target_execution=_execution_section(target, worker),
    )
    report["verification"]["result"] = verdict(findings, level, required_level)
    return VerificationResult(level, tuple(findings), results, report, outcome)


def verdict(findings, level: str = "NONE", required_level: str | None = None) -> dict[str, Any]:
    """The run's overall result and CLI exit code, derived from the findings
    and, only when a minimum level is required, the level reached.
    Precedence: REJECTED (2) > FAILED (3) > INCONCLUSIVE (4) >
    INSUFFICIENT_EVIDENCE (5) > OK (0). A required level can only turn an
    otherwise OK result into 5; it never changes any other result."""
    codes = {f.code for f in findings}
    if "VALIDATION_REJECTED" in codes:
        exit_code = 2
    elif any(f.severity == "error" for f in findings):
        exit_code = 3
    elif codes & INCONCLUSIVE_CODES:
        exit_code = 4
    elif required_level is not None and _rank(level) < _rank(required_level):
        exit_code = 5
    else:
        exit_code = 0
    label, meaning = next((label, meaning) for code, label, meaning in EXIT_CODES if code == exit_code)
    result = {"exit_code": exit_code, "label": label, "meaning": meaning}
    if required_level is not None:
        result.update(required_level=required_level, level_reached=level)
    return result


def _rank(level: str) -> int:
    return LEVELS.index(level) if level in LEVELS else -1


def rejection_result(error: ProposalRejectedError, policy_text: str) -> VerificationResult:
    """A report for a proposal that failed validation: nothing was executed."""
    header = _header(policy_text, None, None, None, None)
    header["proposal"] = _proposal_section(error.source, error.response_body)
    return _stopped(header, _rejected_finding(error.issues))


def _rejected_finding(issues) -> Finding:
    return Finding(
        "VALIDATION_REJECTED", "error",
        "The proposal failed PolicyProof's schema and evidence validation; no rule was executed.",
        details={"issues": [{"path": i.path, "message": i.message} for i in issues]},
    )


def _revalidate(document: RuleDocument, policy_text: str) -> RuleDocument:
    """Run the document back through the schema validator with this policy
    text: evidence and thresholds are re-grounded and spans recomputed."""
    def case_payload(case: Any) -> Any:
        if not isinstance(case, ProposedTestCase):
            return case
        payload = {
            "id": case.id,
            "inputs": {"amount": case.amount, "has_service_date": case.has_service_date},
            "expected_decision": case.expected_decision,
        }
        if case.rule_id is not None:
            payload["rule_id"] = case.rule_id
        if case.rationale is not None:
            payload["rationale"] = case.rationale
        return payload

    payload = {
        "schema_version": document.schema_version,
        "policy_id": document.policy_id,
        "rules": [
            {
                "id": rule.id,
                "description": rule.description,
                "priority": rule.priority,
                "conditions": [
                    {"field": c.field, "operator": c.operator, "value": c.value}
                    for c in rule.conditions
                ],
                "decision": rule.decision,
                "evidence": rule.evidence,
            }
            for rule in document.rules
        ],
        "test_cases": [case_payload(case) for case in document.test_cases],
    }
    return validate_rule_payload(payload, policy_text)


def provenance_label(source: str, body: dict[str, Any]) -> str:
    if source == SOURCE_LIVE:
        return "LIVE"
    if source == SOURCE_REPLAY:
        if isinstance(body.get(FIXTURE_NOTE_KEY), str):
            return "REPLAY_SYNTHETIC"
        if isinstance(body.get(RECORDING_KEY), dict):
            return "REPLAY_SAVED_LIVE_RESPONSE"
        return "REPLAY_UNKNOWN_ORIGIN"
    return "UNKNOWN"


def _header(policy_text, document, proposal, reference, target) -> dict[str, Any]:
    return {
        "report_version": REPORT_VERSION,
        "tool": "PolicyProof",
        "policy": {
            "policy_id": document.policy_id if isinstance(document, RuleDocument) else None,
            "sha256": hashlib.sha256(policy_text.encode("utf-8")).hexdigest(),
            "characters": len(policy_text),
        },
        "proposal": (
            _proposal_section(proposal.source, proposal.response_body)
            if proposal is not None
            else {"provenance_label": "UNKNOWN", "provenance": "no proposal metadata supplied",
                  "response_id": None, "model_reported": None, "note": PROVENANCE_NOTE}
        ),
        "reference": _implementation_record(reference),
        "target": _implementation_record(target),
        "semantics": SEMANTICS,
        "domain": {
            "amount": [str(bound) for bound in NUMERIC_DOMAINS["amount"]],
            "amount_note": "whole cents; the schema's representable range, not a policy limit",
            "has_service_date": [False, True],
        },
    }


def _proposal_section(source: str, body: dict[str, Any]) -> dict[str, Any]:
    return {
        "provenance_label": provenance_label(source, body),
        "provenance": describe_provenance(source, body),
        "response_id": body.get("id") if isinstance(body.get("id"), str) else None,
        "model_reported": body.get("model") if isinstance(body.get("model"), str) else None,
        "note": PROVENANCE_NOTE,
    }


def _implementation_record(implementation: Implementation | None) -> dict[str, str] | None:
    if implementation is None:
        return None
    return {"name": implementation.name, "description": implementation.description}


def _stopped(header: dict[str, Any], finding: Finding) -> VerificationResult:
    report = dict(header)
    report.update(
        verification={
            "level": "NONE",
            "level_meaning": LEVEL_MEANING,
            "criteria": {level: {"met": False, "detail": "verification stopped"} for level in LEVELS},
            "scope": "Verification stopped before any rule was executed.",
            "not_established": list(NOT_ESTABLISHED),
        },
        rules=[], policy_thresholds=[], excluded_points=[], points=[],
        findings=[_finding_record(finding)],
        target_search={"performed": False, "reason": "verification stopped"},
    )
    report["verification"]["result"] = verdict((finding,))
    return VerificationResult("NONE", (finding,), (), report)


def _policy_thresholds(policy_text: str):
    low, high = NUMERIC_DOMAINS["amount"]
    spans_by_value: dict[Decimal, list[tuple[int, int]]] = {}
    findings: list[Finding] = []
    for value, span in find_dollar_amounts(policy_text):
        if not (value.is_finite() and low <= value <= high and value == value.quantize(CENT)):
            findings.append(Finding(
                "UNSUPPORTED", "info",
                f"Policy amount ${value} at [{span[0]}, {span[1]}) is not a whole-cent amount "
                "inside the schema domain and was not used as a threshold.",
                details={"amount": str(value), "span": list(span)},
            ))
            continue
        canonical = value.quantize(CENT)
        spans_by_value.setdefault(canonical, []).append(span)

    values = sorted(spans_by_value)
    if len(values) > MAX_POLICY_THRESHOLDS:
        findings.append(Finding(
            "UNSUPPORTED", "warning",
            f"The policy text states {len(values)} distinct amounts; only the lowest "
            f"{MAX_POLICY_THRESHOLDS} were used as thresholds.",
            details={"ignored": [str(v) for v in values[MAX_POLICY_THRESHOLDS:]]},
        ))
        values = values[:MAX_POLICY_THRESHOLDS]
    return [(value, tuple(spans_by_value[value])) for value in values], findings


def _source_record(source: PointSource) -> dict[str, Any]:
    if source.kind == "threshold":
        return {
            "kind": "rule_threshold",
            "rule_id": source.rule_id,
            "condition_index": source.condition_index,
            "threshold": str(source.threshold),
            "offset": str(source.offset),
        }
    if source.kind == "extra":
        return {
            "kind": "policy_text_amount",
            "label": source.label,
            "threshold": str(source.threshold),
            "offset": str(source.offset),
        }
    return {"kind": "domain_bound", "label": source.label}


def _collect_points(derivation, document: RuleDocument):
    table: dict[tuple[Decimal, bool], tuple[list, list]] = {}
    for point in derivation.points:
        sources, _ = table.setdefault((point.amount, point.has_service_date), ([], []))
        sources.extend(_source_record(source) for source in point.amount_sources)
    for case in document.test_cases:
        sources, cases = table.setdefault((case.amount, case.has_service_date), ([], []))
        sources.append({"kind": "model_test_case", "case_id": case.id})
        cases.append(case)
    for (amount, dated), (sources, cases) in sorted(table.items()):
        point_id = f"point-{amount}-{'dated' if dated else 'undated'}"
        yield (amount, dated), (point_id, tuple(sources), tuple(cases))


def _run(implementation: Implementation, case: TestCase) -> Outcome:
    try:
        value = implementation.decide(case)
    # The implementation is under test: record failures, never crash. SystemExit
    # is caught too (a target calling sys.exit() must not end the run);
    # KeyboardInterrupt still stops it.
    except (Exception, SystemExit) as exc:
        return Outcome(None, f"raised {type(exc).__name__}: {str(exc)[:200]}", "exception")
    if not isinstance(value, str) or value not in DECISIONS:
        return Outcome(None, f"returned {repr(value)[:80]}, which is not a decision", "invalid_output")
    return Outcome(value)


def _run_isolated(worker: TargetWorker, case: TestCase) -> Outcome:
    decision, error, failure = worker.call(case.amount, case.has_service_date, case.description)
    if failure is not None:
        return Outcome(None, error, failure)
    if decision not in DECISIONS:
        return Outcome(None, f"returned {repr(decision)[:80]}, which is not a decision", "invalid_output")
    return Outcome(decision)


def _evaluate_point(engine, point_id, amount, dated, sources, cases, reference, run_target):
    evaluation = engine.evaluate({"amount": amount, "has_service_date": dated})
    case = TestCase(amount, dated, point_id)
    return PointResult(
        point_id, amount, dated, sources, evaluation, cases,
        _run(reference, case) if reference else None,
        run_target(case) if run_target else None,
    )


def _agrees(evaluation: Evaluation, reference: Outcome | None, target: Outcome) -> bool | None:
    """Whether the target matches the comparison basis: the reference when
    one is given, otherwise the executed proposed rules. None: no basis, or
    the target was not evaluated at all."""
    if target.failure in NOT_EVALUATED:
        return None
    if reference is not None:
        return None if reference.decision is None else target.decision == reference.decision
    if evaluation.status != "DECIDED":
        return None
    return target.decision == evaluation.decision


def _search(engine, results, reference, run_target, budget, seed, hints=()) -> SearchOutcome:
    low, high = NUMERIC_DOMAINS["amount"]
    known = {
        (r.amount, r.has_service_date): Judgement(
            _agrees(r.evaluation, r.reference, r.target), (r.evaluation, r.reference, r.target)
        )
        for r in results
    }

    def judge(amount: Decimal, dated: bool) -> Judgement:
        case = TestCase(amount, dated, _search_point_id(amount, dated))
        evaluation = engine.evaluate({"amount": amount, "has_service_date": dated})
        ref = _run(reference, case) if reference else None
        tgt = run_target(case)
        return Judgement(_agrees(evaluation, ref, tgt), (evaluation, ref, tgt))

    return search_target(judge, known, low=low, high=high, seed=seed, budget=budget, hints=hints)


def _search_point_id(amount: Decimal, dated: bool) -> str:
    return f"search-{amount}-{'dated' if dated else 'undated'}"


def _range_findings(outcome: SearchOutcome, results, document, reference):
    """One finding per discrepancy range, with the existing codes and the
    existing rule for confirmation, applied to every disagreeing amount."""
    rules = {rule.id: rule for rule in document.rules}
    base = {(r.amount, r.has_service_date): r for r in results}
    points: dict[str, PointResult] = {}
    findings = []

    def point(amount: Decimal, dated: bool, role: str) -> str:
        if (amount, dated) in base:
            return base[(amount, dated)].id
        point_id = _search_point_id(amount, dated)
        evaluation, ref, tgt = outcome.observations[(amount, dated)].payload
        source = {"kind": "target_search", "role": role, "seed": outcome.seed}
        existing = points.get(point_id)
        sources = (*existing.sources, source) if existing else (source,)
        points[point_id] = PointResult(point_id, amount, dated, sources, evaluation, (), ref, tgt)
        return point_id

    for found in outcome.ranges:
        dated = found.has_service_date
        payloads = [outcome.observations[(a, dated)].payload for a in found.disagreeing]
        reasons: list[str] = []
        if reference is not None:
            for amount, (ev, ref, _) in zip(found.disagreeing, payloads):
                expectations = base[(amount, dated)].expectations if (amount, dated) in base else ()
                for reason in _dispute_reasons(ev, ref.decision, expectations):
                    if reason not in reasons:
                        reasons.append(reason)
        if reference is None:
            code, severity = "TARGET_DISCREPANCY_MODEL_ONLY", "warning"
        elif not reasons:
            code, severity = "TARGET_DISCREPANCY_CONFIRMED", "error"
        else:
            code, severity = "TARGET_DISCREPANCY_DISPUTED", "warning"

        lower, upper = found.lower, found.upper
        ids = []
        if lower.outside is not None:
            ids.append(point(lower.outside, dated, "agreeing amount below the range"))
        ids.append(point(lower.inside, dated, "lowest disagreeing amount of the range"))
        if upper.inside != lower.inside:
            ids.append(point(upper.inside, dated, "highest disagreeing amount of the range"))
        if upper.outside is not None:
            ids.append(point(upper.outside, dated, "agreeing amount above the range"))

        evaluation, ref, tgt = outcome.observations[(lower.inside, dated)].payload
        summary = _range_summary(found, code, evaluation, ref, tgt, rules)
        findings.append(Finding(
            code, severity, summary,
            points=tuple(ids),
            rules=(evaluation.decided_by,) if evaluation.decided_by else (),
            details={
                "kind": "range",
                "has_service_date": dated,
                "start": str(lower.inside),
                "end": str(upper.inside),
                "agrees_below": None if lower.outside is None else str(lower.outside),
                "agrees_above": None if upper.outside is None else str(upper.outside),
                "lower_edge_verified": lower.verified,
                "upper_edge_verified": upper.verified,
                "disagreeing_amounts_evaluated": len(found.disagreeing),
                "found_by_search": found.found_by_search,
                "disputed_because": reasons,
                "at_start": {"target": tgt.decision, "target_error": tgt.error,
                             "reference": None if ref is None else ref.decision,
                             "interpreted": evaluation.decision},
            },
        ))
    return findings, list(points.values())


def _unjudged_finding(outcome: SearchOutcome) -> Finding:
    """Search calls that produced no judgement: the target was not run (time
    limit, worker start), the reference gave no decision, or there was no
    decided basis. Without this, agreement would be claimed for them."""
    reasons: dict[str, int] = {}
    for key in outcome.unjudged_inputs:
        _, ref, tgt = outcome.observations[key].payload
        if tgt.failure in NOT_EVALUATED:
            reason = f"target {tgt.failure}"
        elif ref is not None and ref.decision is None:
            reason = "reference produced no decision"
        else:
            reason = "no decided comparison basis"
        reasons[reason] = reasons.get(reason, 0) + 1
    first = outcome.unjudged_inputs[0]
    return Finding(
        "UNSUPPORTED", "error",
        f"Target search: {outcome.unjudged} of {outcome.calls} search evaluations could not be "
        "judged (" + ", ".join(f"{n} {reason}" for reason, n in sorted(reasons.items()))
        + "). Nothing is concluded about the target at those amounts, so agreement is not "
        "claimed for the search.",
        details={
            "unjudged": outcome.unjudged,
            "search_evaluations": outcome.calls,
            "reasons": reasons,
            "first_unjudged": {"amount": str(first[0]), "has_service_date": first[1]},
        },
    )


def _range_summary(found, code, evaluation, ref, tgt, rules) -> str:
    lower, upper = found.lower, found.upper
    where = "with" if found.has_service_date else "without"
    basis = "the reference" if ref is not None else "the executed proposed rules"
    text = (
        f"Target search: the target disagrees with {basis} at every one of "
        f"{len(found.disagreeing)} evaluated amounts from ${lower.inside} to ${upper.inside} "
        f"{where} a service date."
    )
    for edge, side in ((lower, "lower"), (upper, "upper")):
        if edge.outside is None:
            text += (f" The range reaches the {side} end of the domain."
                     if edge.verified else f" The {side} edge could not be located.")
        elif edge.verified:
            text += f" The {side} edge is verified: it agrees at ${edge.outside} and disagrees at ${edge.inside}."
        else:
            text += (f" The {side} edge was not located to the cent: it lies between "
                     f"${min(edge.outside, edge.inside)} and ${max(edge.outside, edge.inside)}.")
    got = tgt.decision or f"no decision ({tgt.error})"
    if code == "TARGET_DISCREPANCY_CONFIRMED":
        rule = rules.get(evaluation.decided_by)
        text += (f" At ${lower.inside} the target decides {got}; the independent reference and the "
                 f"executed proposed rules both decide {ref.decision}")
        text += f" (rule {rule.id}, citing \"{rule.evidence}\")." if rule else "."
    elif code == "TARGET_DISCREPANCY_DISPUTED":
        text += (" Not confirmed at every disagreeing amount: the proposed rules or the "
                 "proposal's own expected decisions do not agree with the reference there.")
    else:
        text += " No independent reference was given, so this is not confirmed."
    return text + " Amounts between evaluated points were sampled, not all checked."


def _execution_section(target, worker: TargetWorker | None) -> dict[str, Any]:
    if target is None:
        return {"mode": "none", "reason": "no target supplied"}
    if worker is None:
        return {
            "mode": "in-process",
            "note": "The target ran inside the verifier with no timeout: a target that never "
                    "returns would hang the run.",
        }
    return {
        "mode": "isolated-worker-process",
        "import_path": worker.spec,
        "timeout_seconds": worker.timeout,
        "time_limit_seconds": worker.time_limit,
        "calls": worker.stats["calls"],
        "worker_starts": worker.stats["starts"],
        "timeouts": worker.stats["timeouts"],
        "worker_crashes": worker.stats["crashes"],
        "not_run": worker.stats["not_run"],
        "note": "Each call ran in a separate worker process and was abandoned, with the worker "
                "killed, if it did not answer within the timeout. This is process isolation "
                "with a timeout, not a security sandbox: the worker has the user's permissions.",
    }


def _search_section(outcome: SearchOutcome | None, target, budget, reference,
                    hints: SourceAmounts | None = None, proposed: tuple[Decimal, ...] = (),
                    proposed_origin: str | None = None,
                    folded: FoldedConstants | None = None) -> dict[str, Any]:
    if outcome is None:
        reason = "no target supplied" if target is None else "search budget is 0"
        return {"performed": False, "reason": reason}
    return {
        "performed": True,
        "seed": outcome.seed,
        "budget": outcome.budget,
        "target_calls": outcome.calls,
        "reference_calls": outcome.calls if reference is not None else 0,
        "probe_calls": outcome.probe_calls,
        "bisection_calls": outcome.bisection_calls,
        "budget_exhausted": outcome.budget_exhausted,
        "unjudged_evaluations": outcome.unjudged,
        "ranges_found": len(outcome.ranges),
        "source_amounts": {"used": False, "reason": "disabled"} if hints is None else {
            "used": True,
            "read_from": hints.source,
            "unavailable": hints.unavailable,
            "amounts": [str(a) for a in hints.amounts],
            "note": "Amounts written in the target's own source, probed with one cent either "
                    "side before the ladder. The source was parsed, never executed; a probe is "
                    "evidence only through the decisions actually observed there.",
        },
        "proposed_amounts": {
            "origin": proposed_origin or "unspecified",
            "amounts": [str(a) for a in proposed],
            "note": "Amounts proposed outside PolicyProof (for example by a model), probed with "
                    "one cent either side like source amounts. A proposal is a place to look, "
                    "not a finding: only the decisions observed there count.",
        } if proposed else {"used": False},
        **({} if folded is None else {"constant_amounts": {
            "read_from": folded.source,
            "unavailable": folded.unavailable,
            "amounts": [str(a) for a in folded.amounts],
            "derivations": {k: list(v) for k, v in folded.derivations.items()},
            "unsupported": list(folded.unsupported),
            "note": "Constant expressions in the target's source folded to amounts by a bounded "
                    "evaluator over the syntax tree (the source was parsed, never executed), "
                    "probed with one cent either side. Unsupported expressions are listed, not "
                    "guessed. A probe is evidence only through the decisions observed there.",
        }}),
        "strategy": (
            "For each value of has_service_date: amounts written in the target's source and "
            "one cent either side (when enabled), then a round-number ladder (1, 2, 2.5 and 5 x 10^k "
            "dollars and one cent either side), then seeded samples spread over power-of-ten "
            "bands between neighbouring evaluated amounts, then bisection to one cent at the "
            f"edges of every range. 1/{BISECTION_SHARE} of the budget is reserved for bisection."
        ),
        "comparison_basis": "independent reference" if reference is not None
        else "executed proposed rules (no reference)",
        "limitations": [
            "Sampling, not exhaustive checking: faults at a few isolated amounts can be missed.",
            "Inside a reported range only the listed evaluated amounts were checked; the range "
            "may contain agreeing amounts that were never sampled.",
            "Edges marked verified were evaluated on both sides; any other edge is given as an "
            "interval.",
            "How target calls were run (in-process, or a worker process with a per-call "
            "timeout) is stated under target_execution; neither is a security sandbox.",
        ],
    }


def _findings(document, results, reference, target) -> list[Finding]:
    rules = {rule.id: rule for rule in document.rules}
    findings: list[Finding] = []

    gaps = [r for r in results if r.evaluation.status == "NO_MATCH"]
    if gaps:
        findings.append(Finding(
            "COVERAGE_GAP", "error",
            f"No rule decides {len(gaps)} evaluated point(s); the rules are incomplete there.",
            points=tuple(r.id for r in gaps),
            details={"other_perspectives": {r.id: _perspectives(r) for r in gaps}},
        ))

    groups: dict[tuple[str, tuple[str, ...]], list[PointResult]] = {}
    for r in results:
        ev = r.evaluation
        if ev.status == "DECIDED" and ev.has_conflicting_matches:
            overridden = tuple(
                t.rule_id for t in ev.rule_traces
                if t.matched and not t.decided and t.decision != ev.decision
            )
            groups.setdefault((ev.decided_by, overridden), []).append(r)
    for (decider, overridden), group in sorted(groups.items()):
        involved = (decider, *overridden)
        assumptions = [rules[i].description for i in involved if "assumption" in rules[i].description.lower()]
        reference_agrees = None
        if reference is not None:
            reference_agrees = all(
                r.reference is not None and r.reference.decision == r.evaluation.decision
                for r in group
            )
        documented = bool(assumptions)
        summary = (
            f"{decider} ({rules[decider].decision}) overrides "
            + ", ".join(f"{o} ({rules[o].decision})" for o in overridden)
            + f" at {len(group)} point(s) only because of its higher priority. First-match "
            "priority resolves this under the declared contract; the policy text does not "
            "itself state the order. "
            + ("A rule records this as an assumption." if documented
               else "No rule records this as an assumption.")
        )
        if reference_agrees is False:
            summary += " The reference disagrees with the priority-based result."
        findings.append(Finding(
            "PRECEDENCE_DEPENDENT",
            "info" if documented and reference_agrees is not False else "warning",
            summary,
            points=tuple(r.id for r in group),
            rules=involved,
            details={
                "deciding_rule": decider,
                "overridden_rules": [{"rule_id": o, "decision": rules[o].decision} for o in overridden],
                "assumption_documented": documented,
                "assumption_text": assumptions,
                "reference_agrees_with_priority_result": reference_agrees,
            },
        ))

    deciders = {r.evaluation.decided_by for r in results}
    matchers = {rule_id for r in results for rule_id in r.evaluation.matching_rule_ids}
    for rule in sorted(document.rules, key=lambda rule: rule.priority):
        if rule.id not in deciders:
            how = ("it matches but higher-priority rules always decide first"
                   if rule.id in matchers else "its conditions never all hold")
            findings.append(Finding(
                "UNREACHABLE_RULE", "warning",
                f"Rule {rule.id} decides no evaluated point: {how}. The derived points show "
                "every distinct behaviour of the rule document, so it never decides anywhere "
                "in the domain.",
                rules=(rule.id,),
                details={"matches_somewhere": rule.id in matchers},
            ))

    for r in results:
        ev = r.evaluation
        if ev.status != "DECIDED":
            continue
        for case in r.expectations:
            if case.expected_decision != ev.decision:
                findings.append(Finding(
                    "SELF_INCONSISTENT", "error",
                    f"The proposal's test case {case.id} expects {case.expected_decision}, but its own "
                    f"rules decide {ev.decision} (rule {ev.decided_by}).",
                    points=(r.id,), rules=(ev.decided_by,),
                    details={"kind": "expected_decision", "case_id": case.id},
                ))
            elif case.rule_id is not None and case.rule_id != ev.decided_by:
                findings.append(Finding(
                    "SELF_INCONSISTENT", "warning",
                    f"The proposal's test case {case.id} names rule {case.rule_id}, but rule "
                    f"{ev.decided_by} decides it.",
                    points=(r.id,), rules=(ev.decided_by, case.rule_id),
                    details={"kind": "rule_attribution", "case_id": case.id},
                ))

    reference_failures = [r for r in results if r.reference is not None and r.reference.decision is None]
    if reference_failures:
        findings.append(Finding(
            "UNSUPPORTED", "error",
            f"The reference produced no decision at {len(reference_failures)} point(s).",
            points=tuple(r.id for r in reference_failures),
            details={"errors": {r.id: r.reference.error for r in reference_failures}},
        ))

    not_evaluated = [r for r in results if r.target is not None and r.target.failure in NOT_EVALUATED]
    if not_evaluated:
        failures: dict[str, int] = {}
        for r in not_evaluated:
            failures[r.target.failure] = failures.get(r.target.failure, 0) + 1
        findings.append(Finding(
            "UNSUPPORTED", "error",
            f"The target was not evaluated at {len(not_evaluated)} point(s) ("
            + ", ".join(f"{n} {kind}" for kind, n in sorted(failures.items()))
            + f"): {not_evaluated[0].target.error}. A call that did not finish is not evidence "
            "of a wrong decision, so nothing is concluded about the target there.",
            points=tuple(r.id for r in not_evaluated),
            details={"errors": {r.id: r.target.error for r in not_evaluated}, "failures": failures},
        ))

    for r in results:
        ev = r.evaluation
        ref = r.reference.decision if r.reference is not None else None
        if ref is not None and ev.status == "DECIDED" and ev.decision != ref:
            findings.append(Finding(
                "REFERENCE_DISAGREEMENT", "warning",
                f"The reference decides {ref}, but the proposed rules decide {ev.decision} "
                f"(rule {ev.decided_by}). Two interpretations conflict; a person must decide.",
                points=(r.id,), rules=(ev.decided_by,),
                details={"reference": ref, "interpreted": ev.decision},
            ))
        if r.target is None or r.target.failure in NOT_EVALUATED:
            continue
        tgt = r.target.decision
        if ref is not None:
            if tgt == ref:
                continue
            reasons = _dispute_reasons(ev, ref, r.expectations)
            confirmed = not reasons
            code = "TARGET_DISCREPANCY_CONFIRMED" if confirmed else "TARGET_DISCREPANCY_DISPUTED"
            summary = _target_summary(r, rules, ref, reasons)
            findings.append(Finding(
                code, "error" if confirmed else "warning", summary,
                points=(r.id,), rules=(ev.decided_by,) if ev.decided_by else (),
                details={"target": tgt, "target_error": r.target.error, "target_failure": r.target.failure,
                         "reference": ref, "interpreted": ev.decision,
                         "model_expectations": [c.expected_decision for c in r.expectations],
                         "disputed_because": reasons},
            ))
        elif ev.status == "DECIDED" and tgt != ev.decision:
            findings.append(Finding(
                "TARGET_DISCREPANCY_MODEL_ONLY", "warning",
                f"The target decides {tgt or 'nothing'}, but the proposed rules decide {ev.decision}. "
                "No independent reference is available here, so this is not confirmed.",
                points=(r.id,), rules=(ev.decided_by,),
                details={"target": tgt, "target_error": r.target.error, "interpreted": ev.decision},
            ))

    checked = [r for r in results if _all_agree(r)]
    if checked:
        available = ["interpreted"] + [
            name for name, present in (("expected", any(r.expectations for r in checked)),
                                       ("reference", reference is not None),
                                       ("target", target is not None)) if present
        ]
        findings.append(Finding(
            "CHECKED", "info",
            f"All available perspectives agree at {len(checked)} of {len(results)} point(s).",
            points=tuple(r.id for r in checked),
            details={"perspectives": available},
        ))
    return findings


def _dispute_reasons(evaluation: Evaluation, ref: str, expectations) -> list[str]:
    """Why a target discrepancy at one point cannot be confirmed. A
    confirmation needs the executed rules to agree with the reference, and
    none of the proposal's own test cases at that point to contradict the
    reference. The model is never ground truth: it can only withhold a
    confirmation, never create one."""
    reasons = []
    if evaluation.status != "DECIDED" or evaluation.decision != ref:
        reasons.append("the proposed rules do not agree with the reference")
    contradicting = sorted({c.expected_decision for c in expectations if c.expected_decision != ref})
    if contradicting:
        reasons.append(
            "the proposal's own expected decision (" + ", ".join(contradicting)
            + ") contradicts the reference"
        )
    return reasons


def _target_summary(r: PointResult, rules, ref: str, reasons: list[str]) -> str:
    where = f"amount ${r.amount} {'with' if r.has_service_date else 'without'} a service date"
    got = r.target.decision or f"no decision ({r.target.error})"
    if reasons:
        return (
            f"The target decides {got} at {where}; the reference decides {ref} and the "
            f"proposed rules decide {r.evaluation.decision or 'nothing'}. Not confirmed: "
            + "; ".join(reasons) + "."
        )
    rule = rules[r.evaluation.decided_by]
    return (
        f"The target decides {got} at {where}. The independent reference and the executed "
        f"proposed rules both decide {ref} (rule {rule.id}, citing \"{rule.evidence}\")."
    )


def _all_agree(r: PointResult) -> bool:
    ev = r.evaluation
    if ev.status != "DECIDED":
        return False
    decisions = {ev.decision}
    decisions.update(case.expected_decision for case in r.expectations)
    for outcome in (r.reference, r.target):
        if outcome is not None:
            decisions.add(outcome.decision)
    return decisions == {ev.decision}


def _perspectives(r: PointResult) -> dict[str, Any]:
    return {
        "expected": [case.expected_decision for case in r.expectations],
        "reference": r.reference.decision if r.reference else None,
        "target": r.target.decision if r.target else None,
    }


def _level(results, findings, reference, target, outcome=None):
    codes = {f.code for f in findings}
    ranges = [f for f in findings if f.details.get("kind") == "range"]
    expectations = [(case, r) for r in results for case in r.expectations]
    agreeing = sum(
        1 for case, r in expectations
        if r.evaluation.status == "DECIDED" and case.expected_decision == r.evaluation.decision
    )
    gaps = sum(r.evaluation.status == "NO_MATCH" for r in results)
    overlaps = sum(r.evaluation.has_conflicting_matches for r in results)
    reference_ok = reference is not None and all(
        r.reference.decision is not None
        and r.evaluation.status == "DECIDED"
        and r.evaluation.decision == r.reference.decision
        for r in results
    )
    unjudged = outcome.unjudged if outcome is not None else 0
    target_ok = target is not None and reference is not None and not ranges and not unjudged and all(
        r.target.decision is not None and r.target.decision == r.reference.decision
        for r in results
    )
    searched = (
        f" and in all {outcome.calls} target-search evaluations" if outcome is not None else ""
    )
    skipped = sum(1 for r in results if r.target is not None and r.target.failure in NOT_EVALUATED)
    criteria = {
        "L0": {"met": True, "detail": "The rules passed schema validation and evidence "
               "grounding, and the interpreter supports every construct they use."},
        "L1": {"met": "COVERAGE_GAP" not in codes and "SELF_INCONSISTENT" not in codes,
               "detail": f"{len(results)} points executed; {gaps} without a decision; "
               f"{agreeing} of {len(expectations)} model expectations agree; "
               f"{overlaps} precedence-dependent point(s) reported."},
        "L2": {"met": reference_ok,
               "detail": "no reference supplied" if reference is None else
               "interpreted rules and reference agree at every evaluated point" if reference_ok
               else "interpreted rules and reference do not agree at every evaluated point"},
        "L3": {"met": target_ok,
               "detail": "no target supplied" if target is None else
               "no reference to compare the target with" if reference is None else
               f"target agrees with the reference at every evaluated point{searched}" if target_ok
               else f"the target was not evaluated at {skipped} point(s)" if skipped
               else f"{unjudged} of {outcome.calls} target-search evaluations could not be judged"
               if unjudged
               else f"target search found {len(ranges)} range(s) where the target disagrees"
               if ranges else "target does not agree with the reference at every evaluated point"},
    }
    level = "NONE"
    for name in LEVELS:
        if not criteria[name]["met"]:
            break
        level = name
    return level, criteria


def _verification_section(level, criteria, point_count, outcome=None) -> dict[str, Any]:
    searched = "" if outcome is None else (
        f" In addition, the target was called at {outcome.calls} amounts chosen by a seeded "
        f"search (seed {outcome.seed}, budget {outcome.budget}) between those points"
        + (f", of which {outcome.unjudged} could not be judged" if outcome.unjudged else "")
        + "; that is sampling, not exhaustive checking."
    )
    return {
        "level": level,
        "level_meaning": LEVEL_MEANING,
        "criteria": criteria,
        "scope": (
            f"Results cover {point_count} evaluated points: boundary points derived from the "
            "rules' amount thresholds, \"$\" amounts found in the policy text, and the proposal's own "
            "test cases, inside the schema domain for both values of has_service_date. For the "
            "rule document these points show every distinct behaviour it has. For the "
            "reference and the target, agreement holds at these points only." + searched
        ),
        "not_established": list(NOT_ESTABLISHED),
    }


def _rule_record(rule) -> dict[str, Any]:
    return {
        "id": rule.id,
        "priority": rule.priority,
        "decision": rule.decision,
        "description": rule.description,
        "conditions": [
            {"field": c.field, "operator": c.operator,
             "value": str(c.value) if isinstance(c.value, Decimal) else c.value}
            for c in rule.conditions
        ],
        "evidence": {"quote": rule.evidence, "span": list(rule.evidence_span)},
    }


def _point_record(r: PointResult) -> dict[str, Any]:
    ev = r.evaluation
    return {
        "id": r.id,
        "amount": str(r.amount),
        "has_service_date": r.has_service_date,
        "sources": list(r.sources),
        "interpreted": {
            "status": ev.status,
            "decision": ev.decision,
            "decided_by": ev.decided_by,
            "matching_rule_ids": list(ev.matching_rule_ids),
            "conflicting_matches": ev.has_conflicting_matches,
            "trace": [
                {
                    "rule_id": t.rule_id, "priority": t.priority, "decision": t.decision,
                    "matched": t.matched, "decided": t.decided,
                    "conditions": [
                        {"index": c.index, "field": c.field, "operator": c.operator,
                         "expected": str(c.expected) if isinstance(c.expected, Decimal) else c.expected,
                         "actual": str(c.actual) if isinstance(c.actual, Decimal) else c.actual,
                         "holds": c.holds}
                        for c in t.conditions
                    ],
                }
                for t in ev.rule_traces
            ],
        },
        "model_expectations": [
            {"case_id": c.id, "expected_decision": c.expected_decision, "rule_id": c.rule_id}
            for c in r.expectations
        ],
        "reference": None if r.reference is None else
        {"decision": r.reference.decision, "error": r.reference.error},
        "target": None if r.target is None else
        {"decision": r.target.decision, "error": r.target.error, "failure": r.target.failure},
    }


def _finding_record(finding: Finding) -> dict[str, Any]:
    return {
        "code": finding.code,
        "severity": finding.severity,
        "summary": finding.summary,
        "points": list(finding.points),
        "rules": list(finding.rules),
        "details": finding.details,
    }


REFERENCE_NAMES = ("democo-meal",)
TARGET_NAMES = ("democo-buggy", "democo-fixed", "democo-loophole")


def _registry() -> tuple[dict[str, Implementation], dict[str, Implementation]]:
    """The only implementations the CLI can run: fixed, trusted local code."""
    from examples import buggy_engine, fixed_engine, loophole_engine
    from src.policyproof import reference

    references = {
        "democo-meal": Implementation(
            "democo-meal-reference",
            "Human-written synthetic reference for the fictional DemoCo meal policy "
            "(src/policyproof/reference.py). It encodes the same missing-date precedence "
            "assumption as the rules, so it is one interpretation, not ground truth.",
            reference.evaluate_meal_claim,
        )
    }
    targets = {
        "democo-buggy": Implementation(
            "democo-buggy-engine",
            "Deliberately buggy DemoCo engine (examples/buggy_engine.py).",
            buggy_engine.evaluate_meal_claim,
            "examples.buggy_engine:evaluate_meal_claim",
        ),
        "democo-fixed": Implementation(
            "democo-fixed-engine",
            "Corrected DemoCo engine (examples/fixed_engine.py).",
            fixed_engine.evaluate_meal_claim,
            "examples.fixed_engine:evaluate_meal_claim",
        ),
        "democo-loophole": Implementation(
            "democo-loophole-engine",
            "DemoCo engine with a seeded loophole far from the policy's threshold "
            "(examples/loophole_engine.py).",
            loophole_engine.evaluate_meal_claim,
            "examples.loophole_engine:evaluate_meal_claim",
        ),
    }
    return references, targets


def main(argv: list[str] | None = None) -> int:
    """Exit codes (see EXIT_CODES): 0 OK, 1 operational error, 2 proposal
    rejected, 3 error findings, 4 inconclusive, 5 below --require-level."""
    parser = argparse.ArgumentParser(
        description="Verify Muse Spark's proposed rules against a policy, a reference and a target.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="exit codes (highest precedence first):\n" + "\n".join(
            f"  {code}  {label:<12} {meaning}" for code, label, meaning in EXIT_CODES
        ) + "\n  argparse usage errors also exit with 2.",
    )
    parser.add_argument("policy", type=Path, help="policy text file (UTF-8)")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--replay", type=Path, metavar="RESPONSE_JSON",
                        help="verify a saved Muse Spark response offline")
    source.add_argument("--live", action="store_true",
                        help="call the Muse Spark API (needs META_MUSE_API_KEY)")
    parser.add_argument("--reference", choices=REFERENCE_NAMES,
                        help="independent human-written reference")
    parser.add_argument("--target", choices=TARGET_NAMES, help="implementation under test")
    parser.add_argument("--report", type=Path, metavar="PATH",
                        help="write the JSON evidence report; it quotes the policy evidence")
    parser.add_argument("--overwrite", action="store_true",
                        help="allow --report to replace an existing file")
    parser.add_argument("--search-budget", type=_budget, default=DEFAULT_BUDGET, metavar="N",
                        help=f"maximum target calls for the target search (0 disables it; "
                        f"default {DEFAULT_BUDGET}, at most {MAX_BUDGET})")
    parser.add_argument("--target-timeout", type=_timeout, default=DEFAULT_TARGET_TIMEOUT,
                        metavar="SECONDS",
                        help=f"run the target in a worker process and abandon any call that takes "
                        f"longer (default {DEFAULT_TARGET_TIMEOUT:g}; 0 runs it in-process with no "
                        f"timeout; at most {MAX_TIMEOUT:g})")
    parser.add_argument("--target-time-limit", type=_time_limit, default=DEFAULT_TIME_LIMIT,
                        metavar="SECONDS",
                        help=f"total time allowed for target calls; later calls are skipped and "
                        f"reported as not evaluated (default {DEFAULT_TIME_LIMIT:g})")
    parser.add_argument("--require-level", choices=LEVELS, metavar="LEVEL",
                        help="exit 5 (INSUFFICIENT_EVIDENCE) when the run would otherwise be OK "
                        "but reaches a lower verification level; for CI use L3 to require an "
                        "independent reference and a target that agrees with it (default: no "
                        "minimum)")
    parser.add_argument("--search-seed", type=int, default=DEFAULT_SEED, metavar="SEED",
                        help=f"seed for the target search (default {DEFAULT_SEED})")
    parser.add_argument("--no-source-probes", action="store_true",
                        help="do not probe amounts written in the target's source code")
    args = parser.parse_args(argv)

    if args.overwrite and not args.report:
        return _fail("--overwrite only applies to --report")
    if args.report and args.report.exists() and not args.overwrite:
        return _fail(f"{args.report} already exists; pass --overwrite to replace it")

    try:
        policy_text = args.policy.read_text(encoding="utf-8")
        if args.replay:
            proposal = replay_proposal(args.replay, policy_text)
        else:
            proposal = MuseClient.from_env().propose_rules(policy_text)
    except ProposalRejectedError as exc:
        result = rejection_result(exc, policy_text)
    except (MuseClientError, ValueError, OSError) as exc:
        return _fail(str(exc))
    else:
        references, targets = _registry()
        result = verify(
            proposal.document, policy_text, proposal=proposal,
            reference=references.get(args.reference), target=targets.get(args.target),
            search_budget=args.search_budget, search_seed=args.search_seed,
            source_probes=not args.no_source_probes,
            target_timeout=args.target_timeout or None, target_time_limit=args.target_time_limit,
            required_level=args.require_level,
        )

    _print_summary(result)
    if args.report:
        try:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            with args.report.open("w" if args.overwrite else "x", encoding="utf-8") as handle:
                handle.write(result.to_json())
        except OSError as exc:
            return _fail(f"could not write report: {exc}")
        print(f"Report written to {args.report}. It quotes policy evidence; handle it like the policy.")

    return result.report["verification"]["result"]["exit_code"]


def _print_summary(result: VerificationResult) -> None:
    report = result.report
    print(report["proposal"]["provenance"])
    print(f"Verification level: {result.level}")
    for name, criterion in report["verification"]["criteria"].items():
        print(f"  {name} {'met' if criterion['met'] else 'not met'}: {criterion['detail']}")
    execution = report.get("target_execution", {})
    if execution.get("mode") == "isolated-worker-process":
        print(f"Target execution: isolated worker process, {execution['timeout_seconds']:g} s per call, "
              f"{execution['calls']} calls, {execution['timeouts']} timeout(s), "
              f"{execution['worker_crashes']} crash(es), {execution['not_run']} skipped; "
              "not a security sandbox.")
    elif execution.get("mode") == "in-process":
        print("Target execution: in-process, no timeout.")
    search = report.get("target_search", {})
    if search.get("performed"):
        print(f"Target search: {search['target_calls']} target calls "
              f"({search['probe_calls']} probes, {search['bisection_calls']} bisection) of a "
              f"budget of {search['budget']}, seed {search['seed']}; "
              f"{search['ranges_found']} discrepancy range(s) found, "
              f"{search['unjudged_evaluations']} evaluation(s) not judged. Sampling, not exhaustive.")
        source = search.get("source_amounts", {})
        if source.get("used") and source.get("amounts"):
            print(f"Source amounts probed: {', '.join('$' + a for a in source['amounts'])} "
                  f"(read from {source['read_from']}; parsed, not executed).")
        elif source.get("used"):
            print(f"Source amounts probed: none ({source.get('unavailable') or 'no amounts in the source'}).")
    for finding in result.findings:
        points = f" [{', '.join(finding.points)}]" if finding.points and finding.code != "CHECKED" else ""
        print(f"{finding.severity.upper():<7} {finding.code}: {finding.summary}{points}")
    print("Not established: semantic correctness; see the report's scope and not_established.")
    outcome = report["verification"].get("result", {})
    print(f"Result: {outcome.get('label')} (exit code {outcome.get('exit_code')}): {outcome.get('meaning')}")


def _timeout(value: str) -> float:
    seconds = float(value)
    if not (seconds == 0 or 0 < seconds <= MAX_TIMEOUT):
        raise argparse.ArgumentTypeError(f"must be 0 or in (0, {MAX_TIMEOUT:g}]")
    return seconds


def _time_limit(value: str) -> float:
    seconds = float(value)
    if not 0 < seconds <= MAX_TIME_LIMIT:
        raise argparse.ArgumentTypeError(f"must be in (0, {MAX_TIME_LIMIT:g}]")
    return seconds


def _budget(value: str) -> int:
    budget = int(value)
    if not 0 <= budget <= MAX_BUDGET:
        raise argparse.ArgumentTypeError(f"must be from 0 to {MAX_BUDGET}")
    return budget


def _fail(message: str) -> int:
    print(f"error: {message}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
