"""API rules of spec 012 (contracts/code-shape.md "Public API of a layer"): what a public callable of the application
and domain layers promises, and the escape hatches that hide a broken promise. Learnt from the antipattern
`chat/application/usecases/challenge.py` (owner, 2026-11-07): `Any` where the types matter, a dict for a result, the
database used directly, one long public function, no docstring on it.

Rules (id: what fails), for modules under an `application/` or `domain/` package unless said otherwise:
  any       a public callable whose parameter or return annotation holds `Any` (`dict[str, Any]` included)
  untyped   a public callable with a parameter or the return not annotated
  doc       a public function, class or method without a docstring
  public    a public function or method over 40 lines (the target of every function is <= 50, a public one
            reads as a list of named steps)
  ignore    a `# type: ignore` (any layer); the detail is the enclosing callable
  lazy      an import inside a function (any layer): a hidden dependency the import contracts cannot see
  exempt    an `ignore_imports` line of backend/.importlinter: a layer contract switched off for one module
  storage   (any module outside an `infrastructure/` package, owner 2026-11-07: SQL inside
            acquisition/reputation/baseline.py) an import of sqlalchemy or of the shared database package: storage is
            reached through a port whose implementation lives in infrastructure; the detail is what is imported.
            Composition roots that only wire the database (STORAGE_ROOTS) are allowed.

Public = no part of the qualified name starts with "_" (dunders other than `__init__` are not API; `__init__`
counts for typing). Nested functions are not API.
"""

from __future__ import annotations

import ast
import io
import tokenize
from collections.abc import Iterator
from pathlib import Path

PUBLIC_MAX = 40
LAYER_DIRS = ("/application/", "/domain/")
IMPORTLINTER = Path("backend/.importlinter")
Callable_ = ast.FunctionDef | ast.AsyncFunctionDef
STORAGE_MODULES = ("sqlalchemy", "automind.shared.infrastructure.db")
STORAGE_ROOTS = {  # composition roots: they create or migrate the database and wire the stores, nothing else
    "delivery/web/app.py": "the app's startup: init_db and the stores wired",
    "delivery/cli/main.py": "the `migrate` command runs the migrations",
}


def in_layer(rel: str) -> bool:
    return any(d in "/" + rel for d in LAYER_DIRS)


def api_rules(rel: str, text: str, tree: ast.Module) -> list[tuple[str, str]]:
    """(rule, detail) pairs of one module."""
    out = _ignores(text, tree) + _lazy(tree) + _storage(rel, tree)
    if not in_layer(rel):
        return out
    for node, qual, owner in _api(tree):
        if isinstance(node, ast.ClassDef):
            if ast.get_docstring(node) is None:
                out.append(("doc", qual))
            continue
        name = node.name
        dunder = name.startswith("__") and name.endswith("__")
        if not dunder and ast.get_docstring(node) is None and not _is_overload(node):
            out.append(("doc", qual))
        if not dunder and (node.end_lineno or node.lineno) - node.lineno + 1 > PUBLIC_MAX:
            out.append(("public", qual))
        if dunder and name != "__init__":
            continue
        params = _params(node, owner)
        if any(p.annotation is None for p in params) or (node.returns is None and name != "__init__"):
            out.append(("untyped", qual))
        annotations = [p.annotation for p in params if p.annotation is not None] + [node.returns]
        if any(a is not None and _has_any(a) for a in annotations):
            out.append(("any", qual))
    return out


def exempt_rules(root: Path) -> list[str]:
    """Every `ignore_imports` line of the import contracts, as `contract:importer -> imported`."""
    path = root / IMPORTLINTER
    if not path.exists():
        return []
    out, contract, collecting = [], "", False
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line.startswith("[importlinter:contract:"):
            contract, collecting = line.removeprefix("[importlinter:contract:").rstrip("]"), False
        elif line.startswith("ignore_imports"):
            collecting = True
        elif collecting and "->" in line and not line.startswith("#"):
            out.append(f"{contract}:{line}")
        elif collecting and line and not line.startswith("#") and not raw[:1].isspace():
            collecting = False
    return out


# --- helpers -----------------------------------------------------------------------------------------------------


def _api(tree: ast.Module) -> Iterator[tuple[ast.ClassDef | Callable_, str, ast.ClassDef | None]]:
    """Public module-level functions and classes, and the methods of public classes."""
    for n in tree.body:
        if isinstance(n, Callable_) and not n.name.startswith("_"):
            yield n, n.name, None
        elif isinstance(n, ast.ClassDef) and not n.name.startswith("_"):
            yield n, n.name, None
            for m in n.body:
                if isinstance(m, Callable_) and (not m.name.startswith("_") or m.name.startswith("__")):
                    yield m, f"{n.name}.{m.name}", n


def _params(fn: Callable_, owner: ast.ClassDef | None) -> list[ast.arg]:
    a = fn.args
    params = [*a.posonlyargs, *a.args, *a.kwonlyargs, *(x for x in (a.vararg, a.kwarg) if x is not None)]
    static = any(isinstance(d, ast.Name) and d.id == "staticmethod" for d in fn.decorator_list)
    if owner is not None and not static and params and params[0].arg in ("self", "cls"):
        params = params[1:]
    return params


def _has_any(annotation: ast.expr) -> bool:
    return any(
        (isinstance(n, ast.Name) and n.id == "Any") or (isinstance(n, ast.Attribute) and n.attr == "Any")
        or (isinstance(n, ast.Constant) and isinstance(n.value, str) and "Any" in n.value)
        for n in ast.walk(annotation)
    )  # fmt: skip


def _is_overload(fn: Callable_) -> bool:
    return any(isinstance(d, ast.Name) and d.id == "overload" for d in fn.decorator_list)


def _ignores(text: str, tree: ast.Module) -> list[tuple[str, str]]:
    lines = [
        t.start[0]
        for t in tokenize.generate_tokens(io.StringIO(text).readline)
        if t.type == tokenize.COMMENT and "type: ignore" in t.string
    ]
    spans = [(n.lineno, n.end_lineno or n.lineno, q) for n, q in _all_callables(tree)]
    out = set()
    for ln in lines:
        inner = [s for s in spans if s[0] <= ln <= s[1]]
        out.add(("ignore", max(inner, key=lambda s: s[0])[2] if inner else "<module>"))
    return sorted(out)


def _storage(rel: str, tree: ast.Module) -> list[tuple[str, str]]:
    """Imports of the database outside infrastructure (rule `storage`), one entry per imported storage module."""
    if "/infrastructure/" in "/" + rel or rel in STORAGE_ROOTS:
        return []
    out = set()
    for n in ast.walk(tree):
        names: list[str] = []
        if isinstance(n, ast.Import):
            names = [a.name for a in n.names]
        elif isinstance(n, ast.ImportFrom) and n.module:
            names = [n.module] + [f"{n.module}.{a.name}" for a in n.names]
        for name in names:
            hit = next((m for m in STORAGE_MODULES if name == m or name.startswith(m + ".")), None)
            if hit is not None:
                out.add(("storage", hit))
    return sorted(out)


def _lazy(tree: ast.Module) -> list[tuple[str, str]]:
    out = set()
    for fn, qual in _all_callables(tree):
        for n in ast.walk(fn):
            if isinstance(n, ast.Import | ast.ImportFrom):
                out.add(("lazy", qual))
    return sorted(out)


def _all_callables(tree: ast.AST, prefix: str = "") -> Iterator[tuple[Callable_, str]]:
    for n in ast.iter_child_nodes(tree):
        if isinstance(n, Callable_):
            yield n, prefix + n.name
            yield from _all_callables(n, f"{prefix}{n.name}.")
        elif isinstance(n, ast.ClassDef):
            yield from _all_callables(n, f"{prefix}{n.name}.")
