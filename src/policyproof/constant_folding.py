"""Constant expressions in a target's source, folded to amounts (method E).

source_literals collects the numeric literals a target writes out. A special
case whose edges are computed (``_LOW = _BASE + Decimal(37) * CENT``) has no
literal equal to them, so this module folds such expressions to their values
with a small, bounded evaluator over the syntax tree.

Nothing from the target is executed: the source text is parsed with ``ast``,
and no target code is imported, called, ``eval``-ed or ``exec``-ed here. The
evaluator knows only:

  - int, float and string literals (strings only as ``Decimal`` arguments);
  - ``Decimal(x)`` when ``Decimal`` is bound by ``from decimal import Decimal``
    (or ``import decimal`` / ``decimal.Decimal``) and by nothing else;
  - ``+ - * / // %``, unary ``-`` and ``+``, and ``**`` with a small integer
    exponent, applied with Python's own type rules (``Decimal + float`` is
    unsupported, as it would raise when the target runs), in a decimal
    context equal to Python's default;
  - names bound exactly once at module level, or exactly once in the
    function and not a parameter.

Everything else is unsupported and reported, never guessed: other calls,
attributes, names bound more than once (ambiguous), names rebound through
``global`` or augmented assignment, cycles, imported names, values out of
bounds. A module that changes the decimal context at import is not modelled.

The folded amounts are probes, exactly like source literals: a probe becomes
evidence only through the target's and the reference's actual decisions.
"""

import ast
import decimal
import inspect
import operator
import re
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

CENT = Decimal("0.01")
MAX_FOLDED_AMOUNTS = 100
MAX_UNSUPPORTED = 50
MAX_DEPTH = 40
MAX_MAGNITUDE = Decimal(10) ** 15
MAX_EXPONENT = 12
_DECIMAL_TEXT = re.compile(r"\s*[+-]?(\d+(\.\d*)?|\.\d+)\s*")
_BINARY = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
           ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod,
           ast.Pow: operator.pow}
_UNARY = {ast.USub: operator.neg, ast.UAdd: operator.pos}


def _context() -> decimal.Context:
    """Python's default decimal context, independent of the caller's."""
    return decimal.Context(prec=28, rounding=decimal.ROUND_HALF_EVEN, Emin=-999999,
                           Emax=999999, capitals=1, clamp=0, flags=[],
                           traps=[decimal.InvalidOperation, decimal.DivisionByZero,
                                  decimal.Overflow])


@dataclass(frozen=True)
class FoldedConstants:
    amounts: tuple[Decimal, ...]
    # amount (as text) -> the expressions that fold to it, "line N: source"
    derivations: dict[str, tuple[str, ...]]
    # "line N: <expression or name>: <reason>", for every expression that
    # could have been a constant but was not folded
    unsupported: tuple[str, ...]
    source: str | None
    unavailable: str | None = None


class Unsupported(Exception):
    def __init__(self, reason: str, runtime: bool = False):
        super().__init__(reason)
        self.reason, self.runtime = reason, runtime


def fold_constants(function: Callable, low: Decimal, high: Decimal) -> FoldedConstants:
    """Fold the constant expressions ``function``'s source uses. Reads the
    source file; never runs the function or its module's code."""
    try:
        path = inspect.getsourcefile(function)
        _, first = inspect.getsourcelines(function)
    except (TypeError, OSError) as exc:
        return FoldedConstants((), {}, (), None, f"source not available: {exc}")
    name = getattr(function, "__name__", "<lambda>")
    if path is None or name == "<lambda>":
        return FoldedConstants((), {}, (), None, "source not available: not a named function")
    try:
        text = Path(path).read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError) as exc:
        return FoldedConstants((), {}, (), None, f"source could not be read: {exc}")
    return fold_source(text, name, low, high, first_line=first,
                       where=f"{Path(path).name}:{first} {name}()")


def fold_source(text: str, function_name: str, low: Decimal, high: Decimal, *,
                first_line: int | None = None, where: str | None = None) -> FoldedConstants:
    """Fold the constant expressions in module source ``text`` that the
    function ``function_name`` (starting at ``first_line``, if given) uses."""
    where = where or f"{function_name}()"
    try:
        module = ast.parse(text)
    except (SyntaxError, ValueError) as exc:
        return FoldedConstants((), {}, (), None, f"source could not be parsed: {exc}")
    function = _find_function(module, function_name, first_line)
    if function is None:
        return FoldedConstants((), {}, (), None, f"function {function_name!r} not found in source")
    return _Folder(module, function).run(low, high, where)


def _find_function(module: ast.Module, name: str, first_line: int | None):
    for node in ast.walk(module):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            starts = {node.lineno, *(d.lineno for d in node.decorator_list)}
            if first_line is None or first_line in starts:
                return node
    return None


def _bound_names(target: ast.AST) -> list[str]:
    return [n.id for n in ast.walk(target) if isinstance(n, ast.Name)]


class _Folder:
    def __init__(self, module: ast.Module, function: ast.FunctionDef | ast.AsyncFunctionDef):
        self.function = function
        self.module_bindings: dict[str, list[ast.AST]] = {}
        self.decimal_names: set[str] = set()   # names bound to decimal.Decimal
        self.decimal_modules: set[str] = set()  # names bound to the decimal module
        self.imported: set[str] = set()
        rebound_globally: set[str] = set()
        for node in ast.walk(module):
            if isinstance(node, ast.Global):
                rebound_globally.update(node.names)
        for statement in module.body:
            self._record_module_binding(statement)
        for name in rebound_globally:
            self.module_bindings.setdefault(name, []).append(None)  # never a constant

        args = function.args
        self.parameters = {a.arg for a in (*args.posonlyargs, *args.args, *args.kwonlyargs,
                                           *([args.vararg] if args.vararg else []),
                                           *([args.kwarg] if args.kwarg else []))}
        self.local_bindings: dict[str, list[ast.AST | None]] = {}
        for node in ast.walk(function):
            if node is function:
                continue
            if isinstance(node, ast.Assign):
                single = len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)
                for target in node.targets:
                    for name in _bound_names(target):
                        self.local_bindings.setdefault(name, []).append(node.value if single else None)
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                self.local_bindings.setdefault(node.target.id, []).append(node.value)
            elif isinstance(node, (ast.AugAssign, ast.For, ast.AsyncFor, ast.With, ast.AsyncWith,
                                   ast.NamedExpr, ast.comprehension, ast.ExceptHandler,
                                   ast.Import, ast.ImportFrom, ast.FunctionDef,
                                   ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
                for name in self._other_bindings(node):
                    self.local_bindings.setdefault(name, []).append(None)
        self.cache: dict[tuple[str, str], object] = {}
        self.resolving: list[tuple[str, str]] = []

    # -- binding tables -------------------------------------------------
    def _record_module_binding(self, statement: ast.stmt) -> None:
        b = self.module_bindings
        if isinstance(statement, ast.Assign):
            single = len(statement.targets) == 1 and isinstance(statement.targets[0], ast.Name)
            for target in statement.targets:
                for name in _bound_names(target):
                    b.setdefault(name, []).append(statement.value if single else None)
        elif isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name):
            b.setdefault(statement.target.id, []).append(statement.value)
        elif isinstance(statement, ast.ImportFrom):
            for alias in statement.names:
                bound = alias.asname or alias.name
                b.setdefault(bound, []).append(None)
                self.imported.add(bound)
                if alias.name == "Decimal" and statement.module == "decimal" and not statement.level:
                    self.decimal_names.add(bound)
        elif isinstance(statement, ast.Import):
            for alias in statement.names:
                bound = alias.asname or alias.name.split(".")[0]
                b.setdefault(bound, []).append(None)
                self.imported.add(bound)
                if alias.name == "decimal":
                    self.decimal_modules.add(bound)
        else:
            for name in self._other_bindings(statement):
                b.setdefault(name, []).append(None)
            # bindings nested in if/try/for/with blocks at module level
            for child in ast.iter_child_nodes(statement):
                if isinstance(child, ast.stmt):
                    self._record_module_binding(child)
                elif isinstance(child, ast.ExceptHandler):
                    if child.name:
                        b.setdefault(child.name, []).append(None)
                    for inner in child.body:
                        self._record_module_binding(inner)

    @staticmethod
    def _other_bindings(node: ast.AST) -> list[str]:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            return [node.name]
        if isinstance(node, ast.AugAssign):
            return _bound_names(node.target)
        if isinstance(node, (ast.For, ast.AsyncFor, ast.comprehension)):
            return _bound_names(node.target)
        if isinstance(node, (ast.With, ast.AsyncWith)):
            return [n for item in node.items if item.optional_vars is not None
                    for n in _bound_names(item.optional_vars)]
        if isinstance(node, ast.NamedExpr):
            return [node.target.id]
        if isinstance(node, ast.ExceptHandler):
            return [node.name] if node.name else []
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            return [(a.asname or a.name).split(".")[0] for a in node.names]
        return []

    def _is_decimal_constructor(self, func: ast.expr) -> bool:
        if isinstance(func, ast.Name):
            return func.id in self.decimal_names and func.id not in self.local_bindings \
                and len(self.module_bindings.get(func.id, [])) == 1
        if isinstance(func, ast.Attribute) and func.attr == "Decimal" \
                and isinstance(func.value, ast.Name):
            name = func.value.id
            return name in self.decimal_modules and name not in self.local_bindings \
                and len(self.module_bindings.get(name, [])) == 1
        return False

    # -- name resolution ------------------------------------------------
    def resolve(self, name: str, scope: str):
        """The value of ``name`` seen from ``scope`` ("local" or "module")."""
        if scope == "local":
            if name in self.parameters:
                raise Unsupported(f"{name} is a parameter (a runtime value)", runtime=True)
            if name in self.local_bindings:
                return self._resolve_binding(name, "local", self.local_bindings[name])
        if name in self.module_bindings:
            return self._resolve_binding(name, "module", self.module_bindings[name])
        raise Unsupported(f"{name} is not a constant defined in this module")

    def _resolve_binding(self, name: str, scope: str, values: list):
        key = (scope, name)
        if key in self.cache:
            cached = self.cache[key]
            if isinstance(cached, Unsupported):
                raise cached
            return cached
        if len(values) != 1:
            error = Unsupported(f"{name} is bound {len(values)} times (ambiguous)")
        elif values[0] is None and scope == "local":
            error = Unsupported(f"{name} is bound at run time", runtime=True)
        elif values[0] is None and name in self.imported:
            error = Unsupported(f"{name} is imported; other modules are not read")
        elif values[0] is None:
            error = Unsupported(f"{name} is not bound by a plain assignment")
        elif key in self.resolving:
            cycle = " -> ".join(n for _, n in self.resolving[self.resolving.index(key):])
            error = Unsupported(f"cycle: {cycle} -> {name}")
        else:
            self.resolving.append(key)
            try:
                value = self.evaluate(values[0], scope, 0)
            except Unsupported as exc:
                error = Unsupported(f"{name}: {exc.reason}", exc.runtime)
            else:
                self.cache[key] = value
                return value
            finally:
                self.resolving.pop()
        if not error.reason.startswith("cycle"):
            self.cache[key] = error
        raise error

    # -- the bounded evaluator -------------------------------------------
    def evaluate(self, node: ast.AST, scope: str, depth: int):
        if depth > MAX_DEPTH:
            raise Unsupported("expression nested too deeply")
        if isinstance(node, ast.Constant):
            value = node.value
            if isinstance(value, bool) or not isinstance(value, (int, float, str)):
                raise Unsupported(f"literal {value!r} is not a number")
            return self._bounded(value)
        if isinstance(node, ast.Name):
            return self.resolve(node.id, scope)
        if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY:
            return self._bounded(self._apply(_UNARY[type(node.op)],
                                             self._number(node.operand, scope, depth)))
        if isinstance(node, ast.BinOp) and type(node.op) in _BINARY:
            left = self._number(node.left, scope, depth)
            right = self._number(node.right, scope, depth)
            if isinstance(node.op, ast.Pow) and (isinstance(right, bool) or not isinstance(right, int)
                                                 or not 0 <= right <= MAX_EXPONENT):
                raise Unsupported(f"exponent must be an integer from 0 to {MAX_EXPONENT}")
            return self._bounded(self._apply(_BINARY[type(node.op)], left, right))
        if isinstance(node, ast.Call):
            if not self._is_decimal_constructor(node.func):
                raise Unsupported(f"call to {ast.unparse(node.func)} is not evaluated")
            if len(node.args) != 1 or node.keywords:
                raise Unsupported("Decimal() with other than one positional argument")
            argument = self.evaluate(node.args[0], scope, depth + 1)
            if isinstance(argument, str):
                if not _DECIMAL_TEXT.fullmatch(argument):
                    raise Unsupported(f"Decimal({argument!r}) is not a plain decimal number")
                argument = argument.strip()
            return self._bounded(self._apply(Decimal, argument))
        if isinstance(node, ast.Attribute):
            if isinstance(node.value, ast.Name) and node.value.id in self.parameters and scope == "local":
                raise Unsupported(f"{ast.unparse(node)} is a runtime value", runtime=True)
            raise Unsupported(f"attribute {ast.unparse(node)} is not evaluated")
        raise Unsupported(f"{type(node).__name__} expressions are not evaluated")

    def _number(self, node: ast.AST, scope: str, depth: int):
        value = self.evaluate(node, scope, depth + 1)
        if isinstance(value, str):
            raise Unsupported("string used in arithmetic")
        return value

    @staticmethod
    def _apply(function, *args):
        try:
            with decimal.localcontext(_context()):
                return function(*args)
        except (TypeError, ArithmeticError, ValueError) as exc:
            raise Unsupported(f"{type(exc).__name__} when evaluated") from None

    @staticmethod
    def _bounded(value):
        if isinstance(value, str):
            return value
        if isinstance(value, float) and value != value:
            raise Unsupported("not a number")
        try:
            magnitude = abs(Decimal(value)) if not isinstance(value, Decimal) else abs(value)
        except (ValueError, OverflowError, decimal.InvalidOperation):
            raise Unsupported("value cannot be represented") from None
        if not magnitude.is_finite() or magnitude > MAX_MAGNITUDE:
            raise Unsupported(f"value beyond {MAX_MAGNITUDE:,}")
        return value

    # -- candidates -----------------------------------------------------
    def run(self, low: Decimal, high: Decimal, where: str) -> FoldedConstants:
        derivations: dict[Decimal, list[str]] = {}
        unsupported: list[str] = []

        def consider(node: ast.AST, scope: str, label: str | None = None) -> None:
            try:
                value = self.evaluate(node, scope, 0)
            except Unsupported as exc:
                if not exc.runtime:
                    unsupported.append(f"line {node.lineno}: {label or ast.unparse(node)}: {exc.reason}")
                return
            amount = _as_amount(value)
            if amount is not None and low <= amount <= high:
                derivations.setdefault(amount, []).append(
                    f"line {node.lineno}: {label + ' = ' if label else ''}{ast.unparse(node)}")

        # Every constant-shaped expression in the function body ...
        candidates = (ast.BinOp, ast.UnaryOp, ast.Call, ast.Name)
        body = [n for statement in self.function.body for n in ast.walk(statement)]
        called = {id(n.func) for n in body if isinstance(n, ast.Call)}
        objects = {id(n.value) for n in body if isinstance(n, ast.Attribute)}
        seen_names = set()
        for node in body:
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                seen_names.add(node.id)
            if not isinstance(node, candidates) or id(node) in called or id(node) in objects:
                continue  # a called name (len, Decimal, a helper) or an object is not a value
            if isinstance(node, ast.UnaryOp) and type(node.op) not in _UNARY:
                continue  # not, ~: never an amount
            if isinstance(node, ast.Name) and not isinstance(node.ctx, ast.Load):
                continue
            if isinstance(node, ast.Call) and not self._is_decimal_constructor(node.func):
                continue  # other calls in the function run at decision time
            consider(node, "local")
        # ... and in the module constants they depend on, transitively.
        module_seen, queue = set(), [n for n in seen_names
                                     if n not in self.local_bindings and n not in self.parameters]
        for values in self.local_bindings.values():
            for value in values:
                if value is not None:
                    queue += [n.id for n in ast.walk(value) if isinstance(n, ast.Name)]
        while queue:
            name = queue.pop()
            if name in module_seen or name not in self.module_bindings:
                continue
            module_seen.add(name)
            values = self.module_bindings[name]
            if name in self.decimal_names or name in self.decimal_modules:
                continue
            if len(values) == 1 and values[0] is not None:
                for node in ast.walk(values[0]):
                    if isinstance(node, (ast.BinOp, ast.UnaryOp, ast.Call)):
                        consider(node, "module")  # unsupported calls here are reported
                    if isinstance(node, ast.Name):
                        queue.append(node.id)
            elif len(values) != 1:
                unsupported.append(f"{name}: bound {len(values)} times (ambiguous)")
        unique_unsupported = list(dict.fromkeys(unsupported))
        if len(unique_unsupported) > MAX_UNSUPPORTED:
            unique_unsupported = unique_unsupported[:MAX_UNSUPPORTED] + [
                f"{len(unique_unsupported) - MAX_UNSUPPORTED} more not listed"]
        amounts = tuple(sorted(derivations))[:MAX_FOLDED_AMOUNTS]
        return FoldedConstants(
            amounts,
            {str(a): tuple(dict.fromkeys(derivations[a])) for a in amounts},
            tuple(unique_unsupported), where,
        )


def _as_amount(value) -> Decimal | None:
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        return None
    amount = Decimal(repr(value)) if isinstance(value, float) else Decimal(value)
    if not amount.is_finite() or amount < 0 or amount != amount.quantize(CENT, context=_context()):
        return None
    return amount.quantize(CENT, context=_context())
