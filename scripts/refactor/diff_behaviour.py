#!/usr/bin/env python3
"""Before/after behaviour diff of a refactoring step (spec 012 research R11). The gate of every step S3a–S13.

    diff_behaviour.py [--base REF] [--head REF] [--keep] [-- pytest args]

Runs the behaviour suites (tests/graph, tests/golden, tests/integration by default) on the base and on the head,
each in its own temporary git worktree, with `behaviour_dump_plugin` writing every test's normalised chat events.
The base runs twice. Tests whose events are equal in both base runs are compared byte for byte; tests that differ
only in order/ids (parallel research interleaving, unordered reads) are compared in a canonical form (ids collapsed,
lists sorted); tests whose canonical content differs even between the two base runs are "racy" (timing decides,
e.g. which jobs a limit pause catches): listed, not gated. Exit 1 on any other difference.

Runs never overlap (one test database). TEST_DATABASE_URL is taken from the environment or .env.docker like
scripts/check.sh does.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PLUGIN_DIR = Path(__file__).resolve().parent
SUITES = ["tests/graph", "tests/golden", "tests/integration"]
KNOWN_RACY = {ln.strip() for ln in (PLUGIN_DIR / "racy_tests.txt").read_text(encoding="utf-8").splitlines()
              if ln.strip() and not ln.startswith("#")}  # fmt: skip


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--base", default="origin/main")
    ap.add_argument("--head", default="HEAD")
    ap.add_argument("--keep", action="store_true", help="keep the worktrees and dumps for inspection")
    ap.add_argument("pytest_args", nargs="*", default=SUITES)
    a = ap.parse_args(argv)
    env = _test_env()
    tmp = Path(tempfile.mkdtemp(prefix="behaviour-"))
    try:
        # base, head, base: the test database accumulates rows run after run, so an effect of that drift shows up as
        # a difference between the two base runs (unstable/racy), never as a false difference of the head
        base1 = _run(a.base, tmp / "base", tmp / "dump-base-1", a.pytest_args, env)
        head = _run(a.head, tmp / "head", tmp / "dump-head", a.pytest_args, env)
        base2 = _run(a.base, tmp / "base", tmp / "dump-base-2", a.pytest_args, env, reuse=True)
        return report(compare(base1, base2, head))
    finally:
        if a.keep:
            print(f"kept: {tmp}")
        else:
            for wt in (tmp / "base", tmp / "head"):
                subprocess.run(["git", "worktree", "remove", "--force", str(wt)], cwd=REPO, capture_output=True)
            shutil.rmtree(tmp, ignore_errors=True)


def compare(base1: Path, base2: Path, head: Path) -> dict[str, list[str]]:
    names = sorted({p.name for p in base1.glob("*.json")} | {p.name for p in head.glob("*.json")})
    out: dict[str, list[str]] = {"same": [], "unstable": [], "order-only": [], "racy": [], "differs": [], "missing": [],
                                 "added": []}  # fmt: skip
    for n in names:
        b1, b2, h = (_load(d / n) for d in (base1, base2, head))
        if n in KNOWN_RACY:
            out["racy"].append(n)
        elif b1 is None:
            out["added"].append(n)
        elif h is None:
            out["missing"].append(n)
        elif b1 == b2 and h == b1:
            out["same"].append(n)
        elif b1 == b2 and _same_but_list_order(b1, h):
            # equal content, other list order: the order of unordered DB reads (backlog §4.5) — listed, not gated
            out["order-only"].append(n)
        elif b1 == b2:
            out["differs"].append(n + _first_diff(b1, h))
        elif _multiset(b1) != _multiset(b2):
            out["racy"].append(n)  # timing decides even the canonical content on the base: reported, not gated
        else:
            same = _multiset(b1) == _multiset(h)
            out["unstable" if same else "differs"].append(n + ("" if same else " (as multiset)"))
    return out


def report(r: dict[str, list[str]]) -> int:
    for k in ("differs", "missing", "added", "racy", "order-only"):
        for n in r[k]:
            print(f"{k.upper():8} {n}")
    print(", ".join(f"{k} {len(v)}" for k, v in r.items()))
    return 1 if r["differs"] or r["missing"] else 0


# --- helpers -----------------------------------------------------------------------------------------------------


def _run(ref: str, wt: Path, dump: Path, args: list[str], env: dict[str, str], reuse: bool = False) -> Path:
    if not reuse:
        subprocess.run(["git", "worktree", "add", "--detach", str(wt), ref], cwd=REPO, check=True, capture_output=True)
    dump.mkdir(parents=True)
    # a fixed hash seed: set iteration order (e.g. ties between equal criteria weights) is the same in every run
    run_env = {**env, "BEHAVIOUR_DUMP": str(dump), "PYTHONHASHSEED": "0",
               "PYTHONPATH": os.pathsep.join(filter(None, [str(PLUGIN_DIR), env.get("PYTHONPATH")]))}  # fmt: skip
    cmd = ["uv", "run", "pytest", "-q", "-p", "behaviour_dump_plugin", "-p", "no:randomly", *args]
    r = subprocess.run(cmd, cwd=wt / "backend", env=run_env, capture_output=True, text=True)
    tail = r.stdout.strip().splitlines()[-1:] if r.stdout.strip() else ["(no output)"]
    print(f"{ref}: {tail[0]}  -> {len(list(dump.glob('*.json')))} dumps")
    return dump


def _test_env() -> dict[str, str]:
    env = dict(os.environ)
    if env.get("TEST_DATABASE_URL"):
        return env
    dotenv = REPO / ".env.docker"
    if dotenv.exists():
        for line in dotenv.read_text(encoding="utf-8").splitlines():
            k, sep, v = line.partition("=")
            if sep and not line.startswith("#"):
                env.setdefault(k.strip(), v.strip().strip('"'))
        pw, port = env.get("POSTGRES_PASSWORD", ""), env.get("AUTOMIND_DB_PORT", "5433")
        env["TEST_DATABASE_URL"] = f"postgresql+asyncpg://automind:{pw}@127.0.0.1:{port}/automind_test"
    return env


def _load(p: Path) -> list[dict] | None:
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def _multiset(events: list[dict]) -> Counter[str]:
    """Canonical form for tests that are not stable even on the base: ids collapsed (parallel jobs interleave, so
    first-appearance numbers shift) and every list sorted (unordered DB reads and job completion order). Stable
    tests are still compared byte for byte, order included."""
    return Counter(json.dumps(_canonical(json.loads(re.sub(r"<id\d+>", "<id>", json.dumps(e)))), sort_keys=True)
                   for e in events)  # fmt: skip


def _same_but_list_order(a: list[dict], b: list[dict]) -> bool:
    """The same events in the same order, differing only in the order of list items inside them."""
    return len(a) == len(b) and all(_canonical(x) == _canonical(y) for x, y in zip(a, b, strict=True))


def _canonical(v: object) -> object:
    if isinstance(v, dict):
        return {k: _canonical(x) for k, x in v.items()}
    if isinstance(v, list):
        return sorted((_canonical(x) for x in v), key=lambda x: json.dumps(x, sort_keys=True))
    return v


def _first_diff(a: list[dict], b: list[dict]) -> str:
    for i, (x, y) in enumerate(zip(a, b, strict=False)):
        if x != y:
            return f" (event {i}: {json.dumps(x, ensure_ascii=False)[:160]} != {json.dumps(y, ensure_ascii=False)[:160]})"
    return f" (length {len(a)} != {len(b)})"


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
