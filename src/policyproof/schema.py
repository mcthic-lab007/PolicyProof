"""Strict JSON contract and deterministic validator for proposed policy rules.

Muse Spark proposes rules and test cases as JSON. Nothing it produces is
trusted until it passes this validator. The validator only parses data
(``json`` with exact ``Decimal`` numbers); it never evaluates model output
as code.

Contract, schema_version "1.0". Every object is closed: unknown keys are
errors, and all errors are collected and reported together.

    {
      "schema_version": "1.0",
      "policy_id": "democo-meal-claims",            identifier (see below)
      "rules": [                                    1..100 rules
        {
          "id": "democo-meal-approve-40",           identifier, unique
          "description": "Approve dated claims up to $40",
          "priority": 2,                            integer >= 1, unique;
                                                    lower is evaluated first
          "conditions": [                           0..20; all must hold;
                                                    [] means "always"
            {"field": "has_service_date", "operator": "==", "value": true},
            {"field": "amount", "operator": "<=", "value": 40.00}
          ],
          "decision": "APPROVE",                    APPROVE | REJECT | REVIEW
          "evidence": "Meal claims of $40.00 or less are approved automatically."
        }
      ],
      "test_cases": [                               0..500 cases
        {
          "id": "exact-threshold",                  identifier, unique
          "inputs": {"amount": 40.00, "has_service_date": true},
          "expected_decision": "APPROVE",
          "rule_id": "democo-meal-approve-40",      optional (or null); must
                                                    name a rule above
          "rationale": "..."                        optional (or null)
        }
      ]
    }

Identifiers match ``[a-z0-9][a-z0-9-]{0,63}``. Text fields are non-blank,
at most 1,000 characters, and valid Unicode (no unpaired surrogates).
JSON may nest at most 32 levels; deeper input is rejected before parsing.

Fields:
  amount            JSON number, 0 <= amount <= 1,000,000.00, whole cents.
                    Canonicalized to exactly two decimal places
                    (40 -> 40.00, 4E+1 -> 40.00, -0.00 -> 0.00).
                    Operators: < <= > >= == !=
  has_service_date  JSON boolean. Operators: == !=

Evidence: each rule quotes at least 15 characters of the policy. The quote
must appear in the policy and start and end on token boundaries: it may not
begin or end inside a word or a number ("$4" does not quote "$40.00").
Before comparison both texts are folded the same way:
  - runs of whitespace become one space;
  - invisible format characters (Unicode category Cf: zero-width spaces and
    joiners, soft hyphens, byte-order marks, bidi marks) are removed;
  - typographic quotes, primes and dashes become ASCII ' " -;
  - canonical equivalents are unified (NFC), and compatibility characters
    are folded (NFKC: the "fi" ligature, no-break space, full-width
    letters) except where either form has a numeric value, so full-width
    or superscript digits never match ASCII digits.
Case, wording and all other punctuation must match exactly. Words split by
a hyphen at a line break are not rejoined.

Threshold grounding: every "amount" condition value must equal a dollar
amount written in that rule's own quote ("$40", "$40.00", "$1,000.00").
This ties numbers to their source; it does not check that the operator,
the decision or boolean conditions follow from the quote.

``RuleSpec.evidence_span`` is a half-open [start, end) range of Python
string indices into the original, unmodified policy text, so
``policy_text[start:end]`` is the cited passage as written there. It may
differ from the quote in whitespace or in the characters folded above.
"""

import json
import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, get_args

from src.policyproof.models import Decision, TestCase


SCHEMA_VERSION = "1.0"
DECISIONS = frozenset(get_args(Decision))
FIELD_OPERATORS = {
    "amount": frozenset({"<", "<=", ">", ">=", "==", "!="}),
    "has_service_date": frozenset({"==", "!="}),
}
MAX_AMOUNT = Decimal("1000000.00")
CENT = Decimal("0.01")
MIN_EVIDENCE_CHARS = 15
MAX_TEXT_CHARS = 1_000
MAX_DOCUMENT_CHARS = 200_000
MAX_RULES = 100
MAX_CONDITIONS = 20
MAX_TEST_CASES = 500
MAX_PRIORITY = 10_000
ID_PATTERN = re.compile(r"[a-z0-9][a-z0-9-]{0,63}")
MAX_JSON_DEPTH = 32

# "$40", "$ 40.00", "$1,000.00"; ASCII digits only, and never followed by
# another digit or letter of any script, so "$40" is not read out of "$400",
# "$40,5" or "$4⁰".
_DOLLAR_AMOUNT = re.compile(
    r"\$ ?((?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)(?:\.[0-9]+)?)(?![.,]?[0-9])(?!\w)"
)
_TYPOGRAPHIC_FOLDS = str.maketrans(
    {
        "‘": "'", "’": "'", "‚": "'", "‛": "'", "′": "'",
        "“": '"', "”": '"', "„": '"', "‟": '"', "″": '"',
        "‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-",
        "−": "-",
    }
)

DOCUMENT_KEYS = frozenset({"schema_version", "policy_id", "rules", "test_cases"})
RULE_KEYS = frozenset(
    {"id", "description", "priority", "conditions", "decision", "evidence"}
)
CONDITION_KEYS = frozenset({"field", "operator", "value"})
CASE_KEYS = frozenset({"id", "inputs", "expected_decision"})
CASE_OPTIONAL_KEYS = frozenset({"rule_id", "rationale"})
INPUT_KEYS = frozenset(FIELD_OPERATORS)

# Marks a value that is missing or failed validation. A sentinel is needed
# because False is a legitimate field value.
_INVALID: Any = object()


@dataclass(frozen=True)
class ValidationIssue:
    path: str
    message: str

    def __str__(self) -> str:
        return f"{self.path}: {self.message}"


class RuleValidationError(ValueError):
    def __init__(self, issues: list[ValidationIssue]):
        self.issues = tuple(issues)
        lines = "\n".join(f"  - {issue}" for issue in self.issues)
        super().__init__(f"{len(self.issues)} validation error(s):\n{lines}")


@dataclass(frozen=True)
class Condition:
    field: str
    operator: str
    value: Decimal | bool


@dataclass(frozen=True)
class RuleSpec:
    id: str
    description: str
    priority: int
    conditions: tuple[Condition, ...]
    decision: Decision
    evidence: str
    evidence_span: tuple[int, int]


@dataclass(frozen=True)
class ProposedTestCase:
    id: str
    amount: Decimal
    has_service_date: bool
    expected_decision: Decision
    rule_id: str | None = None
    rationale: str | None = None

    def to_test_case(self) -> TestCase:
        return TestCase(self.amount, self.has_service_date, self.id)


@dataclass(frozen=True)
class RuleDocument:
    schema_version: str
    policy_id: str
    rules: tuple[RuleSpec, ...]
    test_cases: tuple[ProposedTestCase, ...]


def parse_rule_document(raw: str | bytes, policy_text: str) -> RuleDocument:
    """Parse model output as JSON and validate it against the policy text."""
    if isinstance(raw, bytes):
        try:
            raw = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise RuleValidationError(
                [ValidationIssue("$", f"not valid UTF-8: {exc.reason}")]
            ) from None
    if not isinstance(raw, str):
        raise TypeError("raw must be str or bytes")
    if len(raw) > MAX_DOCUMENT_CHARS:
        raise RuleValidationError(
            [ValidationIssue("$", f"document exceeds {MAX_DOCUMENT_CHARS} characters")]
        )
    # Checked up front so the outcome does not depend on the interpreter's
    # recursion limit; RecursionError below is only a backstop.
    if _json_depth(raw) > MAX_JSON_DEPTH:
        raise RuleValidationError(
            [ValidationIssue("$", f"JSON nesting exceeds {MAX_JSON_DEPTH} levels")]
        )

    try:
        payload = json.loads(
            raw,
            parse_float=Decimal,
            parse_constant=_reject_constant,
            object_pairs_hook=_reject_duplicate_keys,
        )
    except json.JSONDecodeError as exc:
        raise RuleValidationError(
            [
                ValidationIssue(
                    "$",
                    f"malformed JSON: {exc.msg} "
                    f"(line {exc.lineno}, column {exc.colno})",
                )
            ]
        ) from None
    except ValueError as exc:
        raise RuleValidationError([ValidationIssue("$", str(exc))]) from None
    except RecursionError:
        raise RuleValidationError(
            [ValidationIssue("$", "JSON nesting is too deep to parse")]
        ) from None

    return validate_rule_payload(payload, policy_text)


def validate_rule_payload(payload: Any, policy_text: str) -> RuleDocument:
    """Validate an already-parsed payload. Floats are rejected as inexact."""
    if not isinstance(policy_text, str) or not policy_text.strip():
        raise ValueError("policy_text must be a non-empty string")
    if not _is_valid_unicode(policy_text):
        raise ValueError("policy_text contains invalid Unicode")

    issues: list[ValidationIssue] = []
    document = _document(payload, _fold(policy_text), issues)
    if issues:
        raise RuleValidationError(issues)
    return document


def _json_depth(raw: str) -> int:
    """Maximum bracket nesting outside string literals."""
    depth = deepest = 0
    in_string = escaped = False
    for char in raw:
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
        elif char == '"':
            in_string = True
        elif char in "[{":
            depth += 1
            deepest = max(deepest, depth)
        elif char in "]}":
            depth -= 1
    return deepest


def _reject_constant(name: str) -> None:
    raise ValueError(f"non-finite number {name} is not allowed")


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate key {key!r}")
        result[key] = value
    return result


def _is_valid_unicode(text: str) -> bool:
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


@dataclass(frozen=True)
class _FoldedText:
    """Text folded for comparison, with the original [start, end) range that
    produced each folded character."""

    text: str
    sources: tuple[tuple[int, int], ...]


def _fold(text: str) -> _FoldedText:
    chars: list[str] = []
    sources: list[tuple[int, int]] = []
    start = 0
    while start < len(text):
        # Fold a base character together with its combining marks so NFC
        # composition never crosses a source boundary.
        end = start + 1
        while end < len(text) and unicodedata.combining(text[end]):
            end += 1
        for char in _fold_cluster(text[start:end]):
            if char.isspace():
                if chars and chars[-1] == " ":
                    sources[-1] = (sources[-1][0], end)
                    continue
                char = " "
            chars.append(char)
            sources.append((start, end))
        start = end
    return _FoldedText("".join(chars), tuple(sources))


def _fold_cluster(cluster: str) -> str:
    visible = "".join(c for c in cluster if unicodedata.category(c) != "Cf")
    canonical = unicodedata.normalize("NFC", visible).translate(_TYPOGRAPHIC_FOLDS)
    compatible = unicodedata.normalize("NFKC", canonical)
    if compatible != canonical and any(
        unicodedata.numeric(c, None) is not None for c in canonical + compatible
    ):
        return canonical
    return compatible


def _splits_token(text: str, index: int) -> bool:
    """Whether a cut before text[index] falls inside a word or number."""
    if index <= 0 or index >= len(text):
        return False
    before, after = text[index - 1], text[index]
    if before.isalnum() and after.isalnum():
        return True
    # Decimal and thousands separators inside a number: "40|.00", "40.|00".
    if after in ".," and before.isdigit():
        return index + 1 < len(text) and text[index + 1].isdigit()
    if before in ".," and after.isdigit():
        return index >= 2 and text[index - 2].isdigit()
    return False


def _evidence_span(
    evidence: str, policy: _FoldedText, path: str, issues: list[ValidationIssue]
) -> tuple[int, int]:
    needle = _fold(evidence).text.strip()
    if len(needle) < MIN_EVIDENCE_CHARS:
        issues.append(
            ValidationIssue(
                path,
                f"evidence must quote at least {MIN_EVIDENCE_CHARS} characters of policy text",
            )
        )
        return _INVALID

    found_inside_token = False
    start = policy.text.find(needle)
    while start != -1:
        end = start + len(needle)
        if _splits_token(policy.text, start) or _splits_token(policy.text, end):
            found_inside_token = True
        else:
            return policy.sources[start][0], policy.sources[end - 1][1]
        start = policy.text.find(needle, start + 1)

    if found_inside_token:
        message = (
            "evidence begins or ends in the middle of a word or number: "
            f"{evidence[:80]!r}"
        )
    else:
        message = f"evidence not found verbatim in policy text: {evidence[:80]!r}"
    issues.append(ValidationIssue(path, message))
    return _INVALID


def _stated_dollar_amounts(evidence: str) -> set[Decimal]:
    folded = _fold(evidence).text
    return {
        Decimal(match.group(1).replace(",", ""))
        for match in _DOLLAR_AMOUNT.finditer(folded)
    }


def find_dollar_amounts(text: str) -> tuple[tuple[Decimal, tuple[int, int]], ...]:
    """Dollar amounts written in ``text``, matched exactly as threshold
    grounding matches them, each with its [start, end) position in the
    original, unmodified text. Only "$" amounts are recognised: "40 dollars",
    other currencies and bare numbers are not found."""
    folded = _fold(text)
    return tuple(
        (
            Decimal(match.group(1).replace(",", "")),
            (folded.sources[match.start()][0], folded.sources[match.end() - 1][1]),
        )
        for match in _DOLLAR_AMOUNT.finditer(folded.text)
    )


def _type_name(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float, Decimal)):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


def _object(
    value: Any,
    path: str,
    required: frozenset[str],
    optional: frozenset[str],
    issues: list[ValidationIssue],
) -> bool:
    if not isinstance(value, dict):
        issues.append(ValidationIssue(path, f"expected object, got {_type_name(value)}"))
        return False
    for key in sorted(required - value.keys()):
        issues.append(ValidationIssue(path, f"missing required field {key!r}"))
    for key in sorted(value.keys() - required - optional, key=str):
        issues.append(ValidationIssue(path, f"unknown field {key!r}"))
    return True


def _array(
    value: Any, path: str, min_len: int, max_len: int, issues: list[ValidationIssue]
) -> list[Any] | None:
    if value is _INVALID:
        return None
    if not isinstance(value, list):
        issues.append(ValidationIssue(path, f"expected array, got {_type_name(value)}"))
        return None
    if not min_len <= len(value) <= max_len:
        issues.append(
            ValidationIssue(path, f"must contain {min_len}..{max_len} items, got {len(value)}")
        )
        return None
    return value


def _text(value: Any, path: str, issues: list[ValidationIssue]) -> str:
    if value is _INVALID:
        return _INVALID
    if not isinstance(value, str):
        issues.append(ValidationIssue(path, f"expected string, got {_type_name(value)}"))
        return _INVALID
    if not value.strip():
        issues.append(ValidationIssue(path, "must not be blank"))
        return _INVALID
    if len(value) > MAX_TEXT_CHARS:
        issues.append(ValidationIssue(path, f"exceeds {MAX_TEXT_CHARS} characters"))
        return _INVALID
    if not _is_valid_unicode(value):
        issues.append(ValidationIssue(path, "contains invalid Unicode (unpaired surrogate)"))
        return _INVALID
    return value


def _identifier(value: Any, path: str, issues: list[ValidationIssue]) -> str:
    text = _text(value, path, issues)
    if text is not _INVALID and not ID_PATTERN.fullmatch(text):
        issues.append(
            ValidationIssue(path, f"invalid identifier {text!r}; use [a-z0-9][a-z0-9-]{{0,63}}")
        )
        return _INVALID
    return text


def _decision(value: Any, path: str, issues: list[ValidationIssue]) -> Decision:
    if value is _INVALID:
        return _INVALID
    if not (isinstance(value, str) and value in DECISIONS):
        issues.append(
            ValidationIssue(path, f"invalid decision {value!r}; allowed: {sorted(DECISIONS)}")
        )
        return _INVALID
    return value


def _amount(value: Any, path: str, issues: list[ValidationIssue]) -> Decimal:
    if value is _INVALID:
        return _INVALID
    if isinstance(value, float):
        issues.append(
            ValidationIssue(path, "floats are inexact; supply JSON parsed with Decimal")
        )
        return _INVALID
    if isinstance(value, bool) or not isinstance(value, (int, Decimal)):
        issues.append(ValidationIssue(path, f"expected number, got {_type_name(value)}"))
        return _INVALID
    amount = Decimal(value)
    if not amount.is_finite():
        issues.append(ValidationIssue(path, "amount must be finite"))
        return _INVALID
    if not Decimal(0) <= amount <= MAX_AMOUNT:
        issues.append(ValidationIssue(path, f"amount must be between 0 and {MAX_AMOUNT}"))
        return _INVALID
    canonical = amount.quantize(CENT)
    if amount != canonical:
        issues.append(ValidationIssue(path, "amount must be in whole cents"))
        return _INVALID
    return canonical.copy_abs() if canonical.is_zero() else canonical


def _boolean(value: Any, path: str, issues: list[ValidationIssue]) -> bool:
    if value is _INVALID:
        return _INVALID
    if not isinstance(value, bool):
        issues.append(ValidationIssue(path, f"expected boolean, got {_type_name(value)}"))
        return _INVALID
    return value


_FIELD_PARSERS = {"amount": _amount, "has_service_date": _boolean}


def _condition(raw: Any, path: str, issues: list[ValidationIssue]) -> Condition:
    if not _object(raw, path, CONDITION_KEYS, frozenset(), issues):
        return _INVALID

    field = raw.get("field", _INVALID)
    if field is not _INVALID and not (isinstance(field, str) and field in FIELD_OPERATORS):
        issues.append(
            ValidationIssue(
                f"{path}.field",
                f"unsupported field {field!r}; allowed: {sorted(FIELD_OPERATORS)}",
            )
        )
        field = _INVALID

    operator = raw.get("operator", _INVALID)
    value = raw.get("value", _INVALID)
    if field is _INVALID:
        return _INVALID

    allowed = FIELD_OPERATORS[field]
    if operator is not _INVALID and not (isinstance(operator, str) and operator in allowed):
        issues.append(
            ValidationIssue(
                f"{path}.operator",
                f"unsupported operator {operator!r} for {field!r}; allowed: {sorted(allowed)}",
            )
        )
        operator = _INVALID
    value = _FIELD_PARSERS[field](value, f"{path}.value", issues)

    if operator is _INVALID or value is _INVALID:
        return _INVALID
    return Condition(field, operator, value)


def _rule(
    raw: Any, path: str, policy: _FoldedText, issues: list[ValidationIssue]
) -> RuleSpec:
    if not _object(raw, path, RULE_KEYS, frozenset(), issues):
        return _INVALID

    rule_id = _identifier(raw.get("id", _INVALID), f"{path}.id", issues)
    description = _text(raw.get("description", _INVALID), f"{path}.description", issues)
    decision = _decision(raw.get("decision", _INVALID), f"{path}.decision", issues)

    priority = raw.get("priority", _INVALID)
    if priority is not _INVALID and (
        isinstance(priority, bool)
        or not isinstance(priority, int)
        or not 1 <= priority <= MAX_PRIORITY
    ):
        issues.append(
            ValidationIssue(f"{path}.priority", f"expected integer 1..{MAX_PRIORITY}")
        )
        priority = _INVALID

    conditions: Any = _INVALID
    raw_conditions = _array(
        raw.get("conditions", _INVALID), f"{path}.conditions", 0, MAX_CONDITIONS, issues
    )
    if raw_conditions is not None:
        parsed = [
            _condition(item, f"{path}.conditions[{index}]", issues)
            for index, item in enumerate(raw_conditions)
        ]
        if all(item is not _INVALID for item in parsed):
            conditions = tuple(parsed)

    evidence = _text(raw.get("evidence", _INVALID), f"{path}.evidence", issues)
    span: Any = _INVALID
    if evidence is not _INVALID:
        span = _evidence_span(evidence, policy, f"{path}.evidence", issues)

    # Threshold grounding is only meaningful once the quote itself is valid.
    if conditions is not _INVALID and span is not _INVALID:
        stated = _stated_dollar_amounts(evidence)
        for index, condition in enumerate(conditions):
            if condition.field == "amount" and condition.value not in stated:
                issues.append(
                    ValidationIssue(
                        f"{path}.conditions[{index}].value",
                        f"threshold {condition.value} is not stated as a dollar "
                        "amount in this rule's evidence",
                    )
                )
                conditions = _INVALID

    fields = (rule_id, description, priority, conditions, decision, evidence, span)
    if any(item is _INVALID for item in fields):
        return _INVALID
    return RuleSpec(*fields)


def _test_case(raw: Any, path: str, issues: list[ValidationIssue]) -> ProposedTestCase:
    if not _object(raw, path, CASE_KEYS, CASE_OPTIONAL_KEYS, issues):
        return _INVALID

    case_id = _identifier(raw.get("id", _INVALID), f"{path}.id", issues)
    expected = _decision(
        raw.get("expected_decision", _INVALID), f"{path}.expected_decision", issues
    )

    rule_id = raw.get("rule_id")
    if rule_id is not None:
        rule_id = _identifier(rule_id, f"{path}.rule_id", issues)
    rationale = raw.get("rationale")
    if rationale is not None:
        rationale = _text(rationale, f"{path}.rationale", issues)

    amount = has_service_date = _INVALID
    inputs = raw.get("inputs", _INVALID)
    if inputs is not _INVALID and _object(
        inputs, f"{path}.inputs", INPUT_KEYS, frozenset(), issues
    ):
        amount = _amount(inputs.get("amount", _INVALID), f"{path}.inputs.amount", issues)
        has_service_date = _boolean(
            inputs.get("has_service_date", _INVALID),
            f"{path}.inputs.has_service_date",
            issues,
        )

    fields = (case_id, amount, has_service_date, expected, rule_id, rationale)
    if any(item is _INVALID for item in fields):
        return _INVALID
    return ProposedTestCase(*fields)


def _document(
    payload: Any, policy: _FoldedText, issues: list[ValidationIssue]
) -> RuleDocument:
    if not _object(payload, "$", DOCUMENT_KEYS, frozenset(), issues):
        return _INVALID

    version = payload.get("schema_version", _INVALID)
    if version is not _INVALID and version != SCHEMA_VERSION:
        issues.append(
            ValidationIssue(
                "$.schema_version",
                f"unsupported schema_version {version!r}; expected {SCHEMA_VERSION!r}",
            )
        )
    policy_id = _identifier(payload.get("policy_id", _INVALID), "$.policy_id", issues)

    rules: list[RuleSpec] = []
    raw_rules = _array(payload.get("rules", _INVALID), "$.rules", 1, MAX_RULES, issues)
    for index, item in enumerate(raw_rules or []):
        rule = _rule(item, f"$.rules[{index}]", policy, issues)
        if rule is not _INVALID:
            rules.append(rule)

    cases: list[ProposedTestCase] = []
    raw_cases = _array(
        payload.get("test_cases", _INVALID), "$.test_cases", 0, MAX_TEST_CASES, issues
    )
    for index, item in enumerate(raw_cases or []):
        case = _test_case(item, f"$.test_cases[{index}]", issues)
        if case is not _INVALID:
            cases.append(case)

    _check_unique(rules, "id", "$.rules", issues)
    _check_unique(rules, "priority", "$.rules", issues)
    _check_unique(cases, "id", "$.test_cases", issues)

    # Check references against every declared id, not only rules that
    # validated, so one bad rule does not cascade into reference errors.
    rule_ids = {
        item.get("id") for item in raw_rules or [] if isinstance(item, dict)
    }
    for index, case in enumerate(cases):
        if case.rule_id is not None and case.rule_id not in rule_ids:
            issues.append(
                ValidationIssue(
                    f"$.test_cases[{index}].rule_id",
                    f"references unknown rule {case.rule_id!r}",
                )
            )

    if issues:
        return _INVALID
    return RuleDocument(version, policy_id, tuple(rules), tuple(cases))


def _check_unique(
    items: list[Any], attribute: str, path: str, issues: list[ValidationIssue]
) -> None:
    seen: set[Any] = set()
    for item in items:
        value = getattr(item, attribute)
        if value in seen:
            issues.append(ValidationIssue(path, f"duplicate {attribute} {value!r}"))
        seen.add(value)
