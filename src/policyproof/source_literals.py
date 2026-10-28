"""Amounts written in a target's own source code, as extra search probes.

The target search samples between evaluated points, so a fault confined to a
few cents far from any threshold is almost never hit (benchmark corpus v2:
$777.77 and $12,345.67-$12,345.99 were missed in every search-enabled run).
Hand-written special cases, however, usually spell their amounts out. This
module reads the target function's source text and collects the numeric
literals in it, and in the module-level constants it names, so the search
can probe each one and the cents either side.

The source is parsed with ``ast`` and never executed or evaluated: a
constant computed from other constants (``LIMIT * 50``) contributes only its
literal operands, not its value. The amounts are probes, nothing more. A
probe becomes evidence only through the target's and the reference's actual
decisions there, exactly like every other search call.
"""

import ast
import inspect
import re
import textwrap
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path

CENT = Decimal("0.01")
MAX_SOURCE_AMOUNTS = 100
_NUMERIC_TEXT = re.compile(r"\d{1,7}(\.\d{1,2})?")


@dataclass(frozen=True)
class SourceAmounts:
    amounts: tuple[Decimal, ...]
    # Where the amounts were read, or why none could be.
    source: str | None
    unavailable: str | None = None


def source_amounts(function: Callable, low: Decimal, high: Decimal) -> SourceAmounts:
    """The whole-cent amounts in [low, high] written in ``function``'s source
    and in the module-level constants it refers to by name, ascending."""
    try:
        path = inspect.getsourcefile(function)
        lines, first = inspect.getsourcelines(function)
    except (TypeError, OSError) as exc:
        return SourceAmounts((), None, f"source not available: {exc}")
    if path is None or getattr(function, "__name__", "<lambda>") == "<lambda>":
        return SourceAmounts((), None, "source not available: not a named function")
    try:
        node = ast.parse(textwrap.dedent("".join(lines)))
        module = ast.parse(Path(path).read_text(encoding="utf-8"))
    except (OSError, SyntaxError, UnicodeDecodeError, ValueError) as exc:
        return SourceAmounts((), None, f"source could not be parsed: {exc}")

    constants = {}
    for statement in module.body:
        if isinstance(statement, ast.Assign) and len(statement.targets) == 1 \
                and isinstance(statement.targets[0], ast.Name):
            constants[statement.targets[0].id] = statement.value
        elif isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name) \
                and statement.value is not None:
            constants[statement.target.id] = statement.value

    trees, seen = [node], set()
    names = [n.id for n in ast.walk(node) if isinstance(n, ast.Name)]
    while names:  # module constants, and the constants they name in turn
        name = names.pop()
        if name in seen or name not in constants:
            continue
        seen.add(name)
        trees.append(constants[name])
        names.extend(n.id for n in ast.walk(constants[name]) if isinstance(n, ast.Name))

    found = set()
    for tree in trees:
        for item in ast.walk(tree):
            amount = _amount(item)
            if amount is not None and low <= amount <= high:
                found.add(amount)
    where = f"{Path(path).name}:{first} {function.__name__}()"
    return SourceAmounts(tuple(sorted(found))[:MAX_SOURCE_AMOUNTS], where)


def _amount(node: ast.AST) -> Decimal | None:
    """A literal that could be a whole-cent amount: an int or float, or a
    string such as "777.77" (the usual way to write a Decimal)."""
    if not isinstance(node, ast.Constant) or isinstance(node.value, bool):
        return None
    value = node.value
    if isinstance(value, str):
        if not _NUMERIC_TEXT.fullmatch(value):
            return None
    elif not isinstance(value, (int, float)):
        return None
    try:
        amount = Decimal(str(value))
    except InvalidOperation:
        return None
    if amount < 0 or amount != amount.quantize(CENT):
        return None
    return amount.quantize(CENT)
