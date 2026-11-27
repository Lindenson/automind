"""Spec 013 T034: the golden message set on the new understanding chain (real model), compared case by case with the
old interpreter's baseline run (T005, `baseline.json`), written as `shadow.md`.

    cd backend && uv run python -m tests.eval.understanding.shadow [--ids ru-001,es-004] [--limit N]
                                                                   [--out ../specs/013-dialogue-quality/shadow.md]

One understander call per case (≈ 148 calls on the `understander` role). Needs the model keys and a database for the
usage rows (`DATABASE_URL`). A case whose call fails is reported as an error, not scored. The new path and its
limits: `new_path` module doc; the scoring: `scoring`. "Old" is read from the baseline file, not run again.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

from automind.chat.application.services.understanding.understander import Understander
from automind.chat.dialog.prompts import load_all as load_prompts
from automind.chat.infrastructure.adapters import policy_config
from automind.delivery.bootstrap import configure_domain, reference
from automind.shared.infrastructure.config.settings import settings
from automind.shared.infrastructure.llm import gateway
from automind.shared.metering.usage import current_budget
from tests.eval.understanding.fixture_models import Fixtures, load_fixtures
from tests.eval.understanding.new_path import run_case
from tests.eval.understanding.runner import OUT, Result, _failure, _Gateway, _pct, _ratio
from tests.eval.understanding.schema import Case, load_cases
from tests.eval.understanding.scoring import FIELDS, score

SHADOW = OUT.with_name("shadow.md")
BASELINE = OUT.with_suffix(".json")
CONCURRENCY = 4
WINDOW = (6, 600)


async def run(cases: list[Case], fx: Fixtures, llm: object) -> list[Result]:
    """Every case through the new chain, `CONCURRENCY` at a time, each under its own turn budget."""
    configure_domain()
    ref = reference(load_prompts())
    understander = Understander(llm, ref.prompts["understander"], WINDOW)  # type: ignore[arg-type]
    cfg = policy_config(settings(), ref.search)
    gate = asyncio.Semaphore(CONCURRENCY)

    async def one(c: Case) -> Result:
        async with gate:
            budget = gateway.new_budget(None, None)
            token = current_budget.set(budget)
            pending = fx.pendings[c.pending] if c.pending else None
            try:
                o = await run_case(understander, ref.makes, c, fx.cases[c.fixture], pending, cfg)
            except Exception as e:  # noqa: BLE001  an eval reports a failed case and goes on; never in src
                return Result(c, None, None, budget.cost_eur, f"{type(e).__name__}: {e}"[:300])
            finally:
                current_budget.reset(token)
            s = score(c.expect, o)
            print(f"{c.id} {o.action} {'ok' if s.ok else 'MISS'}", flush=True)
            return Result(c, o, s, budget.cost_eur)

    return list(await asyncio.gather(*(one(c) for c in cases)))


def report(results: list[Result], old: dict[str, dict[str, object]], fx: Fixtures, when: datetime) -> str:
    """shadow.md: new vs old per field and group, latency, what the new chain fixed and broke, its failures."""
    done = [r for r in results if r.score is not None and r.case.id in old and old[r.case.id].get("fields")]
    lat = sorted(r.observed.latency_ms for r in done if r.observed)
    old_lat = sorted(float(o["latency_ms"]) for o in old.values() if o.get("latency_ms"))  # type: ignore[arg-type]
    cost = sum(r.cost_eur for r in results)
    lines = [
        "# Spec 013 T034 — understanding in the shadow: new chain vs old interpreter", "",
        f"Run {when:%Y-%m-%d %H:%M} UTC · model `{gateway.model_name('understander')}` · prompt "
        f"`{load_prompts()['understander'].splitlines()[0][:60]}` · {len(results)} cases, {len(done)} compared, "
        f"{sum(1 for r in results if r.error)} errors · cost €{cost:.3f}", "",
        "Produced by `backend/tests/eval/understanding/shadow.py`. Old = the T005 baseline run (`baseline.json`, "
        "gemini-3.6-flash on the `interpreter` role); new = Understander → validate_understanding → IntentResolver "
        "(`new_path.py`). `action` is indicative on both sides: today's policy on the mapped request, without "
        "identification or assessment; the policy reads the intent only from S4.", "",
        "## Accuracy per field", "", "| Field | Checked | Old | New | Fixed | Broke |", "|---|---|---|---|---|---|",
        *(_row(f, done, old) for f in FIELDS), _row_all(done, old), "",
        f"## Latency of the understanding step ({len(lat)} new calls)", "",
        f"old p95 {_pct(old_lat, 95):.0f} ms · new p95 **{_pct(lat, 95):.0f} ms** (p50 {_pct(lat, 50):.0f} ms) — "
        "criterion: new ≤ old + 20 % (G4). Wall clock with 4 calls in flight.", "",
        *_groups("Per language", done, old, lambda r: r.case.lang.value),
        *_groups("Per pending kind", done, old, lambda r: fx.pendings[r.case.pending].kind.value if r.case.pending
                 else "none"),  # fmt: skip
        "## Broke (old right, new wrong)", "", "| Case | Message | Fields (expected / got) |", "|---|---|---|",
        *(_failure(r) for r in done if _broke(r, old)), "",
        "## All failures of the new chain", "", "| Case | Message | Fields (expected / got) |", "|---|---|---|",
        *(_failure(r) for r in done if not r.score.ok), "",  # type: ignore[union-attr]
        "## Errors", "", *(f"- {r.case.id}: {r.error}" for r in results if r.error), "",
    ]  # fmt: skip
    return "\n".join(lines)


def _old_field(old: dict[str, dict[str, object]], case_id: str, f: str) -> bool | None:
    fields = old[case_id].get("fields") or {}
    return fields.get(f) if isinstance(fields, dict) else None


def _row(f: str, done: list[Result], old: dict[str, dict[str, object]]) -> str:
    pairs = [(_old_field(old, r.case.id, f), r.score.fields.get(f)) for r in done]  # type: ignore[union-attr]
    pairs = [(o, n) for o, n in pairs if o is not None and n is not None]
    fixed, broke = sum(1 for o, n in pairs if n and not o), sum(1 for o, n in pairs if o and not n)
    return (f"| {f} | {len(pairs)} | {_ratio(sum(o for o, _ in pairs), len(pairs))} | "
            f"{_ratio(sum(n for _, n in pairs), len(pairs))} | {fixed} | {broke} |")  # fmt: skip


def _all_old(old: dict[str, dict[str, object]], case_id: str) -> bool:
    fields = old[case_id].get("fields") or {}
    return all(fields.values()) if isinstance(fields, dict) else False


def _row_all(done: list[Result], old: dict[str, dict[str, object]]) -> str:
    o = sum(_all_old(old, r.case.id) for r in done)
    n = sum(r.score.ok for r in done)  # type: ignore[union-attr]
    fixed = sum(1 for r in done if r.score.ok and not _all_old(old, r.case.id))  # type: ignore[union-attr]
    broke = sum(1 for r in done if _all_old(old, r.case.id) and not r.score.ok)  # type: ignore[union-attr]
    return f"| **all fields** | {len(done)} | {_ratio(o, len(done))} | **{_ratio(n, len(done))}** | {fixed} | {broke} |"


def _groups(title: str, done: list[Result], old: dict[str, dict[str, object]], key) -> list[str]:  # type: ignore[no-untyped-def]
    groups: dict[str, list[Result]] = defaultdict(list)
    for r in done:
        groups[key(r)].append(r)
    rows = [f"| {k} | {len(v)} | {_ratio(sum(_all_old(old, r.case.id) for r in v), len(v))} | "
            f"{_ratio(sum(r.score.ok for r in v), len(v))} |" for k, v in sorted(groups.items())]  # type: ignore[union-attr]  # fmt: skip
    return [f"## {title} (all fields)", "", "| | cases | old | new |", "|---|---|---|---|", *rows, ""]


def _broke(r: Result, old: dict[str, dict[str, object]]) -> bool:
    return any(_old_field(old, r.case.id, f) and not v for f, v in r.score.fields.items())  # type: ignore[union-attr]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--ids", default="", help="comma-separated case ids (default: all)")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--out", type=Path, default=SHADOW)
    a = ap.parse_args()
    fx, cases = load_fixtures(), load_cases()
    if a.ids:
        cases = [c for c in cases if c.id in set(a.ids.split(","))]
    if a.limit:
        cases = cases[: a.limit]
    old = {row["id"]: row for row in json.loads(BASELINE.read_text(encoding="utf-8"))}
    results = asyncio.run(run(cases, fx, _Gateway()))
    a.out.write_text(report(results, old, fx, datetime.now(UTC)), encoding="utf-8")
    rows = [{"id": r.case.id, "error": r.error, "cost_eur": r.cost_eur, "fields": r.score.fields if r.score else None,
             "misses": r.score.misses if r.score else None, "notes": r.observed.notes if r.observed else None,
             "latency_ms": r.observed.latency_ms if r.observed else None} for r in results]  # fmt: skip
    a.out.with_suffix(".json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    done = [r for r in results if r.score]
    print(f"cases {len(results)} scored {len(done)} all-ok {sum(r.score.ok for r in done)} "  # type: ignore[union-attr]
          f"cost €{sum(r.cost_eur for r in results):.4f} → {a.out}")  # fmt: skip


if __name__ == "__main__":
    main()
