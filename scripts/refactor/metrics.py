#!/usr/bin/env python3
"""Measurements of the code's shape before and after spec 012 (research R11, review I9).

    metrics.py [--coverage FILE] [--out FILE]

Prints (or writes) a Markdown table: source and test lines, modules over 400 lines, `type: ignore`, `# fmt: skip`,
import-linter contracts and `ignore_imports` lines, regexes inside functions, structure violations per rule, and
branch coverage of the watched modules when a coverage JSON (`pytest --cov --cov-report=json`) is given.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "backend/src/automind"
TESTS = REPO / "backend/tests"
WATCHED = ("application/compose.py", "application/identify.py", "application/resolve.py",
           "application/interpret.py", "orchestration/nodes/compute.py", "orchestration/nodes/understand.py",
           "orchestration/nodes/confirm.py", "domain/policy.py", "domain/intake.py",
           "acquisition/pipeline/job.py")  # fmt: skip


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--coverage", type=Path, help="coverage.json of a full pytest run with --cov-branch")
    ap.add_argument("--out", type=Path)
    a = ap.parse_args(argv)
    text = render(measure(a.coverage))
    if a.out:
        a.out.write_text(text, encoding="utf-8")
    else:
        print(text)
    return 0


def measure(coverage: Path | None) -> dict[str, object]:
    src = [p for p in SRC.rglob("*.py") if "__pycache__" not in p.parts]
    tests = [p for p in TESTS.rglob("*.py") if "__pycache__" not in p.parts]
    texts = {p: p.read_text(encoding="utf-8") for p in src}
    lines = {p: t.count("\n") for p, t in texts.items()}
    importlinter = (REPO / "backend/.importlinter").read_text(encoding="utf-8")
    out: dict[str, object] = {
        "commit": _git("rev-parse", "--short", "HEAD"),
        "source modules": len(src),
        "source lines": sum(lines.values()),
        "test lines": sum(p.read_text(encoding="utf-8").count("\n") for p in tests),
        "modules > 400 lines": sum(n > 400 for n in lines.values()),
        "largest modules": ", ".join(f"{p.relative_to(SRC)} {n}" for p, n in sorted(lines.items(), key=lambda x: -x[1])[:5]),
        "`type: ignore`": sum(t.count("type: ignore") for t in texts.values()),
        "`# fmt: skip`": sum(t.count("# fmt: skip") for t in texts.values()),
        "import contracts": len(re.findall(r"^\[importlinter:contract:", importlinter, re.M)),
        "`ignore_imports` lines": _ignore_lines(importlinter),
        "structure violations": _structure(),
    }
    if coverage:
        out["branch coverage (watched)"] = _coverage(coverage)
    return out


def render(m: dict[str, object]) -> str:
    rows = "\n".join(f"| {k} | {v} |" for k, v in m.items() if not isinstance(v, dict))
    out = f"# Metrics ({date.today().isoformat()}, commit {m['commit']})\n\n| Measure | Value |\n|---|---|\n{rows}\n"
    for k, v in m.items():
        if isinstance(v, dict):
            out += f"\n## {k}\n\n| | |\n|---|---|\n" + "\n".join(f"| {a} | {b} |" for a, b in v.items()) + "\n"
    return out


def _ignore_lines(importlinter: str) -> int:
    n, inside = 0, False
    for line in importlinter.splitlines():
        if line.startswith("ignore_imports"):
            inside = True
            continue
        if inside and (line.startswith("    ") and "->" in line):
            n += 1
        elif inside and line and not line.startswith(("    ", "#")):
            inside = False
    return n


def _structure() -> dict[str, int]:
    r = subprocess.run([sys.executable, str(REPO / "scripts/check_structure.py"), "--report"], capture_output=True,
                       text=True, cwd=REPO)  # fmt: skip
    line = next((ln for ln in r.stdout.splitlines() if ln.startswith("per rule: ")), "")
    return {k: int(v) for k, v in (p.rsplit(" ", 1) for p in line.removeprefix("per rule: ").split(", ") if p)}


def _coverage(path: Path) -> dict[str, str]:
    files = json.loads(path.read_text(encoding="utf-8"))["files"]
    out = {}
    for rel in WATCHED:
        f = next((v for k, v in files.items() if k.endswith(rel)), None)
        if f is None:
            out[rel] = "not measured"
            continue
        s = f["summary"]
        br = s.get("num_branches") or 0
        pct = 100.0 * (s.get("covered_branches") or 0) / br if br else 100.0
        out[rel] = f"lines {s['percent_covered_display']} %, branches {pct:.0f} % ({s.get('covered_branches')}/{br})"
    return out


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True, cwd=REPO).stdout.strip()


if __name__ == "__main__":
    sys.exit(main())
