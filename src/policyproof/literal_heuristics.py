"""Two more parse-only probe heuristics over the target's source: numbers
inside string literals (method G) and integer literals read as cents
(method H).

Both read exactly what source_literals reads (the target function and the
module-level constants it names, transitively), parse it with ``ast`` and
never execute or evaluate it. Like every probe, an amount found here is
only a place to look: it becomes evidence solely through the target's and
the reference's actual decisions there.

G, numbers in strings. Source amounts (B) take a string only when the
whole string is a number ("777.77"). G also scans inside other strings,
such as a configuration value "approve:7531.24-7531.89". A token is a
plain decimal with at most two fractional digits, not glued to letters,
digits or a decimal point: "1.005", "0.9213", "v1.2.3", "id42" and "40USD"
yield nothing, nor does a token with a leading zero such as "05". "7,531.24"
is probed both as 7531.24 and as 7 and 531.24,
because a comma may group thousands or separate items; probing both
readings is cheaper than guessing. Docstrings are skipped.

H, integers as cents. B reads the literal 654321 as $654,321.00. H reads
an integer as cents only with explicit evidence in the code, recorded with
each amount:
  scale  the integer is compared with, or used to look up, an expression
         that multiplies the claim amount by 100 (``int(case.amount * 100)
         in TABLE``, ``cents == 654321``, ``TABLE.get(cents)``), followed
         through local variables and the module constants it names;
  name   the integer is bound to a name with its own word "cent" or
         "cents" (``_OVERRIDE_CENTS``, ``limitCents``; not ``PERCENT``).
Integers of 100 or more without such evidence are not read as cents; the
result counts them, so the omission is never silent. The factor 100 of a
scaling expression is not itself read as an amount.

H abstains, and records why in ``declined``, when the unit is ambiguous:
  ratio         a division takes part in the scaled expression
                (``amount / limit * 100`` is a percentage, ``amount * 100 /
                limit`` too): no scale evidence from it;
  contradicted  a name meaning cents is compared directly with the amount
                in dollars (``case.amount <= LIMIT_CENTS``): the code itself
                uses it as dollars, so the name is not evidence.

The factor is recognised as 100 or 100.0, or ``Decimal(100)``,
``Decimal("100")``, ``decimal.Decimal(100)`` (the call named Decimal with
one literal argument). An alias (``D = Decimal``), ``10 ** 2`` or a named
constant holding 100 is not recognised; those give no scale evidence.

Limits: no inter-procedural data flow (a helper that converts to cents is
not followed), no tuple unpacking (``lo, hi = BAND``), no other scale
factors (mills, basis points), and names from other modules are not
followed. The cost of a wrong reading is three probe calls, never a
finding.

Correction (2026-11-01): marking the nodes of a ``Decimal(100)`` factor
also marked Python's single shared ``ast.Load`` context object, so every
loaded name looked "already scaled" and tables looked up by
``Decimal(100) * amount`` were never read. Context objects are no longer
marked.
"""

import ast
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from src.policyproof.source_literals import CENT, MAX_SOURCE_AMOUNTS, _resolve

MAX_STRING_CHARS = 10_000   # characters scanned per string literal
MAX_ORIGINS = 3             # examples of where each amount was read
MIN_CENTS = 100             # integers below 100 (under $1.00) are not read as cents

_BOUND_BEFORE = r"(?<![\w.])"
_BOUND_AFTER = r"(?!\w|\.\d)"
# No leading zero before another digit ("000.00" in "1,000.00", "05"): such
# a token is never a written amount on its own.
_PLAIN_NUMBER = re.compile(_BOUND_BEFORE + r"(?!0\d)\d{1,7}(?:\.\d{1,2})?" + _BOUND_AFTER)
_GROUPED_NUMBER = re.compile(r"(?<![\w.,])\d{1,3}(?:,\d{3}){1,2}(?:\.\d{1,2})?" + _BOUND_AFTER)
_NAME_WORDS = re.compile(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])|\d+")
_CENT_WORDS = {"cent", "cents"}
_DIVIDE = (ast.Div, ast.FloorDiv, ast.Mod)


@dataclass(frozen=True)
class HeuristicAmounts:
    amounts: tuple[Decimal, ...]
    # amount -> how it was read (string excerpts for G, evidence for H)
    origins: dict[Decimal, tuple[str, ...]] = field(default_factory=dict)
    # Where the amounts were read, or why none could be.
    source: str | None = None
    unavailable: str | None = None
    # H only: integers >= MIN_CENTS in scope that had no cents evidence.
    integers_without_evidence: int = 0
    # H only: readings H abstained from because the unit is ambiguous.
    declined: tuple[str, ...] = ()


def _whole_cents(text: str) -> Decimal | None:
    try:
        amount = Decimal(text)
    except InvalidOperation:
        return None
    if amount < 0 or amount != amount.quantize(CENT):
        return None
    return amount.quantize(CENT)


def _finish(found: dict[Decimal, list[str]], where: str, low: Decimal, high: Decimal,
            **extra) -> HeuristicAmounts:
    kept = sorted(a for a in found if low <= a <= high)[:MAX_SOURCE_AMOUNTS]
    return HeuristicAmounts(tuple(kept), {a: tuple(found[a][:MAX_ORIGINS]) for a in kept}, where, **extra)


# ------------------------------------------------------------ G: strings

def numbers_in_text(text: str) -> list[Decimal]:
    """Whole-cent amounts written inside ``text``, in order of appearance,
    with both readings of a comma-grouped number."""
    if len(text) > MAX_STRING_CHARS:  # never read a number cut in half by the cap
        text = re.sub(r"[\d.,]+$", "", text[:MAX_STRING_CHARS])
    found = []
    for match in sorted([*_PLAIN_NUMBER.finditer(text), *_GROUPED_NUMBER.finditer(text)],
                        key=lambda m: (m.start(), -len(m.group()))):
        amount = _whole_cents(match.group().replace(",", ""))
        if amount is not None and amount not in found:
            found.append(amount)
    return found


def _docstring_nodes(tree: ast.AST) -> set[int]:
    skip = set()
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and body \
                and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                and isinstance(body[0].value.value, str):
            skip.add(id(body[0].value))
    return skip


def string_amounts(function: Callable, low: Decimal, high: Decimal) -> HeuristicAmounts:
    """Method G: whole-cent amounts in [low, high] written inside string
    literals of ``function`` and the module constants it names, ascending."""
    resolved = _resolve(function)
    if isinstance(resolved, str):
        return HeuristicAmounts((), {}, None, resolved)
    node, constants, where = resolved
    found: dict[Decimal, list[str]] = {}
    for tree in [node, *constants]:
        skip = _docstring_nodes(tree)
        for item in ast.walk(tree):
            if isinstance(item, ast.Constant) and isinstance(item.value, str) and id(item) not in skip:
                excerpt = repr(item.value if len(item.value) <= 60 else item.value[:57] + "...")
                for amount in numbers_in_text(item.value):
                    origins = found.setdefault(amount, [])
                    if excerpt not in origins:
                        origins.append(excerpt)
    return _finish(found, where, low, high)


# --------------------------------------------------------------- H: cents

def _is_hundred(node: ast.AST) -> bool:
    if isinstance(node, ast.Constant) and not isinstance(node.value, bool):
        return isinstance(node.value, (int, float)) and node.value == 100
    if isinstance(node, ast.Call) and len(node.args) == 1 and not node.keywords \
            and isinstance(node.func, (ast.Name, ast.Attribute)) \
            and (node.func.id if isinstance(node.func, ast.Name) else node.func.attr) == "Decimal":
        arg = node.args[0]
        if isinstance(arg, ast.Constant) and not isinstance(arg.value, bool):
            if isinstance(arg.value, int):
                return arg.value == 100
            if isinstance(arg.value, str):
                return _whole_cents(arg.value) == Decimal(100)
    return False


def _mentions_amount(node: ast.AST) -> bool:
    return any((isinstance(n, ast.Attribute) and n.attr == "amount")
               or (isinstance(n, ast.Name) and n.id == "amount") for n in ast.walk(node))


def _cent_word(name: str) -> bool:
    return any(w.lower() in _CENT_WORDS for w in _NAME_WORDS.findall(name))


def _target_names(statement: ast.AST) -> list[str]:
    if isinstance(statement, ast.Assign):
        return [t.id for t in statement.targets if isinstance(t, ast.Name)]
    if isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name):
        return [statement.target.id]
    return []


class _Cents:
    def __init__(self, function_tree: ast.AST, constants: list[ast.stmt]):
        self.function = function_tree
        self.module = {name: c.value for c in constants for name in _target_names(c)}
        self.local = {}
        for item in ast.walk(function_tree):
            if isinstance(item, (ast.Assign, ast.AnnAssign)) and item.value is not None:
                for name in _target_names(item):
                    self.local.setdefault(name, item.value)
        self.factors: set[int] = set()  # the 100s of scaling expressions
        self.scaled_names: set[str] = set()
        self.declined: list[str] = []
        for item in ast.walk(function_tree):
            if isinstance(item, ast.BinOp) and isinstance(item.op, ast.Mult):
                for factor, other in ((item.left, item.right), (item.right, item.left)):
                    if _is_hundred(factor) and _mentions_amount(other):
                        if any(isinstance(n, ast.BinOp) and isinstance(n.op, _DIVIDE) for n in ast.walk(other)):
                            self._decline(f"ratio: {ast.unparse(item)} divides before x 100 "
                                          "(a percentage or ratio, not cents)")
                            continue
                        # Never the expr_context objects (ast.Load...): Python
                        # shares one instance across all names, so marking it
                        # made every name look scaled.
                        self.factors.update(id(n) for n in ast.walk(factor)
                                            if not isinstance(n, ast.expr_context))
        changed = True
        while changed:  # local names holding the amount in cents, to a fixed point
            changed = False
            for name, value in self.local.items():
                if name not in self.scaled_names and self.scaled(value):
                    self.scaled_names.add(name)
                    changed = True

    def _decline(self, why: str) -> None:
        if why not in self.declined:
            self.declined.append(why)

    def _holds_scale(self, node: ast.AST) -> bool:
        return any(id(n) in self.factors or (isinstance(n, ast.Name) and n.id in self.scaled_names)
                   for n in ast.walk(node))

    def divided(self, node: ast.AST) -> bool:
        """A division takes part in a scaled expression (amount x 100 / limit)."""
        return any(isinstance(n, ast.BinOp) and isinstance(n.op, _DIVIDE) and self._holds_scale(n)
                   for n in ast.walk(node))

    def scaled(self, node: ast.AST) -> bool:
        return self._holds_scale(node) and not self.divided(node)

    def integers(self, node: ast.AST, seen: frozenset = frozenset()):
        """(literal, binding name or None) for every int literal in ``node``,
        following names to local and module-level assignments."""
        for n in ast.walk(node):
            if isinstance(n, ast.Constant) and type(n.value) is int and id(n) not in self.factors:
                yield n.value, None
            elif isinstance(n, ast.Name) and n.id not in seen and n.id not in self.scaled_names:
                value = self.local.get(n.id, self.module.get(n.id))
                if value is not None:
                    for literal, _ in self.integers(value, seen | {n.id}):
                        yield literal, n.id

    def read(self) -> dict[int, list[str]]:
        evidence: dict[int, list[str]] = {}

        def add(literal: int, why: str):
            if literal >= MIN_CENTS and why not in evidence.setdefault(literal, []):
                evidence[literal].append(why)

        contradicted: set[str] = set()
        for item in ast.walk(self.function):
            if isinstance(item, ast.Compare):
                operands = [item.left, *item.comparators]
                if any(self.divided(o) for o in operands):
                    self._decline(f"ratio: {ast.unparse(item)} compares a scaled amount after a division")
                    continue
                if any(_mentions_amount(o) and not self._holds_scale(o) for o in operands):
                    for o in operands:  # a cents name used as dollars, not converted
                        if isinstance(o, ast.Name) and _cent_word(o.id):
                            contradicted.add(o.id)
                            self._decline(f"contradicted: {o.id} is compared directly with the amount "
                                          "in dollars, so its name is not cents evidence")
                if any(self.scaled(o) for o in operands):
                    for operand in operands:
                        if not self.scaled(operand):
                            for literal, name in self.integers(operand):
                                add(literal, f"scale: {literal} is compared with the amount x 100"
                                             + (f" (via {name})" if name else ""))
            elif isinstance(item, ast.Subscript) and self.scaled(item.slice) and not self.scaled(item.value):
                for literal, name in self.integers(item.value):
                    add(literal, f"scale: {literal} is in a table looked up by the amount x 100"
                                 + (f" (via {name})" if name else ""))
            elif isinstance(item, ast.Call) and isinstance(item.func, ast.Attribute) \
                    and any(self.scaled(a) for a in item.args) and not self.scaled(item.func.value):
                for literal, name in self.integers(item.func.value):
                    add(literal, f"scale: {literal} is in a table looked up by the amount x 100"
                                 + (f" (via {name})" if name else ""))
        for name, value in [*self.module.items(), *self.local.items()]:
            if _cent_word(name) and name not in contradicted:
                for literal, _ in self.integers(value, frozenset({name})):
                    add(literal, f"name: {literal} is bound to {name}")
        return evidence

    def all_integers(self, trees) -> set[int]:
        return {n.value for t in trees for n in ast.walk(t)
                if isinstance(n, ast.Constant) and type(n.value) is int
                and n.value >= MIN_CENTS and id(n) not in self.factors}


def cents_amounts(function: Callable, low: Decimal, high: Decimal) -> HeuristicAmounts:
    """Method H: integer literals of ``function`` and the module constants it
    names that the code itself marks as cents, as amounts in [low, high],
    ascending, each with its evidence."""
    resolved = _resolve(function)
    if isinstance(resolved, str):
        return HeuristicAmounts((), {}, None, resolved)
    node, constants, where = resolved
    analysis = _Cents(node, constants)
    evidence = analysis.read()
    found = {(Decimal(literal) / 100).quantize(CENT): reasons for literal, reasons in evidence.items()}
    without = len(analysis.all_integers([node, *constants]) - set(evidence))
    return _finish(found, where, low, high, integers_without_evidence=without,
                   declined=tuple(analysis.declined))
