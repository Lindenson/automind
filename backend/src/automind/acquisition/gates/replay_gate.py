"""The replay gate (spec 011 US5 T101, research R14), worker task `gate_replay:<change_id>`.

Corpus: the object's stored pages of the 30 days up to the change's `as_of` (the drift day for a repair; extended by
the days the change has waited), pinned in `acq_experiments.corpus` (`retention_class=pinned`) while the gates run.
For a redesign the yield is measured on the pages fetched since `changed_on` and the accuracy on every gold-covered
page. Old and new versions run on the same pages (`gates/evaluate.py`: readers offline, extractors cached and within
the agent's budget) and `domain/gates.replay_verdict` decides: pass → shadow; fail → rejected with the reason;
insufficient evidence → the task re-queues itself for the next day, up to `wait_days`, then abandoned.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from sqlalchemy import update

from automind.acquisition.agents.budget import AgentBudget
from automind.acquisition.domain import gates
from automind.acquisition.gates import evaluate, journal
from automind.acquisition.snapshots import codec
from automind.infrastructure import config
from automind.infrastructure.db import AcqChange, AcqExperiment, PageSnapshot, ParserVersion, sessionmaker

log = logging.getLogger(__name__)
WINDOW_DAYS = 30


def cfg() -> gates.GateConfig:
    return gates.GateConfig.from_mapping(config.agents_config())


def _dt(v: Any) -> datetime | None:
    if not v:
        return None
    if isinstance(v, datetime):
        return v
    d = date.fromisoformat(str(v)[:10])
    return datetime.combine(d, time.min, tzinfo=UTC)


async def degraded(c: AcqChange) -> bool:
    """The object's running version is degraded (a repair: the KPI is the new version's own accuracy)."""
    if bool((c.evidence or {}).get("degraded")):
        return True
    if c.object_kind != "parser" or not c.from_version:
        return c.object_kind == "parser"  # a site without a parser: nothing to compare with
    async with sessionmaker()() as s:
        old = await s.get(ParserVersion, c.from_version)
    return old is not None and old.status == "degraded"


async def corpus(c: AcqChange, now: datetime | None = None) -> list[Any]:
    """The stored pages the gate compares on (ids are pinned by `pin`)."""
    now = now or datetime.now(UTC)
    ev = c.evidence or {}
    as_of = _dt(ev.get("as_of")) or now
    waited = max(0.0, (now - c.created_at).total_seconds() / 86400) if c.created_at else 0.0
    since, until = as_of - timedelta(days=WINDOW_DAYS), min(now, as_of + timedelta(days=1 + int(waited)))
    replay_cfg = config.acquisition_config().get("replay") or {}
    if c.object_kind == "parser":
        old, new = await evaluate.spec_of(c.from_version), await evaluate.spec_of(c.to_version)
        from automind.acquisition.parsing import interpreter  # noqa: PLC0415

        refs = await evaluate.corpus_refs(evaluate.domains_of(c, old, new), since, until)
        return [r for r in refs if new is None or interpreter.applies(new, r.final_url or r.url)]
    if c.object_kind == "rule":
        specs = await evaluate._running_specs()
        return await evaluate.corpus_refs(sorted({d for sp in specs for d in sp.domains}), since, until)
    cap = int(replay_cfg.get("extractor_max_pages", 60))
    refs = await evaluate.corpus_refs(None, since, until, limit=cap * 10)
    return [r for r in refs if r.variant_ids][:cap]


async def pin(change_id: str, phase: str, ids: list[str]) -> None:
    """Pin the corpus (never removed by retention while the experiment runs) and record it."""
    async with sessionmaker()() as s:
        exp = await s.get(AcqExperiment, change_id)
        old = list(exp.corpus or []) if exp is not None else []
        if exp is None:
            exp = AcqExperiment(change_id=change_id, phase=phase, started_at=datetime.now(UTC), corpus=ids,
                                daily={})  # fmt: skip
            s.add(exp)
        else:
            exp.phase, exp.corpus = phase, ids
        if ids:
            await s.execute(update(PageSnapshot).where(PageSnapshot.id.in_(ids))
                            .values(retention_class=codec.PINNED, keep_until=None))  # fmt: skip
        await s.commit()
    if dropped := sorted(set(old) - set(ids)):
        await unpin(dropped)


async def unpin(ids: list[str]) -> None:
    """Back to the class the page earned (plain or accepted), unless another open experiment still holds it."""
    if not ids:
        return
    from sqlalchemy import select, text  # noqa: PLC0415

    rc = config.snapshot_retention()
    async with sessionmaker()() as s:
        held = {str(x) for (x,) in (await s.execute(text(
            "SELECT DISTINCT unnest(corpus) FROM acq_experiments WHERE decided_at IS NULL AND corpus && :ids"),
            {"ids": ids})).all()}  # fmt: skip
        rows = (
            await s.execute(
                select(PageSnapshot).where(
                    PageSnapshot.id.in_([i for i in ids if i not in held]), PageSnapshot.retention_class == codec.PINNED
                )
            )
        ).scalars()
        for r in rows:
            cls = codec.retention_class(r.accepted_values, pinned=False)
            r.retention_class, r.keep_until = cls, codec.keep_until(r.fetched_at, cls, rc)
        await s.commit()


async def _decided(change_id: str, decision: str) -> list[str]:
    async with sessionmaker()() as s:
        exp = await s.get(AcqExperiment, change_id)
        if exp is None:
            return []
        exp.decided_at, exp.decision = datetime.now(UTC), decision
        ids = list(exp.corpus or [])
        await s.commit()
    return ids


async def run(change_id: str, *, llm: Any = None, guard: AgentBudget | None = None,
              now: datetime | None = None) -> dict[str, Any]:  # fmt: skip
    from automind.acquisition.worker import queue  # noqa: PLC0415

    now = now or datetime.now(UTC)
    c = await journal.load(change_id)
    if c is None or c.status not in ("proposed", "replay") or c.closed_at is not None:
        return {"skipped": "not waiting for replay"}
    guard = guard or AgentBudget(journal.agent_of(c))
    rs = await corpus(c, now)
    await pin(change_id, "replay", [r.id for r in rs])
    waited = max(0.0, (now - c.created_at).total_seconds() / 86400) if c.created_at else 0.0
    gc = cfg()
    try:
        old, new = await evaluate.measure(c, rs, since=_dt((c.evidence or {}).get("changed_on")), llm=llm,
                                          charge=guard.charge)  # fmt: skip
        verdict = gates.replay_verdict(old, new, gc, degraded=await degraded(c), waited_days=waited)
    except evaluate.NoMeasure as e:
        old = new = gates.Metrics()
        why = str(e)
        verdict = gates.Verdict("abandon" if waited >= gc.wait_days else "insufficient_evidence", (why,))
    out = {"change_id": change_id, "pages": len(rs), "verdict": verdict.verdict, "reasons": list(verdict.reasons),
           "old": old.as_dict(), "new": new.as_dict()}  # fmt: skip
    if verdict.verdict == "pass":
        await journal.advance(change_id, "shadow", "replay", verdict, old, new, corpus=len(rs))
        await pin(change_id, "shadow", [])  # the shadow phase collects its own live pages
        async with sessionmaker()() as s:
            exp = await s.get(AcqExperiment, change_id)
            assert exp is not None
            exp.started_at, exp.ends_at = now, now + timedelta(days=gc.shadow_max_days)
            exp.pages_old = exp.pages_new = 0
            exp.metrics_old, exp.metrics_new = None, None
            await s.commit()
        from automind.infrastructure import overrides  # noqa: PLC0415

        await overrides.refresh(force=True)  # live readers of this process start feeding the shadow at once
    elif verdict.verdict == "fail":
        await journal.reject(change_id, "replay", verdict, old, new)
        await unpin(await _decided(change_id, "rejected"))
    elif verdict.verdict == "abandon":
        await journal.abandon(change_id, "replay", verdict, old, new)
        await unpin(await _decided(change_id, "abandoned"))
    else:  # insufficient evidence: wait for prefetch to gather pages, try again tomorrow
        await journal.advance(change_id, "replay", "replay", verdict, old, new, corpus=len(rs))
        day = (now + timedelta(days=1)).date()
        await queue.enqueue("gate_replay", {"change_id": change_id, "agent": journal.agent_of(c)},
                            dedupe_key=f"gate_replay:{change_id}:{day.isoformat()}",
                            run_at=datetime.combine(day, time(3, 0), tzinfo=UTC))  # fmt: skip
    log.info("gate.replay change=%s verdict=%s %s", change_id, verdict.verdict, verdict.reason)
    return out
