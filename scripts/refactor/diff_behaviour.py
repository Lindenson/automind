#!/usr/bin/env python3
"""Before/after behaviour diff of a refactoring step (spec 012 research R11). The gate of every step S3a–S13.

    diff_behaviour.py [--base REF] [--head REF] [--keep] [-- pytest args]

Runs the behaviour suites (tests/graph, tests/golden, tests/integration by default) on the base and on the head,
each in its own temporary git worktree, with `behaviour_dump_plugin` writing every test's normalised chat events.
The base runs twice: tests whose events differ between two base runs (parallel research interleaving) are
compared as multisets; all others byte for byte. Exit 1 on any difference, with the first differing event.

Runs never overlap (one test database). TEST_DATABASE_URL is taken from the environment or .env.docker like
scripts/check.sh does.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PLUGIN_DIR = Path(__file__).resolve().parent
SUITES = ["tests/graph", "tests/golden", "tests/integration"]


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
        base1 = _run(a.base, tmp / "base", tmp / "dump-base-1", a.pytest_args, env)
        base2 = _run(a.base, tmp / "base", tmp / "dump-base-2", a.pytest_args, env, reuse=True)
        head = _run(a.head, tmp / "head", tmp / "dump-head", a.pytest_args, env)
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
    out: dict[str, list[str]] = {"same": [], "unstable": [], "differs": [], "missing": [], "added": []}
    for n in names:
        b1, b2, h = (_load(d / n) for d in (base1, base2, head))
        if b1 is None:
            out["added"].append(n)
        elif h is None:
            out["missing"].append(n)
        elif b1 == b2:
            out["same" if h == b1 else "differs"].append(n + ("" if h == b1 else _first_diff(b1, h)))
        else:
            same = _multiset(b1) == _multiset(h)
            out["unstable" if same else "differs"].append(n + ("" if same else " (as multiset)"))
    return out


def report(r: dict[str, list[str]]) -> int:
    for k in ("differs", "missing", "added"):
        for n in r[k]:
            print(f"{k.upper():8} {n}")
    print(", ".join(f"{k} {len(v)}" for k, v in r.items()))
    return 1 if r["differs"] or r["missing"] else 0


# --- helpers -----------------------------------------------------------------------------------------------------


def _run(ref: str, wt: Path, dump: Path, args: list[str], env: dict[str, str], reuse: bool = False) -> Path:
    if not reuse:
        subprocess.run(["git", "worktree", "add", "--detach", str(wt), ref], cwd=REPO, check=True, capture_output=True)
    dump.mkdir(parents=True)
    run_env = {**env, "BEHAVIOUR_DUMP": str(dump),
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
    return Counter(json.dumps(e, sort_keys=True) for e in events)


def _first_diff(a: list[dict], b: list[dict]) -> str:
    for i, (x, y) in enumerate(zip(a, b, strict=False)):
        if x != y:
            return f" (event {i}: {json.dumps(x, ensure_ascii=False)[:160]} != {json.dumps(y, ensure_ascii=False)[:160]})"
    return f" (length {len(a)} != {len(b)})"


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
