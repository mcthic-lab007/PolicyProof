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
    resolved = _resolve(function)
    if isinstance(resolved, str):
        return SourceAmounts((), None, resolved)
    node, constants, where = resolved
    found = set()
    for tree in [node, *constants]:
        for item in ast.walk(tree):
            amount = _amount(item)
            if amount is not None and low <= amount <= high:
                found.add(amount)
    return SourceAmounts(tuple(sorted(found))[:MAX_SOURCE_AMOUNTS], where)


def source_excerpt(function: Callable) -> str | None:
    """The code source_amounts reads, regenerated from its syntax tree: the
    module constants it names, then the function renamed to ``decide``.
    Comments and docstrings are dropped, so the excerpt carries only what
    the code does, not what its author wrote about it. None: no source."""
    resolved = _resolve(function)
    if isinstance(resolved, str):
        return None
    node, constants, _ = resolved
    function_node = next(n for n in ast.walk(node) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)))
    function_node.name = "decide"
    function_node.decorator_list = []
    for item in ast.walk(function_node):
        body = getattr(item, "body", None)
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and body \
                and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                and isinstance(body[0].value.value, str):
            item.body = body[1:] or [ast.Pass()]
    parts = [ast.unparse(c) for c in constants] + ["", ast.unparse(function_node)]
    return "\n".join(parts).strip() + "\n"


def _resolve(function: Callable):
    """(function syntax tree, module-level constant assignments it names,
    where) or the reason the source cannot be read."""
    try:
        path = inspect.getsourcefile(function)
        lines, first = inspect.getsourcelines(function)
    except (TypeError, OSError) as exc:
        return f"source not available: {exc}"
    if path is None or getattr(function, "__name__", "<lambda>") == "<lambda>":
        return "source not available: not a named function"
    try:
        node = ast.parse(textwrap.dedent("".join(lines)))
        module = ast.parse(Path(path).read_text(encoding="utf-8"))
    except (OSError, SyntaxError, UnicodeDecodeError, ValueError) as exc:
        return f"source could not be parsed: {exc}"

    assignments = {}
    for statement in module.body:
        if isinstance(statement, ast.Assign) and len(statement.targets) == 1 \
                and isinstance(statement.targets[0], ast.Name):
            assignments[statement.targets[0].id] = statement
        elif isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name) \
                and statement.value is not None:
            assignments[statement.target.id] = statement

    used, seen = [], set()
    names = [n.id for n in ast.walk(node) if isinstance(n, ast.Name)]
    while names:  # module constants, and the constants they name in turn
        name = names.pop()
        if name in seen or name not in assignments:
            continue
        seen.add(name)
        used.append(assignments[name])
        names.extend(n.id for n in ast.walk(assignments[name].value) if isinstance(n, ast.Name))
    used.sort(key=lambda statement: statement.lineno)  # in source order
    return node, used, f"{Path(path).name}:{first} {function.__name__}()"


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
