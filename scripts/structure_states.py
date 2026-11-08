"""State rules of spec 012 (owner, 2026-11-08: `chat/dialog/runner.py`): decisions taken by comparing words instead
of named states. Learnt from the runner: turn statuses compared as strings ("RUNNING", "WAITING_CONFIRMATION"), a
button's kind tested with `kind in ("rescore", "car_edit")`, a provider failure recognised by substrings of the
exception's text ("503", "overloaded"), and a port method found with `getattr(store, "spent_today", None)`.

Rules (id: what fails), every module of the source tree:
  word      a state-like value compared with a string literal: `x.status == "DONE"`, `kind in ("a", "b")`,
            `msg.get("type") == "hello"`, `match kind: case "a"`. State-like = the compared name (attribute, variable,
            `.get("…")` or `["…"]` key) ends in one of STATE_WORDS. The fix: a `StrEnum` (or `Literal` alias with
            its members as constants) owned by the area, compared by member; a `StrEnum` equals its string, so the
            database, the checkpoints and the events keep their values. Detail: `<callable>:<name>` (one entry per
            name per callable).
  errtext   an exception recognised by its text: a substring test (`in`, `startswith`, `endswith`) on `str(e)`,
            `repr(e)`, an f-string or `.args` of a caught exception or of a value derived from one. The fix: catch
            or classify by type (the SDK's exception classes, a named error of a port); a text fallback, where a
            provider gives nothing else, lives in one named table of one classifier. Detail: `<callable>`.
  duck      `getattr(x, "name", default)` or `hasattr(x, "name")`: a capability hidden from the types. The fix:
            declare it on the port / record (Optional member, Protocol). Detail: `<callable>:<name>`.
"""

from __future__ import annotations

import ast
import re
from collections.abc import Iterator

STATE_WORDS = ("status", "state", "kind", "type", "action", "role", "relation", "phase", "stage", "mode",
               "verdict", "outcome", "route", "choice", "decision", "step", "event")  # fmt: skip
_STATE_NAME = re.compile(rf"(?:^|_)(?:{'|'.join(STATE_WORDS)})s?_?$", re.I)
_TEXT_TESTS = {"startswith", "endswith", "find", "index", "count"}
Callable_ = ast.FunctionDef | ast.AsyncFunctionDef


def state_rules(tree: ast.Module) -> list[tuple[str, str]]:
    """(rule, detail) of every word, errtext and duck violation of a module."""
    out: set[tuple[str, str]] = set()
    for scope, qual in _scopes(tree):
        out |= {("word", f"{qual}:{name}") for name in _word_checks(scope)}
        out |= {("duck", f"{qual}:{name}") for name in _duck(scope)}
        if isinstance(scope, Callable_) and _error_text(scope):
            out.add(("errtext", qual))
    return sorted(out)


def _scopes(tree: ast.Module) -> Iterator[tuple[ast.AST, str]]:
    """The module body (`<module>`) and every function with its qualified name; a nested function is its own scope."""
    yield tree, "<module>"
    yield from _functions(tree, "")


def _functions(node: ast.AST, prefix: str) -> Iterator[tuple[Callable_, str]]:
    for child in ast.iter_child_nodes(node):
        if isinstance(child, ast.ClassDef):
            yield from _functions(child, f"{prefix}{child.name}.")
        elif isinstance(child, Callable_):
            qual = f"{prefix}{child.name}"
            yield child, qual
            yield from _functions(child, f"{qual}.")


def _own(scope: ast.AST) -> Iterator[ast.AST]:
    """The nodes of a scope without those of nested functions and classes."""
    stack = list(ast.iter_child_nodes(scope))
    while stack:
        n = stack.pop()
        yield n
        if not isinstance(n, Callable_ | ast.ClassDef | ast.Lambda):
            stack.extend(ast.iter_child_nodes(n))


# --- word ----------------------------------------------------------------------------------------------------------


def _word_checks(scope: ast.AST) -> set[str]:
    names: set[str] = set()
    for n in _own(scope):
        if isinstance(n, ast.Compare):
            sides = [n.left, *n.comparators]
            if any(_is_words(s) for s in sides):
                names |= {name for s in sides if (name := _state_name(s))}
        elif isinstance(n, ast.Match) and (name := _state_name(n.subject)):
            if any(_case_has_word(c.pattern) for c in n.cases):
                names.add(name)
    return names


def _is_words(e: ast.expr) -> bool:
    if isinstance(e, ast.Constant):
        return isinstance(e.value, str)
    if isinstance(e, ast.Tuple | ast.List | ast.Set):
        return bool(e.elts) and all(isinstance(x, ast.Constant) and isinstance(x.value, str) for x in e.elts)
    return False


def _state_name(e: ast.expr) -> str | None:
    name = None
    if isinstance(e, ast.Name):
        name = e.id
    elif isinstance(e, ast.Attribute):
        name = e.attr
    elif isinstance(e, ast.Call) and isinstance(e.func, ast.Attribute) and e.func.attr == "get" and e.args:
        name = _literal(e.args[0])
    elif isinstance(e, ast.Subscript):
        name = _literal(e.slice)
    return name if name and _STATE_NAME.search(name) else None


def _case_has_word(p: ast.pattern) -> bool:
    if isinstance(p, ast.MatchValue):
        return isinstance(p.value, ast.Constant) and isinstance(p.value.value, str)
    if isinstance(p, ast.MatchOr):
        return any(_case_has_word(x) for x in p.patterns)
    return False


def _literal(e: ast.expr) -> str | None:
    return e.value if isinstance(e, ast.Constant) and isinstance(e.value, str) else None


# --- duck ----------------------------------------------------------------------------------------------------------


def _duck(scope: ast.AST) -> set[str]:
    names: set[str] = set()
    for n in _own(scope):
        if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Name)) or len(n.args) < 2:
            continue
        attr = _literal(n.args[1])
        if attr and ((n.func.id == "getattr" and len(n.args) == 3) or n.func.id == "hasattr"):
            names.add(attr)
    return names


# --- errtext -------------------------------------------------------------------------------------------------------


def _error_text(fn: Callable_) -> bool:
    """A substring test on the text of a caught exception (or of a parameter typed as one)."""
    errors = {a.arg for a in [*fn.args.args, *fn.args.kwonlyargs] if _is_exception_type(a.annotation)}
    errors |= {n.name for n in _own(fn) if isinstance(n, ast.ExceptHandler) and n.name}
    if not errors:
        return False
    texts: set[str] = set()  # names bound to the text of an error, or to a value made from that text
    changed = True
    while changed:
        changed = False
        for n in _own(fn):
            if isinstance(n, ast.Assign) and _is_text(n.value, errors, texts):
                new = {t.id for t in n.targets if isinstance(t, ast.Name)} - texts
                texts |= new
                changed = changed or bool(new)
    return any(_substring_test(n, errors, texts) for n in _own(fn))


def _substring_test(n: ast.AST, errors: set[str], texts: set[str]) -> bool:
    if isinstance(n, ast.Compare) and any(isinstance(op, ast.In | ast.NotIn) for op in n.ops):
        return any(_is_text(c, errors, texts) for c in n.comparators)
    if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr in _TEXT_TESTS:
        return _is_text(n.func.value, errors, texts)
    return False


def _is_exception_type(annotation: ast.expr | None) -> bool:
    if annotation is None:
        return False
    return any(isinstance(x, ast.Name) and x.id in ("BaseException", "Exception") for x in ast.walk(annotation))


def _is_text(e: ast.expr, errors: set[str], texts: set[str]) -> bool:
    """`str(e)`, `repr(e)`, `f"{e}"`, `e.args`, `e.message` of an error, or a name already holding such a text."""
    return any((isinstance(x, ast.Name) and x.id in texts) or _error_of(_text_source(x)) in errors
               for x in ast.walk(e))  # fmt: skip


def _text_source(x: ast.AST) -> ast.expr | None:
    """The object whose text `x` is: the argument of `str`/`repr`, the value of an f-string field, `.args`."""
    if isinstance(x, ast.Call) and isinstance(x.func, ast.Name) and x.func.id in ("str", "repr") and x.args:
        return x.args[0]
    if isinstance(x, ast.FormattedValue):
        return x.value
    if isinstance(x, ast.Attribute) and x.attr in ("args", "message"):
        return x.value
    return None


def _error_of(e: ast.expr | None) -> str | None:
    return e.id if isinstance(e, ast.Name) else None
