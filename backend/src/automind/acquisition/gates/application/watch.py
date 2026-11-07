"""The watch after acceptance (spec 011 US5 T103, research R14): the evaluator compares an accepted change's live
metrics and the wrong signals blamed to its new version with the metrics it was accepted on. On degradation the
previous version is restored and journalled ("km77 parser v5 rolled back: 3 wrong values blamed to v5 in 2 days;
previous v4 restored") and a rolled-back parser repair is handed back to the doctor for tomorrow; after
`watch_days` without degradation the change is kept.

Errors: a store failure propagates (the worker retries); `NoMeasure` counts as no live pages."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, time, timedelta

from automind.acquisition.domain import gates
from automind.acquisition.gates.application.journal import ChangeJournal
from automind.acquisition.gates.application.measure_ports import Measure, NoMeasure
from automind.acquisition.gates.application.ports import ChangeStore, Clock, Experiments, TaskQueue
from automind.acquisition.gates.domain.change import Change, accepted_at, component_like, metrics_of
from automind.shared.contracts.json import JsonObject

log = logging.getLogger(__name__)
DOCTOR_AT = time(3, 45)  # a rolled-back repair: the doctor tries again the next day at this time (UTC)
DOCTOR = "agent:parser_doctor"


class Watch:
    """The watch over the journal, its store, the experiments, the measure, the queue, the clock and the config."""

    def __init__(self, journal: ChangeJournal, store: ChangeStore, experiments: Experiments, measure: Measure,
                 queue: TaskQueue, clock: Clock, cfg: gates.GateConfig) -> None:  # fmt: skip
        self.journal, self.store, self.experiments, self.measure = journal, store, experiments, measure
        self.queue, self.clock, self.cfg = queue, clock, cfg

    async def check(self, change_id: str, now: datetime | None = None) -> JsonObject:
        """One day of the watch: keep, roll back, or go on watching."""
        now = now or self.clock.now()
        c = await self.journal.load(change_id)
        if c is None or c.status != "watch" or not c.open:
            return {"skipped": "not in watch"}
        at = accepted_at(c, now)
        days = max(0.0, (now - at).total_seconds() / 86400)
        baseline = metrics_of(c, "shadow") or metrics_of(c, "replay") or gates.Metrics()
        current = await self._live(c, at)
        like = component_like(c)
        wrong = await self.store.wrong_signals(like, at) if like is not None else 0
        verdict = gates.watch_verdict(baseline, current, wrong, days, self.cfg)
        await self.experiments.record_day(
            change_id, now.date().isoformat(), {**current.as_dict(), "wrong_signals": wrong}
        )
        if verdict.verdict == "rollback":
            await self.journal.rollback(change_id, "system", verdict, current, wrong_signals=wrong, days=days)
            await self._doctor_again(c, now)
        elif verdict.verdict == "keep":
            await self.journal.keep(change_id, verdict, current)
        log.info("gate.watch change=%s verdict=%s %s", change_id, verdict.verdict, verdict.reason)
        return {"change_id": change_id, "verdict": verdict.verdict, "reasons": list(verdict.reasons), "wrong": wrong,
                "pages": current.pages}  # fmt: skip

    async def check_all(self, now: datetime | None = None) -> dict[str, str]:
        """Every change in watch, checked."""
        return {i: str((await self.check(i, now)).get("verdict", "skipped")) for i in await self.store.ids_in("watch")}

    async def _live(self, c: Change, since: datetime) -> gates.Metrics:
        """The new version's metrics on the pages it read live since acceptance (none: empty metrics)."""
        refs = await self.measure.live_pages(c, since)
        if not refs:
            return gates.Metrics()
        try:
            return (await self.measure.measure(c, refs))[1]
        except NoMeasure:
            return gates.Metrics()

    async def _doctor_again(self, c: Change, now: datetime) -> None:
        """A rolled-back repair leaves the parser degraded: the doctor tries again tomorrow (the reverted spec itself
        is refused without newer evidence, see agents/levers.py)."""
        if c.object_kind != "parser" or not c.from_version or c.author != DOCTOR:
            return
        day = (now + timedelta(days=1)).date()
        payload: JsonObject = {"version": c.from_version, "change_id": c.evidence.get("drift_change"),
                               "after_rollback": c.id}  # fmt: skip
        await self.queue.enqueue("parser_doctor", payload, dedupe_key=f"doctor:{c.from_version}:{day.isoformat()}",
                                 run_at=datetime.combine(day, DOCTOR_AT, tzinfo=UTC))  # fmt: skip
