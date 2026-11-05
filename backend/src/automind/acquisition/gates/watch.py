"""The watch after acceptance (spec 011 US5 T103, research R14): the evaluator compares an accepted change's live
metrics and the wrong signals blamed to its new version with the metrics it was accepted on; on degradation the
previous version is restored automatically and journalled ("km77 parser v5 rolled back: 3 wrong values blamed to v5
in 2 days; previous v4 restored"); after `watch_days` without degradation the change is kept.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, text

from automind.acquisition.domain import gates
from automind.acquisition.gates import evaluate, journal, replay_gate
from automind.infrastructure.db import AcqChange, AcqExperiment, PageSnapshot, sessionmaker

log = logging.getLogger(__name__)
MAX_PAGES = 200


def component_like(c: AcqChange) -> str | None:
    """The `truth_signals.component` pattern of the new version (research R9 keys)."""
    if c.object_kind == "parser":
        return f"parser:{c.to_version}"
    if c.object_kind == "prompt":
        return f"extractor:{c.to_version}|%"
    if c.object_kind == "role_model":
        return f"extractor:%|{c.to_version}"
    if c.object_kind == "rule":
        return f"rule:{c.object_key}"
    return None


async def wrong_signals(c: AcqChange, since: datetime) -> int:
    like = component_like(c)
    if like is None:
        return 0
    q = text("SELECT count(*) FROM truth_signals WHERE verdict = 'wrong' AND created_at >= :t AND component LIKE :c")
    async with sessionmaker()() as s:
        return int((await s.execute(q, {"t": since, "c": like})).scalar() or 0)


async def _live_pages(c: AcqChange, since: datetime) -> list[Any]:
    """Pages the new version read since acceptance (parsers); other kinds are judged on blamed signals."""
    if c.object_kind != "parser":
        return []
    async with sessionmaker()() as s:
        ids = [str(i) for (i,) in (await s.execute(
            select(PageSnapshot.id).where(PageSnapshot.parser_version == c.to_version, PageSnapshot.fetched_at >= since)
            .order_by(PageSnapshot.fetched_at.desc()).limit(MAX_PAGES))).all()]  # fmt: skip
    return await evaluate.refs(ids)


def accepted_at(c: AcqChange) -> datetime:
    at = ((c.gates or {}).get("accept") or {}).get("at")
    return datetime.fromisoformat(at) if at else (c.created_at or datetime.now(UTC))


async def check(change_id: str, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    c = await journal.load(change_id)
    if c is None or c.status != "watch" or c.closed_at is not None:
        return {"skipped": "not in watch"}
    at = accepted_at(c)
    days = max(0.0, (now - at).total_seconds() / 86400)
    baseline = journal.metrics_of(c, "shadow") or journal.metrics_of(c, "replay") or gates.Metrics()
    rs = await _live_pages(c, at)
    current = gates.Metrics()
    if rs:
        try:
            _, current = await evaluate.measure(c, rs)
        except evaluate.NoMeasure:
            current = gates.Metrics()
    wrong = await wrong_signals(c, at)
    verdict = gates.watch_verdict(baseline, current, wrong, days, replay_gate.cfg())
    async with sessionmaker()() as s:
        exp = await s.get(AcqExperiment, change_id)
        if exp is not None:
            exp.daily = {**(exp.daily or {}), now.date().isoformat(): {**current.as_dict(), "wrong_signals": wrong}}
            await s.commit()
    if verdict.verdict == "rollback":
        await journal.rollback(change_id, "system", verdict, current, wrong_signals=wrong, days=days)
        await _doctor_again(c, now)
    elif verdict.verdict == "keep":
        await journal.keep(change_id, verdict, current)
    log.info("gate.watch change=%s verdict=%s %s", change_id, verdict.verdict, verdict.reason)
    return {"change_id": change_id, "verdict": verdict.verdict, "reasons": list(verdict.reasons), "wrong": wrong,
            "pages": current.pages}  # fmt: skip


async def _doctor_again(c: AcqChange, now: datetime) -> None:
    """A rolled-back repair leaves the parser degraded: the doctor tries again tomorrow (the reverted spec itself is
    refused without newer evidence, see agents/levers.py)."""
    if c.object_kind != "parser" or not c.from_version or c.author != "agent:parser_doctor":
        return
    from datetime import time, timedelta  # noqa: PLC0415

    from automind.acquisition.worker import queue  # noqa: PLC0415

    day = (now + timedelta(days=1)).date()
    payload = {"version": c.from_version, "change_id": (c.evidence or {}).get("drift_change"), "after_rollback": c.id}
    await queue.enqueue("parser_doctor", payload,
                        dedupe_key=f"doctor:{c.from_version}:{day.isoformat()}",
                        run_at=datetime.combine(day, time(3, 45), tzinfo=UTC))  # fmt: skip


async def check_all(now: datetime | None = None) -> dict[str, str]:
    async with sessionmaker()() as s:
        ids = [str(i) for (i,) in (await s.execute(select(AcqChange.id).where(
            AcqChange.status == "watch", AcqChange.closed_at.is_(None)))).all()]  # fmt: skip
    return {i: (await check(i, now)).get("verdict", "skipped") for i in ids}
