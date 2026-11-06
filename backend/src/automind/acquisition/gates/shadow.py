"""The shadow gate (spec 011 US5 T102, research R14): both versions on the next live/prefetch pages; the user sees the
old version's values.

The parse stage (the live parser registry, after a job read its pages) and the extraction stage queue
`gate_shadow:<change_id>:<snapshot_id>` for every page of an object whose change is in phase `shadow` — the turn only
writes a queue row. The worker's handler adds the page to the experiment (`acq_experiments.corpus`, pinned), measures
both versions on all its shadow pages (`gates/evaluate.py`) and decides with `domain/gates.shadow_verdict`: accept
(the new version becomes active, the old one superseded), reject, abandon (budget or `shadow.max_days`), or wait. The
daily evaluator also calls `decide()` so a shadow without new pages ends on time. A relevance keyword change is
measured on the pages the relevance rules judged live since its replay passed (`gates/relevance_replay.py`).
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, text

from automind.acquisition.agents.budget import AgentBudget
from automind.acquisition.domain import gates, relevance_audit
from automind.acquisition.domain.versions import parse_key
from automind.acquisition.gates import evaluate, journal, relevance_replay, replay_gate
from automind.acquisition.infrastructure import overrides
from automind.shared.infrastructure.db import AcqChange, AcqExperiment, sessionmaker

log = logging.getLogger(__name__)


async def _shadow_changes(kinds: Iterable[str]) -> list[AcqChange]:
    async with sessionmaker()() as s:
        q = select(AcqChange).where(AcqChange.status == "shadow", AcqChange.closed_at.is_(None),
                                    AcqChange.object_kind.in_(list(kinds)))  # fmt: skip
        return list((await s.execute(q)).scalars())


async def _enqueue(c: AcqChange, snapshot_ids: Iterable[str]) -> int:
    from automind.acquisition.worker import queue  # noqa: PLC0415

    n = 0
    for sid in snapshot_ids:
        got = await queue.enqueue("gate_shadow", {"change_id": c.id, "snapshot_id": sid, "agent": journal.agent_of(c)},
                                  dedupe_key=f"gate_shadow:{c.id}:{sid}")  # fmt: skip
        n += got is not None
    return n


async def notify_read(read: Mapping[str, str]) -> int:
    """Pages a live reader just read (snapshot id → parser version key): queue them for parser and rule changes in
    shadow (rule changes re-validate reader rows)."""
    if not read or not (overrides.in_shadow("parser") or overrides.in_shadow("rule")):
        return 0
    n = 0
    for c in await _shadow_changes(("parser", "rule")):
        if c.object_kind == "parser":
            ids = [sid for sid, key in read.items() if _reader(key) == c.object_key]
        else:
            ids = list(read)
        n += await _enqueue(c, ids)
    return n


async def notify_extracted(prompt_name: str | None, snapshot_ids: list[str]) -> int:
    """Pages the extractor just read: queue them for prompt changes of that prompt and extractor model changes."""
    n = 0
    for c in await _shadow_changes(("prompt", "role_model")):
        if (c.object_kind == "prompt" and c.object_key == prompt_name) or (
            c.object_kind == "role_model" and c.object_key == "extractor"
        ):
            n += await _enqueue(c, snapshot_ids)
    return n


def _reader(key: str) -> str | None:
    try:
        return parse_key(key)[0]
    except ValueError:
        return None


_APPEND = text(
    "UPDATE acq_experiments SET corpus = array_append(corpus, CAST(:sid AS varchar(36))) "
    "WHERE change_id = :c AND NOT (CAST(:sid AS varchar(36)) = ANY(corpus))"
)


async def _add(change_id: str, snapshot_id: str) -> None:
    """Add a page to the shadow corpus atomically (shadow tasks run concurrently) and pin it."""
    from sqlalchemy import update  # noqa: PLC0415

    from automind.acquisition.snapshots import codec  # noqa: PLC0415
    from automind.shared.infrastructure.db import PageSnapshot  # noqa: PLC0415

    async with sessionmaker()() as s:
        await s.execute(_APPEND, {"c": change_id, "sid": snapshot_id})
        await s.execute(update(PageSnapshot).where(PageSnapshot.id == snapshot_id)
                        .values(retention_class=codec.PINNED, keep_until=None))  # fmt: skip
        await s.commit()


async def run(change_id: str, snapshot_id: str | None = None, *, llm: Any = None, guard: AgentBudget | None = None,
              now: datetime | None = None) -> dict[str, Any]:  # fmt: skip
    """Add one page (when given) to the change's shadow and decide."""
    now = now or datetime.now(UTC)
    c = await journal.load(change_id)
    if c is None or c.status != "shadow" or c.closed_at is not None:
        return {"skipped": "not in shadow"}
    guard = guard or AgentBudget(journal.agent_of(c))
    if relevance_replay.applies(c):
        return await _relevance(c, now, llm=llm, guard=guard)
    if snapshot_id:
        await _add(change_id, snapshot_id)
    async with sessionmaker()() as s:
        exp = await s.get(AcqExperiment, change_id)
    ids = list(exp.corpus or []) if exp is not None else []
    started = exp.started_at if exp is not None and exp.started_at else now
    days = max(0.0, (now - started).total_seconds() / 86400)
    gc = replay_gate.cfg()
    rs = await evaluate.refs(ids)
    if rs:
        try:
            old, new = await evaluate.measure(c, rs, llm=llm, charge=guard.charge)
        except evaluate.NoMeasure as e:
            old = new = gates.Metrics()
            log.info("gate.shadow no measure change=%s: %s", change_id, e)
    else:
        old = new = gates.Metrics()
    budget_left = await guard.remaining() > 0
    verdict = gates.shadow_verdict(old, new, gc, days=days, budget_left=budget_left,
                                   degraded=await replay_gate.degraded(c))  # fmt: skip
    async with sessionmaker()() as s:
        e = await s.get(AcqExperiment, change_id)
        if e is not None:
            e.pages_old, e.pages_new = old.pages, new.pages
            e.metrics_old, e.metrics_new = old.as_dict(), new.as_dict()
            await s.commit()
    out = {"change_id": change_id, "pages": len(rs), "verdict": verdict.verdict, "reasons": list(verdict.reasons)}
    if verdict.verdict == "pass":
        await journal.accept(change_id, verdict, old, new)
        await replay_gate.unpin(await replay_gate._decided(change_id, "accepted"))
        await overrides.refresh(force=True)
    elif verdict.verdict == "fail":
        await journal.reject(change_id, "shadow", verdict, old, new)
        await replay_gate.unpin(await replay_gate._decided(change_id, "rejected"))
    elif verdict.verdict == "abandon":
        await journal.abandon(change_id, "shadow", verdict, old, new)
        await replay_gate.unpin(await replay_gate._decided(change_id, "abandoned"))
    log.info("gate.shadow change=%s pages=%d verdict=%s %s", change_id, len(rs), verdict.verdict, verdict.reason)
    return out


async def _relevance(c: AcqChange, now: datetime, *, llm: Any, guard: AgentBudget) -> dict[str, Any]:
    """A relevance keyword change in shadow: the pages the relevance rules judged live since the replay passed
    (judged with the old keywords; the user saw that) re-judged with the new ones."""
    async with sessionmaker()() as s:
        exp = await s.get(AcqExperiment, c.id)
    started = exp.started_at if exp is not None and exp.started_at else now
    days = max(0.0, (now - started).total_seconds() / 86400)
    gc, rc = replay_gate.cfg(), relevance_replay.gate_cfg()
    res = await relevance_replay.measure(c, started, now, limit=rc.max_pages, llm=llm, charge=guard.charge)
    await replay_gate.pin(c.id, "shadow", res.snapshot_ids)
    verdict = relevance_audit.relevance_shadow_verdict(
        res.measure, rc, days=days, min_pages=gc.shadow_min_pages, decide_days=gc.shadow_decide_days,
        max_days=gc.shadow_max_days, budget_left=await guard.remaining() > 0)  # fmt: skip
    old, new = res.old, res.new
    async with sessionmaker()() as s:
        e = await s.get(AcqExperiment, c.id)
        if e is not None:
            e.pages_old, e.pages_new = old.pages, new.pages
            e.metrics_old, e.metrics_new = old.as_dict(), new.as_dict()
            await s.commit()
    extra = {"relevance": res.measure.as_dict()}
    if verdict.verdict == "pass":
        await journal.accept(c.id, verdict, old, new, **extra)
        await replay_gate.unpin(await replay_gate._decided(c.id, "accepted"))
        await overrides.refresh(force=True)
    elif verdict.verdict == "fail":
        await journal.reject(c.id, "shadow", verdict, old, new, **extra)
        await replay_gate.unpin(await replay_gate._decided(c.id, "rejected"))
    elif verdict.verdict == "abandon":
        await journal.abandon(c.id, "shadow", verdict, old, new, **extra)
        await replay_gate.unpin(await replay_gate._decided(c.id, "abandoned"))
    log.info("gate.shadow change=%s pages=%d verdict=%s %s", c.id, res.measure.pages, verdict.verdict,
             verdict.reason)  # fmt: skip
    return {"change_id": c.id, "pages": res.measure.pages, "verdict": verdict.verdict,
            "reasons": list(verdict.reasons), **extra}  # fmt: skip


async def decide_all(now: datetime | None = None) -> dict[str, str]:
    """The evaluator's daily pass: every change in shadow is decided on time even without new pages."""
    return {c.id: (await run(c.id, now=now)).get("verdict", "skipped") for c in await _shadow_changes(
        ("parser", "rule", "prompt", "role_model", "source"))}  # fmt: skip
