#!/usr/bin/env python3
"""Structure checker of spec 012 (research R6, contracts/code-shape.md): the shape rules import-linter cannot see.

Rules (id: what fails):
  size      a module over 400 lines
  pkgdoc    a package `__init__.py` without a docstring or without `__all__`
  order     a public top-level function/class after the first private one
  regex     a regex compiled or used with a literal pattern inside a function
  table     a word table (a collection of >= 8 string literals) inside a function
  func      a function over 80 lines
  node      a dialog graph node over 30 lines; a use case `run` over 30; a service `run` over 60
  sql       raw SQL naming a table another area owns (scripts/table_owners.yaml), except listed reads

Ratchet: `scripts/structure_baseline.txt` lists today's violations. A violation not in the baseline fails; a
baseline entry that no longer occurs fails too (remove it in the same PR). Justified exceptions (data modules,
a limit raised with a reason) live in `scripts/structure_exceptions.txt`: `rule|path|reason`.

Usage: check_structure.py [--report] [--write-baseline] [--root DIR]
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
SRC = Path("backend/src/automind")
BASELINE = Path("scripts/structure_baseline.txt")
EXCEPTIONS = Path("scripts/structure_exceptions.txt")
OWNERS = Path("scripts/table_owners.yaml")

MODULE_MAX = 400
FUNC_MAX = 80
NODE_MAX = 30
USECASE_RUN_MAX = 30
SERVICE_RUN_MAX = 60
TABLE_MIN_STRINGS = 8
AREAS = ("chat", "acquisition", "observability", "shared", "delivery")
# Before the tree move (S3a) the area of a module comes from its old top-level package.
LEGACY_AREAS = {"acquisition": "acquisition", "insight": "observability", "domain": "chat", "application": "chat",
                "orchestration": "chat", "api": "delivery", "infrastructure": "shared"}  # fmt: skip
NODE_DIRS = ("orchestration/nodes", "chat/dialog/nodes")
REGEX_FUNCS = {"compile", "match", "search", "fullmatch", "findall", "finditer", "sub", "subn", "split"}
SQL_TABLE = re.compile(r"\b(?:from|join|into|update|table)\s+\"?([a-z_][a-z0-9_]*)", re.I)
SQL_HINT = re.compile(r"\b(select|insert|update|delete)\b.*\b(from|into|set|where)\b", re.I | re.S)


@dataclass(frozen=True, order=True)
class Violation:
    rule: str
    path: str  # relative to the source root, e.g. "domain/intake.py"
    detail: str  # stable across line shifts: a symbol name or a number class, never a line number

    def key(self) -> str:
        return f"{self.rule}|{self.path}|{self.detail}"


def check(src_root: Path, owners_file: Path) -> list[Violation]:
    owners, reads = _load_owners(owners_file)
    out: list[Violation] = []
    for path in sorted(src_root.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        rel = path.relative_to(src_root).as_posix()
        text = path.read_text(encoding="utf-8")
        tree = ast.parse(text)
        out += _size(rel, text)
        out += _pkgdoc(rel, tree)
        out += _order(rel, tree)
        out += _functions(rel, tree)
        out += _sql(rel, tree, owners, reads)
    for pkg in sorted(p for p in src_root.rglob("*") if p.is_dir() and "__pycache__" not in p.parts):
        if any(pkg.glob("*.py")) and not (pkg / "__init__.py").exists():
            out.append(Violation("pkgdoc", pkg.relative_to(src_root).as_posix() + "/__init__.py", "missing"))
    return sorted(set(out))


def area_of(rel: str) -> str:
    top = rel.split("/", 1)[0].removesuffix(".py")
    if top in AREAS:
        return top
    return LEGACY_AREAS.get(top, "delivery" if top == "mcp_server" else "shared")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", type=Path, default=REPO)
    ap.add_argument("--report", action="store_true", help="print every violation and the counts per rule")
    ap.add_argument("--write-baseline", action="store_true", help="write today's violations as the baseline")
    a = ap.parse_args(argv)
    root = a.root
    found = check(root / SRC, root / OWNERS)
    excepted = _exceptions(root / EXCEPTIONS)
    found = [v for v in found if (v.rule, v.path) not in excepted]
    keys = {v.key() for v in found}
    if a.write_baseline:
        (root / BASELINE).write_text(_baseline_text(sorted(keys)), encoding="utf-8")
        print(f"baseline written: {len(keys)} entries")
        return 0
    base = _read_lines(root / BASELINE)
    new = sorted(keys - base)
    fixed = sorted(base - keys)
    if a.report:
        _print_report(found)
    for k in new:
        print(f"NEW   {k}")
    for k in fixed:
        print(f"FIXED {k}  (remove it from {BASELINE})")
    print(f"structure: {len(keys)} violations, baseline {len(base)}, new {len(new)}, fixed-but-listed {len(fixed)}")
    return 1 if new or fixed else 0


# --- rules -------------------------------------------------------------------------------------------------------


def _size(rel: str, text: str) -> list[Violation]:
    n = text.count("\n") + (0 if text.endswith("\n") or not text else 1)
    return [Violation("size", rel, f">{MODULE_MAX}")] if n > MODULE_MAX else []


def _pkgdoc(rel: str, tree: ast.Module) -> list[Violation]:
    if not rel.endswith("__init__.py"):
        return []
    out = []
    if not ast.get_docstring(tree):
        out.append(Violation("pkgdoc", rel, "docstring"))
    if not any(isinstance(n, ast.Assign | ast.AnnAssign) and "__all__" in _target_names(n) for n in tree.body):
        out.append(Violation("pkgdoc", rel, "__all__"))
    return out


def _order(rel: str, tree: ast.Module) -> list[Violation]:
    seen_private = False
    out = []
    for n in tree.body:
        if not isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            continue
        if n.name.startswith("__") and n.name.endswith("__"):
            continue  # module dunders (__getattr__, __dir__) are neither public API nor helpers
        private = n.name.startswith("_")
        if private:
            seen_private = True
        elif seen_private:
            out.append(Violation("order", rel, n.name))
    return out


def _functions(rel: str, tree: ast.Module) -> list[Violation]:
    out = []
    in_nodes = any(rel.startswith(d + "/") for d in NODE_DIRS)
    is_usecase = rel.startswith("chat/application/usecases/")
    is_service = "/application/services/" in rel and rel.endswith("/service.py")
    for fn, qual, depth in _walk_functions(tree):
        length = (fn.end_lineno or fn.lineno) - fn.lineno + 1
        if length > FUNC_MAX:
            out.append(Violation("func", rel, qual))
        if in_nodes and depth == 0 and not fn.name.startswith("_") and length > NODE_MAX:
            out.append(Violation("node", rel, qual))
        if is_usecase and fn.name == "run" and length > USECASE_RUN_MAX:
            out.append(Violation("node", rel, qual))
        if is_service and fn.name == "run" and length > SERVICE_RUN_MAX:
            out.append(Violation("node", rel, qual))
        out += _inside(rel, qual, fn)
    return out


def _inside(rel: str, qual: str, fn: ast.FunctionDef | ast.AsyncFunctionDef) -> list[Violation]:
    out = []
    for n in _own_nodes(fn):
        if isinstance(n, ast.Call) and _is_regex_call(n):
            out.append(Violation("regex", rel, qual))
        elif isinstance(n, ast.List | ast.Tuple | ast.Set | ast.Dict):
            items = n.keys if isinstance(n, ast.Dict) else n.elts
            strings = sum(isinstance(x, ast.Constant) and isinstance(x.value, str) for x in items)
            if strings >= TABLE_MIN_STRINGS:
                out.append(Violation("table", rel, qual))
    return out


def _sql(rel: str, tree: ast.Module, owners: dict[str, str], reads: dict[str, set[str]]) -> list[Violation]:
    area = area_of(rel)
    out = set()
    for n in ast.walk(tree):
        if not (isinstance(n, ast.Constant) and isinstance(n.value, str) and SQL_HINT.search(n.value)):
            continue
        for table in SQL_TABLE.findall(n.value):
            owner = owners.get(table.lower())
            allowed = reads.get(area, set())
            if owner and owner not in (area, "shared") and "*" not in allowed and table.lower() not in allowed:
                out.add(Violation("sql", rel, f"{table.lower()}@{owner}"))
    return sorted(out)


# --- helpers -----------------------------------------------------------------------------------------------------


def _walk_functions(
    tree: ast.AST, prefix: str = "", depth: int = 0
) -> Iterator[tuple[ast.FunctionDef | ast.AsyncFunctionDef, str, int]]:
    for n in ast.iter_child_nodes(tree):
        if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef):
            qual = f"{prefix}{n.name}"
            yield n, qual, depth
            yield from _walk_functions(n, qual + ".", depth + 1)
        elif isinstance(n, ast.ClassDef):
            yield from _walk_functions(n, f"{prefix}{n.name}.", depth + 1)


def _own_nodes(fn: ast.AST) -> Iterator[ast.AST]:
    """Nodes of a function body, not descending into nested functions (they are checked on their own)."""
    stack = list(ast.iter_child_nodes(fn))
    while stack:
        n = stack.pop()
        if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda):
            continue
        yield n
        stack.extend(ast.iter_child_nodes(n))


def _is_regex_call(n: ast.Call) -> bool:
    f = n.func
    named = isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) and f.value.id == "re"
    if not (named and f.attr in REGEX_FUNCS):
        return False
    return bool(n.args) and isinstance(n.args[0], ast.Constant | ast.JoinedStr)


def _target_names(n: ast.Assign | ast.AnnAssign) -> set[str]:
    targets = n.targets if isinstance(n, ast.Assign) else [n.target]
    return {t.id for t in targets if isinstance(t, ast.Name)}


def _load_owners(path: Path) -> tuple[dict[str, str], dict[str, set[str]]]:
    if not path.exists():
        return {}, {}
    d = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    owners = {t: area for area, tables in (d.get("owners") or {}).items() for t in tables or []}
    reads = {area: set(tables or []) for area, tables in (d.get("reads") or {}).items()}
    return owners, reads


def _exceptions(path: Path) -> set[tuple[str, str]]:
    out = set()
    for line in _read_lines(path):
        rule, _, rest = line.partition("|")
        out.add((rule, rest.partition("|")[0]))
    return out


def _read_lines(path: Path) -> set[str]:
    if not path.exists():
        return set()
    return {ln.strip() for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip() and not ln.startswith("#")}


def _baseline_text(keys: list[str]) -> str:
    head = "# Structure violations accepted on the way (spec 012). Only shrinks: rule|path|detail\n"
    return head + "".join(k + "\n" for k in keys)


def _print_report(found: list[Violation]) -> None:
    by_rule: dict[str, int] = {}
    for v in found:
        by_rule[v.rule] = by_rule.get(v.rule, 0) + 1
        print(v.key())
    print("per rule: " + ", ".join(f"{r} {c}" for r, c in sorted(by_rule.items())))


if __name__ == "__main__":
    sys.exit(main())
