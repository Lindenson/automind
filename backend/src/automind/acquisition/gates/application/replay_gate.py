"""The replay gate (spec 011 US5 T101, research R14), worker task `gate_replay:<change_id>`.

The corpus is the object's stored pages of the 30 days up to the change's `as_of`, extended by the days it waited,
pinned while the gates run. Old and new versions run on the same pages (`measure_ports.Measure`); for a redesign
the yield is measured on the pages fetched since `changed_on`. `domain/gates.replay_verdict` decides: pass → shadow;
fail → rejected; insufficient evidence → the task re-queues for tomorrow 03:00, up to `wait_days`, then abandoned.
A relevance keyword change is measured by re-judging the stored pages that name the moved words and decided by
`domain/relevance_audit`.

Errors: a store failure propagates (the worker retries); `NoMeasure` is a verdict (wait, then abandon); an exhausted
budget stops the task (the budget's error propagates, the change stays in replay)."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, time, timedelta

from automind.acquisition.domain import gates, relevance_audit
from automind.acquisition.gates.application.journal import ChangeJournal
from automind.acquisition.gates.application.measure_ports import Budget, Budgets, Measure, NoMeasure, RelevanceMeasure
from automind.acquisition.gates.application.ports import Clock, Experiments, GateEvents, TaskQueue
from automind.acquisition.gates.application.settle import settle
from automind.acquisition.gates.domain import relevance_change
from automind.acquisition.gates.domain.change import Change, day_of, waited_days
from automind.shared.contracts.json import JsonObject
from automind.shared.contracts.llm import LLM

log = logging.getLogger(__name__)
_AWAITING_REPLAY = frozenset({gates.ChangeStatus.PROPOSED, gates.ChangeStatus.REPLAY})
RETRY_AT = time(3, 0)  # an insufficient replay is tried again the next day at this time (UTC)
Measured = tuple[gates.Metrics, gates.Metrics, gates.Verdict, list[str], JsonObject]


class ReplayGate:
    """The replay gate over the journal, the experiments, the measures, the budgets, the queue and the config."""

    def __init__(self, journal: ChangeJournal, experiments: Experiments, measure: Measure, relevance: RelevanceMeasure,
                 budgets: Budgets, queue: TaskQueue, events: GateEvents, clock: Clock, cfg: gates.GateConfig,
                 relevance_cfg: relevance_audit.RelevanceGateConfig) -> None:  # fmt: skip
        self.journal, self.experiments, self.measure, self.relevance = journal, experiments, measure, relevance
        self.agent_budgets, self.queue, self.events, self.clock = budgets, queue, events, clock
        self.cfg, self.relevance_cfg = cfg, relevance_cfg

    async def run(self, change_id: str, *, llm: LLM | None = None, budget: Budget | None = None,
                  now: datetime | None = None) -> JsonObject:  # fmt: skip
        """Measure the change on its corpus and move it on (see the module docstring); returns what was decided."""
        now = now or self.clock.now()
        c = await self.journal.load(change_id)
        if c is None or c.status not in _AWAITING_REPLAY or not c.open:
            return {"skipped": "not waiting for replay"}
        budget = budget or self.agent_budgets.of(c.agent)
        measured = (await self._relevance(c, now, llm, budget) if relevance_change.applies(c)
                    else await self._pages(c, now, llm, budget))  # fmt: skip
        old, new, verdict, ids, extra = measured
        if verdict.verdict == gates.GateVerdict.PASS:
            await self.journal.advance(change_id, "shadow", "replay", verdict, old, new, {"corpus": len(ids), **extra})
            await self.experiments.pin(change_id, "shadow", [], now)  # the shadow phase collects its own live pages
            await self.experiments.start_shadow(change_id, now, now + timedelta(days=self.cfg.shadow_max_days))
            await self.events.refresh_overrides()  # live readers of this process feed the shadow at once
        elif verdict.verdict in (gates.GateVerdict.FAIL, gates.GateVerdict.ABANDON):
            await settle(self.journal, self.experiments, change_id, "replay", verdict, old, new, extra, now)
        else:  # insufficient evidence: wait for prefetch to gather pages, try again tomorrow
            await self.journal.advance(change_id, "replay", "replay", verdict, old, new, {"corpus": len(ids), **extra})
            await self._retry_tomorrow(c, now)
        log.info("gate.replay change=%s verdict=%s %s", change_id, verdict.verdict, verdict.reason)
        return {"change_id": change_id, "pages": len(ids), "verdict": verdict.verdict, "reasons": list(verdict.reasons),
                "old": old.as_dict(), "new": new.as_dict(), **extra}  # fmt: skip

    async def _pages(self, c: Change, now: datetime, llm: LLM | None, budget: Budget) -> Measured:
        """Old and new versions on the corpus; no measure for the kind is a wait (then abandon)."""
        refs = await self.measure.corpus(c, now)
        ids = [r.id for r in refs]
        await self.experiments.pin(c.id, "replay", ids, now)
        waited = waited_days(c, now)
        try:
            old, new = await self.measure.measure(c, refs, since=day_of(c.evidence.get("changed_on")), llm=llm,
                                                  charge=budget.charge)  # fmt: skip
            verdict = gates.replay_verdict(old, new, self.cfg, degraded=await self.measure.degraded(c),
                                           waited_days=waited)  # fmt: skip
        except NoMeasure as e:
            old = new = gates.Metrics()
            verdict = gates.Verdict(
                gates.GateVerdict.ABANDON if waited >= self.cfg.wait_days else gates.GateVerdict.INSUFFICIENT_EVIDENCE,
                (str(e),),
            )
        return old, new, verdict, ids, {}

    async def _relevance(self, c: Change, now: datetime, llm: LLM | None, budget: Budget) -> Measured:
        """A relevance keyword change: the relevance stage re-run on the stored pages of its window."""
        rc = self.relevance_cfg
        as_of = day_of(c.evidence.get("as_of")) or now
        res = await self.relevance.measure(c, as_of - timedelta(days=rc.window_days), now, limit=rc.max_pages, llm=llm,
                                           charge=budget.charge)  # fmt: skip
        await self.experiments.pin(c.id, "replay", res.snapshot_ids, now)
        verdict = relevance_audit.relevance_replay_verdict(res.measure, rc, wait_days=self.cfg.wait_days,
                                                           waited_days=waited_days(c, now))  # fmt: skip
        return res.old, res.new, verdict, res.snapshot_ids, {"relevance": res.measure.as_dict()}

    async def _retry_tomorrow(self, c: Change, now: datetime) -> None:
        day = (now + timedelta(days=1)).date()
        await self.queue.enqueue("gate_replay", {"change_id": c.id, "agent": c.agent},
                                 dedupe_key=f"gate_replay:{c.id}:{day.isoformat()}",
                                 run_at=datetime.combine(day, RETRY_AT, tzinfo=UTC))  # fmt: skip
