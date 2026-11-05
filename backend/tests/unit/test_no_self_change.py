"""Spec 010 FR-010, constitution XII: the insight and registry packages have no write path to files
(code, prompts, parsers, configuration). They write only their own database tables.

Spec 011 T095 (FR-020, SC-008): the engine never writes the human-only settings — robots/terms (`access`,
`access_evidence`), the owner's freeze, the deny-list, budgets and the daily cap — except in the admission check
(robots/terms verdicts) and the registry seed (it copies the owner's config files); the admin API lives outside the
engine. Agents run no dynamic code."""

from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).parents[2] / "src" / "automind"
ACQ = ROOT / "acquisition"
PATTERNS = (
    re.compile(r"open\([^)]*['\"][wax]\+?['\"]"),
    re.compile(r"\.write_text\(|\.write_bytes\("),
    re.compile(r"yaml\.(safe_)?dump\([^)]*,\s*\w"),
    re.compile(r"shutil\.(copy|move)|os\.(remove|rename|replace)\("),
    re.compile(r"subprocess|os\.system\("),
)
HUMAN_FIELDS = {"access", "access_evidence", "frozen", "denylist", "budgets"}
HUMAN_ONLY_WRITERS = {
    "registry/application/admission.py",  # robots/terms verdicts of the admission check
    "registry/application/seed.py",  # the seed from the owner's config/sources.yaml and survey
    "registry/infrastructure/repo.py",  # (same seed, persisted)
    "parsing/migrate_v1.py",  # the parser seed inserts new parsers unfrozen (`frozen=False`, never an update)
}
SQL_SET = re.compile(r"\bSET\b[^;]*\b(access|access_evidence|frozen|denylist|budgets)\s*=", re.I | re.S)
DYNAMIC_CALLS = {"exec", "eval", "compile", "__import__"}
DYNAMIC_MODULES = {"importlib", "subprocess"}


def _targets(node: ast.AST) -> list[ast.AST]:
    if isinstance(node, ast.Assign):
        out: list[ast.AST] = []
        for t in node.targets:
            out += list(t.elts) if isinstance(t, ast.Tuple | ast.List) else [t]
        return out
    if isinstance(node, ast.AugAssign | ast.AnnAssign) and node.value is not None:
        return [node.target]
    return []


def _human_target(t: ast.AST) -> bool:
    if isinstance(t, ast.Attribute):
        return t.attr in HUMAN_FIELDS
    if isinstance(t, ast.Name):
        return t.id.upper().startswith("DAILY_CAP")
    if isinstance(t, ast.Subscript) and isinstance(t.slice, ast.Constant):
        return str(t.slice.value) in HUMAN_FIELDS
    return False


def human_only_writes(source: str) -> list[int]:
    """Line numbers that assign, UPDATE … SET or `.values()`/`.update()` a human-only setting."""
    hits = []
    for node in ast.walk(ast.parse(source)):
        if any(_human_target(t) for t in _targets(node)):
            hits.append(node.lineno)
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in (
            "values", "update"
        ):  # fmt: skip
            if any(k.arg in HUMAN_FIELDS for k in node.keywords):
                hits.append(node.lineno)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and SQL_SET.search(node.value):
            hits.append(node.lineno)
    return hits


def dynamic_code(source: str) -> list[int]:
    hits = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            names = [node.func.id]
        elif isinstance(node, ast.Import):
            names = [a.name.split(".")[0] for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [(node.module or "").split(".")[0]]
        else:
            continue
        if set(names) & (DYNAMIC_CALLS if isinstance(node, ast.Call) else DYNAMIC_MODULES):
            hits.append(node.lineno)
    return hits


def test_engine_never_writes_human_only_settings():
    hits = []
    for f in ACQ.rglob("*.py"):
        rel = str(f.relative_to(ACQ))
        if rel in HUMAN_ONLY_WRITERS:
            continue
        lines = f.read_text(encoding="utf-8").splitlines()
        hits += [f"acquisition/{rel}:{n}: {lines[n - 1].strip()}" for n in human_only_writes("\n".join(lines))]
    assert not hits, "only admission and the seed may write robots/terms, freeze, deny-list or budgets:\n" + "\n".join(
        hits
    )


def test_agents_run_no_dynamic_code():
    hits = []
    for f in (ACQ / "agents").rglob("*.py"):
        hits += [f"{f.relative_to(ROOT)}:{n}" for n in dynamic_code(f.read_text(encoding="utf-8"))]
    assert not hits, "agents output data, never code:\n" + "\n".join(hits)


def test_the_scans_catch_what_they_should():
    bad = [
        "row.access = 'ok'",
        "src.frozen = False",
        "row.access, row.access_evidence = a, b",
        "q = text(\"UPDATE sources SET access = 'ok' WHERE domain = :d\")",
        "stmt = update(SourceRow).values(frozen=False)",
        "cfg['budgets'] = {}",
        "DAILY_CAP_EUR = 9",
        "cfg['denylist'] += ['x']",
    ]
    good = ["if src.access == 'ok':\n    pass", "q = q.where(SourceRow.frozen.is_(False))", "x = row.access",
            "@dataclass(frozen=True)\nclass A:\n    pass", "Source(domain=d, access=a)",
            "q = text(\"SELECT domain FROM sources WHERE access = 'ok'\")"]  # fmt: skip
    assert [b for b in bad if not human_only_writes(b)] == []
    assert [g for g in good if human_only_writes(g)] == []
    for b in ("exec(spec)", "eval('1')", "import importlib", "from subprocess import run", "compile(s, 'f', 'exec')"):
        assert dynamic_code(b), b
    assert not dynamic_code("import re\nP = re.compile('x')")


def test_no_file_writes_in_self_observing_packages():
    hits = []
    for pkg in ("insight", "acquisition"):
        for f in (ROOT / pkg).rglob("*.py"):
            for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
                if any(p.search(line) for p in PATTERNS):
                    hits.append(f"{f.relative_to(ROOT)}:{n}: {line.strip()}")
    assert not hits, "self-observing code must not write files:\n" + "\n".join(hits)
