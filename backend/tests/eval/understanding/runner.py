"""Spec 013 T005: the golden message set on today's interpreter (real model), scored, written as the baseline.

    cd backend && uv run python -m tests.eval.understanding.runner [--ids ru-001,es-004] [--limit N]
                                                                   [--out ../specs/013-dialogue-quality/baseline.md]

Free part first: the harness ceiling (`oracle`), the same cases with the expected labels. Then the paid part: one
interpreter call per case that is not a plain limit yes/no (≈ 145 calls). Needs the model keys and a
database for the usage rows (`DATABASE_URL`; the test DB is fine). Every case runs under its own turn budget; the
summed cost is printed and written. A case whose call fails (provider down) is reported as an error, not scored.
The path and its limits: `old_path` module doc. Scoring: `scoring` module doc.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from automind.chat.application.services.interpretation.service import InterpretationService
from automind.chat.dialog.prompts import load_all as load_prompts
from automind.chat.dialog.report_wording import WORDING
from automind.chat.infrastructure.adapters import policy_config
from automind.delivery.bootstrap import configure_domain, reference
from automind.shared.infrastructure.config.settings import settings
from automind.shared.infrastructure.llm import gateway
from automind.shared.infrastructure.metrics.understanding_eval import EvalSummary
from automind.shared.metering.usage import current_budget
from tests.eval.understanding.coverage import categories
from tests.eval.understanding.fixture_models import Fixtures, load_fixtures
from tests.eval.understanding.old_path import Observed, run_case
from tests.eval.understanding.oracle import OracleLLM
from tests.eval.understanding.schema import Case, load_cases
from tests.eval.understanding.scoring import FIELDS, Score, score

OUT = Path(__file__).resolve().parents[4] / "specs" / "013-dialogue-quality" / "baseline.md"
CONCURRENCY = 4


@dataclass(frozen=True)
class Result:
    case: Case
    observed: Observed | None
    score: Score | None
    cost_eur: float
    error: str | None = None


async def _no_log(kind: str, car_key: str | None = None, item: str | None = None, **details: object) -> None:
    """The intake log is metrics only; the eval records nothing."""


async def run(cases: list[Case], fx: Fixtures, llm: object, *, quiet: bool = False) -> list[Result]:
    """Every case through today's path with `llm` as the model, `CONCURRENCY` at a time, each under its own turn
    budget."""
    configure_domain()
    ref = reference(load_prompts())
    service = InterpretationService(llm, ref, WORDING, _no_log)  # type: ignore[arg-type]
    cfg = policy_config(settings(), ref.search)
    gate = asyncio.Semaphore(CONCURRENCY)

    async def one(c: Case) -> Result:
        async with gate:
            budget = gateway.new_budget(None, None)
            token = current_budget.set(budget)
            pending = fx.pendings[c.pending] if c.pending else None
            try:
                o = await run_case(service, c, fx.cases[c.fixture], pending, cfg)
            except Exception as e:  # noqa: BLE001  an eval reports a failed case and goes on; never in src
                return Result(c, None, None, budget.cost_eur, f"{type(e).__name__}: {e}"[:300])
            finally:
                current_budget.reset(token)
            if not quiet:
                print(f"{c.id} {o.action} {'ok' if score(c.expect, o).ok else 'MISS'}", flush=True)
            return Result(c, o, score(c.expect, o), budget.cost_eur)

    return list(await asyncio.gather(*(one(c) for c in cases)))


class _Gateway:
    """The live model gateway as the `LLM` port (the chat's `LiveLLM` without the agent factory)."""

    async def structured(self, role: str, schema: type, system: str, user: str):  # type: ignore[no-untyped-def]
        return await gateway.structured(role, schema, system, user)

    async def text(self, role: str, system: str, user: str) -> str:
        return await gateway.text(role, system, user)


# ----------------------------------------------------------------------------------------------- the report ----


def report(results: list[Result], fx: Fixtures, when: datetime, ceiling: list[Result]) -> str:
    """baseline.md: accuracy per field, per language, per pending kind and per category; latency; failures."""
    done = [r for r in results if r.score is not None]
    lat = sorted(r.observed.latency_ms for r in done if r.observed and r.observed.model_called)
    cost = sum(r.cost_eur for r in results)
    lines = [
        "# Spec 013 T005 — understanding baseline (today's interpreter)", "",
        f"Run {when:%Y-%m-%d %H:%M} UTC · model `{gateway.model_name('interpreter')}` · prompt "
        f"`{load_prompts()['interpreter'].splitlines()[0][:60]}` · {len(results)} cases, {len(done)} scored, "
        f"{len(results) - len(done)} errors · cost €{cost:.3f}", "",
        "Produced by `backend/tests/eval/understanding/runner.py`. How the old path is run and what it cannot run "
        "(identification and assessment: no catalogue in the fixtures; car facts from the fixture's resolution) is "
        "in `old_path.py`; the scoring rules in `scoring.py`. Old labels → new fields by understanding-spec §4.", "",
        "## Accuracy per field", "",
        "Ceiling = the same harness with an interpreter that returns the expected labels (`oracle.py`): what the "
        "old schema and this harness can score at best. The gap between the two columns is the model's; the gap "
        "between the ceiling and 100 % is the old schema's (no `stop`, no answer kinds for typed confirmations, no "
        "ANSWER_AND_REASK) or the harness's (no identification / assessment, so `action` is indicative only).", "",
        "| Field | Checked | Correct | Accuracy | Ceiling |", "|---|---|---|---|---|",
        *(_row(f, _scores(done), _scores(ceiling)) for f in FIELDS),
        _row_all("all fields of the case", _scores(done), _scores(ceiling)), "",
        f"## Latency of the understanding step (old interpreter, {len(lat)} model calls)", "",
        f"p50 {_pct(lat, 50):.0f} ms · p95 **{_pct(lat, 95):.0f} ms** · max {max(lat, default=0):.0f} ms — the "
        "reference for the +20 % criterion (G4). Wall clock with 4 calls in flight.", "",
        *_table("Per language", done, lambda r: [r.case.lang.value]),
        *_table("Per pending kind", done, lambda r: [fx.pendings[r.case.pending].kind.value if r.case.pending
                                                     else "none"]),  # fmt: skip
        *_table("Per category", done, lambda r: sorted(c.value for c in categories(r.case, fx))),
        "## Failures", "", "| Case | Message | Fields (expected / got) |", "|---|---|---|",
        *(_failure(r) for r in done if not r.score.ok),  # type: ignore[union-attr]
        "", "## Errors", "", *(f"- {r.case.id}: {r.error}" for r in results if r.error), "",
    ]  # fmt: skip
    return "\n".join(lines)


def _scores(results: list[Result]) -> list[Score]:
    return [r.score for r in results if r.score is not None]


def _row(f: str, scores: Iterable[Score], ceiling: list[Score]) -> str:
    vals = [s.fields[f] for s in scores if f in s.fields]
    top = [s.fields[f] for s in ceiling if f in s.fields]
    return f"| {f} | {len(vals)} | {sum(vals)} | {_ratio(sum(vals), len(vals))} | {_ratio(sum(top), len(top))} |"


def _row_all(label: str, scores: list[Score], ceiling: list[Score]) -> str:
    ok = sum(s.ok for s in scores)
    top = _ratio(sum(s.ok for s in ceiling), len(ceiling))
    return f"| **{label}** | {len(scores)} | {ok} | **{_ratio(ok, len(scores))}** | {top} |"


def _table(title: str, done: list[Result], keys_of) -> list[str]:  # type: ignore[no-untyped-def]
    groups: dict[str, list[Score]] = defaultdict(list)
    for r in done:
        for k in keys_of(r):
            groups[k].append(r.score)  # type: ignore[arg-type]
    head = "| | cases | all ok | " + " | ".join(FIELDS) + " |"
    rows = [f"| {k} | {len(v)} | {_ratio(sum(s.ok for s in v), len(v))} | "
            + " | ".join(_cell(f, v) for f in FIELDS) + " |" for k, v in sorted(groups.items())]  # fmt: skip
    return [f"## {title}", "", head, "|" + "---|" * (len(FIELDS) + 3), *rows, ""]


def _cell(f: str, scores: list[Score]) -> str:
    vals = [s.fields[f] for s in scores if f in s.fields]
    return _ratio(sum(vals), len(vals)) if vals else "–"


def _failure(r: Result) -> str:
    misses = "<br>".join(f"**{k}** {v}".replace("|", "/") for k, v in r.score.misses.items())  # type: ignore[union-attr]
    return f"| {r.case.id} | {r.case.message.replace('|', '/')[:80]} | {misses} |"


def _ratio(n: int, d: int) -> str:
    return f"{100 * n / d:.0f} %" if d else "–"


def _pct(xs: list[float], p: int) -> float:
    if not xs:
        return 0.0
    return xs[0] if len(xs) == 1 else statistics.quantiles(xs, n=100, method="inclusive")[p - 1]


def _dump(results: list[Result], path: Path) -> None:
    rows = [{"id": r.case.id, "error": r.error, "cost_eur": r.cost_eur,
             "fields": r.score.fields if r.score else None, "misses": r.score.misses if r.score else None,
             "request": r.observed.request if r.observed else None,
             "latency_ms": r.observed.latency_ms if r.observed else None} for r in results]  # fmt: skip
    path.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")


def summary(results: list[Result], ceiling: list[Result], when: datetime) -> EvalSummary:
    """The nightly summary the app exports as gauges (`shared.infrastructure.metrics.understanding_eval`)."""
    lat = sorted(r.observed.latency_ms for r in results if r.observed and r.observed.model_called)
    return EvalSummary(
        finished_at=when.timestamp(), model=gateway.model_name("interpreter"), cases=len(_scores(results)),
        errors=sum(1 for r in results if r.error), cost_eur=round(sum(r.cost_eur for r in results), 4),
        latency_p95_ms=_pct(lat, 95), accuracy=_shares(_scores(results)), ceiling=_shares(_scores(ceiling)),
    )  # fmt: skip


def _shares(scores: list[Score]) -> dict[str, float]:
    out = {f: sum(v) / len(v) for f in FIELDS if (v := [s.fields[f] for s in scores if f in s.fields])}
    out["all"] = sum(s.ok for s in scores) / len(scores) if scores else 0.0
    return {k: round(v, 4) for k, v in out.items()}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--ids", default="", help="comma-separated case ids (default: all)")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--summary", type=Path, default=None, help="also write the nightly summary JSON here")
    ap.add_argument("--ceiling-only", action="store_true", help="only the free oracle run (no model call)")
    a = ap.parse_args()
    fx, cases = load_fixtures(), load_cases()
    if a.ids:
        wanted = set(a.ids.split(","))
        cases = [c for c in cases if c.id in wanted]
    if a.limit:
        cases = cases[: a.limit]
    ceiling = asyncio.run(run(cases, fx, OracleLLM(cases), quiet=True))
    results = ceiling if a.ceiling_only else asyncio.run(run(cases, fx, _Gateway()))
    a.out.write_text(report(results, fx, datetime.now(UTC), ceiling), encoding="utf-8")
    _dump(results, a.out.with_suffix(".json"))
    if a.summary is not None:
        a.summary.write_text(summary(results, ceiling, datetime.now(UTC)).model_dump_json(indent=1), encoding="utf-8")
    done = [r for r in results if r.score]
    print(
        f"cases {len(results)} scored {len(done)} all-ok {sum(r.score.ok for r in done)} "  # type: ignore[union-attr]
        f"cost €{sum(r.cost_eur for r in results):.4f} → {a.out}"
    )
    print(Counter(r.error.split(":")[0] for r in results if r.error))


if __name__ == "__main__":
    main()
