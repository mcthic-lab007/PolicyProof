"""Deterministic interpreter and boundary derivation for validated rules.

Evaluation semantics, as stated by the rule contract (schema.py) and the
Muse Spark prompt:
  - Rules are considered in ascending priority; priorities are unique.
  - A rule matches when ALL of its conditions hold. A rule with no
    conditions always matches.
  - The first matching rule decides. If no rule matches there is no
    decision: the status is NO_MATCH and the decision is None, never a
    default approval.
  - Every rule and every condition is still evaluated and traced, so a
    later rule that also matched (an overlap silently resolved by
    priority) remains visible in ``Evaluation.matching_rule_ids``.

Only the fields, operators and decisions of the schema are supported, and
comparisons go through a fixed operator table. Nothing is evaluated as code.
A document is re-checked against that allowlist when an engine is built, so
a hand-constructed ``RuleDocument`` cannot smuggle in other constructs.

Inputs are a mapping with exactly the schema's fields: "amount" (Decimal,
whole cents, inside the schema domain 0.00..1,000,000.00) and
"has_service_date" (bool). Anything else yields INVALID_INPUT.

What a successful evaluation shows: what these rules decide for this input.
It does not show that the rules interpret the policy correctly; that needs
comparison with expectations or an independent reference.

Boundary derivation (``derive_boundary_points``) is described on that
function.
"""

import itertools
import operator
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Literal

from src.policyproof.models import Decision, TestCase
from src.policyproof.schema import (
    CENT,
    DECISIONS,
    FIELD_OPERATORS,
    MAX_AMOUNT,
    MAX_CONDITIONS,
    MAX_RULES,
    Condition,
    RuleDocument,
    RuleSpec,
)


_OPERATORS: dict[str, Callable[[Any, Any], bool]] = {
    "<": operator.lt,
    "<=": operator.le,
    ">": operator.gt,
    ">=": operator.ge,
    "==": operator.eq,
    "!=": operator.ne,
}

# Inclusive whole-cent domain of each numeric field. These are the schema's
# representable range, not limits stated by any policy.
NUMERIC_DOMAINS = {"amount": (Decimal("0.00"), MAX_AMOUNT)}
BOOLEAN_FIELDS = ("has_service_date",)
FIELDS = frozenset(NUMERIC_DOMAINS) | frozenset(BOOLEAN_FIELDS)

if FIELDS != frozenset(FIELD_OPERATORS) or not all(
    ops <= _OPERATORS.keys() for ops in FIELD_OPERATORS.values()
):
    raise ImportError("rule_engine does not cover the schema's fields and operators")

# Largest point set any schema-valid document can produce: every condition
# of every rule contributes one threshold (three amounts), plus two domain
# endpoints, for each value of the boolean field.
SCHEMA_MAX_POINTS = (2 + 3 * MAX_RULES * MAX_CONDITIONS) * 2
DEFAULT_MAX_POINTS = 20_000

Status = Literal["DECIDED", "NO_MATCH", "INVALID_INPUT"]


class RuleEngineError(ValueError):
    pass


class UnsupportedRuleError(RuleEngineError):
    """The document uses something the interpreter does not support."""

    def __init__(self, problems: list[str]):
        self.problems = tuple(problems)
        lines = "\n".join(f"  - {problem}" for problem in self.problems)
        super().__init__(f"unsupported rule document:\n{lines}")


class DerivationLimitError(RuleEngineError):
    pass


@dataclass(frozen=True)
class ConditionTrace:
    index: int
    field: str
    operator: str
    expected: Decimal | bool
    actual: Decimal | bool
    holds: bool


@dataclass(frozen=True)
class RuleTrace:
    rule_id: str
    priority: int
    decision: Decision
    matched: bool
    decided: bool
    conditions: tuple[ConditionTrace, ...]


@dataclass(frozen=True)
class Evaluation:
    status: Status
    decision: Decision | None
    decided_by: str | None
    matching_rule_ids: tuple[str, ...]
    rule_traces: tuple[RuleTrace, ...]
    input_issues: tuple[str, ...]

    @property
    def has_conflicting_matches(self) -> bool:
        """More than one rule matched and they disagree: the decision here
        depends on priority order, not on the conditions alone."""
        decisions = {t.decision for t in self.rule_traces if t.matched}
        return len(decisions) > 1


class RuleEngine:
    """Evaluates one validated rule document. Construction checks the
    document against the supported constructs and raises
    ``UnsupportedRuleError`` rather than guessing."""

    def __init__(self, document: RuleDocument):
        _check_document(document)
        self.document = document
        self.rules = tuple(sorted(document.rules, key=lambda rule: rule.priority))

    def evaluate(self, inputs: Mapping[str, Any]) -> Evaluation:
        issues = _input_issues(inputs)
        if issues:
            return Evaluation("INVALID_INPUT", None, None, (), (), issues)

        traces = []
        decided_by: RuleSpec | None = None
        for rule in self.rules:
            conditions = tuple(
                _trace_condition(index, condition, inputs[condition.field])
                for index, condition in enumerate(rule.conditions)
            )
            matched = all(trace.holds for trace in conditions)
            decided = matched and decided_by is None
            if decided:
                decided_by = rule
            traces.append(
                RuleTrace(rule.id, rule.priority, rule.decision, matched, decided, conditions)
            )

        matching = tuple(trace.rule_id for trace in traces if trace.matched)
        if decided_by is None:
            return Evaluation("NO_MATCH", None, None, matching, tuple(traces), ())
        return Evaluation(
            "DECIDED", decided_by.decision, decided_by.id, matching, tuple(traces), ()
        )


def evaluate(document: RuleDocument, inputs: Mapping[str, Any]) -> Evaluation:
    return RuleEngine(document).evaluate(inputs)


def case_inputs(case: Any) -> dict[str, Any]:
    """Inputs for a ``TestCase``, ``ProposedTestCase`` or ``BoundaryPoint``."""
    return {"amount": case.amount, "has_service_date": case.has_service_date}


@dataclass(frozen=True)
class PointSource:
    """Why an amount was included in the derived points.

    kind "threshold": ``offset`` from a condition's value (``rule_id`` and
    ``condition_index`` identify it); kind "extra": offset from a threshold
    supplied by the caller, described by ``label``; kind "domain_bound": an
    endpoint of the schema domain, which is not a policy limit.
    """

    kind: Literal["threshold", "extra", "domain_bound"]
    label: str
    threshold: Decimal | None = None
    offset: Decimal | None = None
    rule_id: str | None = None
    condition_index: int | None = None


@dataclass(frozen=True)
class BoundaryPoint:
    id: str
    amount: Decimal
    has_service_date: bool
    amount_sources: tuple[PointSource, ...]
    boolean_sources: tuple[str, ...]

    def to_test_case(self) -> TestCase:
        return TestCase(self.amount, self.has_service_date, self.id)


@dataclass(frozen=True)
class BoundaryDerivation:
    points: tuple[BoundaryPoint, ...]
    excluded: tuple[str, ...]  # candidate amounts outside the schema domain


def count_boundary_points(
    document: RuleDocument, extra_thresholds: Iterable[tuple[Decimal, str]] = ()
) -> int:
    amounts, _ = _candidate_amounts(document, tuple(extra_thresholds))
    return len(amounts) * 2 ** len(BOOLEAN_FIELDS)


def derive_boundary_points(
    document: RuleDocument,
    extra_thresholds: Iterable[tuple[Decimal, str]] = (),
    *,
    max_points: int = DEFAULT_MAX_POINTS,
) -> BoundaryDerivation:
    """Derive test points from the rule conditions alone.

    For every amount threshold t (each amount condition's value, plus any
    ``extra_thresholds`` given as (value, provenance label)), the amounts
    t - 0.01, t and t + 0.01 are included, together with the schema domain
    endpoints 0.00 and 1,000,000.00. Amounts outside the domain are dropped
    and listed in ``excluded``. Every amount is combined with both values of
    has_service_date (False represents a missing service date).

    ``document.test_cases`` is never read, so the points do not depend on
    the test cases a model proposed.

    Coverage: because every supported amount condition compares the amount
    with a constant, these points include at least one input from every set
    of inputs on which all of the document's conditions evaluate the same
    way, over the whole schema domain. For this rule document, evaluating
    these points therefore shows every decision it can make. That says
    nothing about other implementations (a reference or a system under
    test), whose decision boundaries may lie at amounts the rules never
    mention, and nothing about whether the rules match the policy.

    Size: (2 + 3 x thresholds) x 2 at most. The default limit covers the
    schema maximum (SCHEMA_MAX_POINTS); a larger count raises
    DerivationLimitError before any point is built.
    """
    extra = tuple(extra_thresholds)
    amounts, excluded = _candidate_amounts(document, extra)
    total = len(amounts) * 2 ** len(BOOLEAN_FIELDS)
    if total > max_points:
        raise DerivationLimitError(
            f"{total} derived points exceed the limit of {max_points}"
        )

    references = {
        field: tuple(
            f"{rule.id}.conditions[{index}]"
            for rule in sorted(document.rules, key=lambda r: r.priority)
            for index, condition in enumerate(rule.conditions)
            if condition.field == field
        )
        for field in BOOLEAN_FIELDS
    }
    points = []
    for amount, flags in itertools.product(
        sorted(amounts), itertools.product((False, True), repeat=len(BOOLEAN_FIELDS))
    ):
        (has_service_date,) = flags
        cited = references["has_service_date"]
        boolean_sources = (
            ("has_service_date referenced by " + ", ".join(cited),)
            if cited
            else ("has_service_date varied although no rule references it",)
        )
        label = "dated" if has_service_date else "undated"
        points.append(
            BoundaryPoint(
                id=f"derived-{amount}-{label}",
                amount=amount,
                has_service_date=has_service_date,
                amount_sources=amounts[amount],
                boolean_sources=boolean_sources,
            )
        )
    return BoundaryDerivation(tuple(points), tuple(excluded))


def _candidate_amounts(
    document: RuleDocument, extra: tuple[tuple[Decimal, str], ...]
) -> tuple[dict[Decimal, tuple[PointSource, ...]], list[str]]:
    _check_document(document)
    low, high = NUMERIC_DOMAINS["amount"]
    sources: dict[Decimal, list[PointSource]] = {
        low: [PointSource("domain_bound", "schema domain lower bound (not a policy limit)")],
        high: [PointSource("domain_bound", "schema domain upper bound (not a policy limit)")],
    }
    excluded: list[str] = []

    thresholds: list[tuple[Decimal, str, str | None, int | None]] = []
    for rule in sorted(document.rules, key=lambda r: r.priority):
        for index, condition in enumerate(rule.conditions):
            if condition.field == "amount":
                label = f"{rule.id}.conditions[{index}]: amount {condition.operator} {condition.value}"
                thresholds.append((condition.value, label, rule.id, index))
    for value, label in extra:
        problem = _value_problem("amount", value)
        if problem:
            raise RuleEngineError(f"extra threshold {value!r} ({label}): {problem}")
        thresholds.append((value, f"extra: {label}", None, None))

    for value, label, rule_id, index in thresholds:
        kind = "threshold" if rule_id is not None else "extra"
        for offset in (-CENT, Decimal("0.00"), CENT):
            amount = _canonical(value + offset)
            source = PointSource(kind, label, value, offset, rule_id, index)
            if low <= amount <= high:
                sources.setdefault(amount, []).append(source)
            else:
                excluded.append(f"{amount} ({label}, offset {offset}): outside schema domain")
    return {amount: tuple(items) for amount, items in sources.items()}, excluded


def _canonical(amount: Decimal) -> Decimal:
    canonical = amount.quantize(CENT)
    return canonical.copy_abs() if canonical.is_zero() else canonical


def _trace_condition(index: int, condition: Condition, actual: Any) -> ConditionTrace:
    holds = _OPERATORS[condition.operator](actual, condition.value)
    return ConditionTrace(
        index, condition.field, condition.operator, condition.value, actual, holds
    )


def _value_problem(field: str, value: Any) -> str | None:
    if field in NUMERIC_DOMAINS:
        if isinstance(value, bool) or not isinstance(value, Decimal):
            return f"expected Decimal, got {type(value).__name__}"
        if not value.is_finite():
            return "must be finite"
        low, high = NUMERIC_DOMAINS[field]
        if not low <= value <= high:
            return f"outside schema domain {low}..{high}"
        if value != value.quantize(CENT):
            return "must be whole cents"
        return None
    if not isinstance(value, bool):
        return f"expected bool, got {type(value).__name__}"
    return None


def _input_issues(inputs: Any) -> tuple[str, ...]:
    if not isinstance(inputs, Mapping):
        return (f"inputs must be a mapping, got {type(inputs).__name__}",)
    issues = [f"missing input {field!r}" for field in sorted(FIELDS - inputs.keys())]
    issues += [
        f"unknown input {key!r}" for key in sorted(inputs.keys() - FIELDS, key=str)
    ]
    for field in sorted(FIELDS & inputs.keys()):
        problem = _value_problem(field, inputs[field])
        if problem:
            issues.append(f"input {field!r}: {problem}")
    return tuple(issues)


def _check_document(document: Any) -> None:
    if not isinstance(document, RuleDocument):
        raise UnsupportedRuleError(
            [f"expected a validated RuleDocument, got {type(document).__name__}"]
        )
    problems: list[str] = []
    if not document.rules:
        problems.append("document has no rules")
    seen_ids: set[Any] = set()
    seen_priorities: set[Any] = set()
    for position, rule in enumerate(document.rules):
        if not isinstance(rule, RuleSpec):
            problems.append(f"rules[{position}]: not a RuleSpec")
            continue
        where = f"rule {rule.id!r}"
        if not isinstance(rule.id, str) or not rule.id:
            problems.append(f"rules[{position}]: id must be a non-empty string")
        elif rule.id in seen_ids:
            problems.append(f"{where}: duplicate id")
        else:
            seen_ids.add(rule.id)
        if isinstance(rule.priority, bool) or not isinstance(rule.priority, int):
            problems.append(f"{where}: priority must be an integer")
        elif rule.priority in seen_priorities:
            problems.append(f"{where}: duplicate priority {rule.priority}")
        else:
            seen_priorities.add(rule.priority)
        if not isinstance(rule.decision, str) or rule.decision not in DECISIONS:
            problems.append(f"{where}: unsupported decision {rule.decision!r}")
        if not isinstance(rule.conditions, tuple):
            problems.append(f"{where}: conditions must be a tuple")
            continue
        for index, condition in enumerate(rule.conditions):
            at = f"{where}.conditions[{index}]"
            if not isinstance(condition, Condition):
                problems.append(f"{at}: not a Condition")
                continue
            if not isinstance(condition.field, str) or condition.field not in FIELDS:
                problems.append(f"{at}: unsupported field {condition.field!r}")
                continue
            if (
                not isinstance(condition.operator, str)
                or condition.operator not in FIELD_OPERATORS[condition.field]
            ):
                problems.append(
                    f"{at}: unsupported operator {condition.operator!r} for {condition.field!r}"
                )
            problem = _value_problem(condition.field, condition.value)
            if problem:
                problems.append(f"{at}: value {problem}")
    if problems:
        raise UnsupportedRuleError(problems)
