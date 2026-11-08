"""The shadow gate (spec 011 US5 T102, research R14): both versions on the next live/prefetch pages while the user
sees the old version's values.

The live parse and extraction stages call `notify_read`/`notify_extracted`, which only queue
`gate_shadow:<change_id>:<snapshot_id>`. The task adds its page to the experiment (pinned), measures both versions on
all its shadow pages and decides with `domain/gates.shadow_verdict`: accept (the new version live), reject, abandon
(no budget, or `shadow.max_days`), or wait. The evaluator's daily `decide_all` ends a shadow on time even without
new pages. A relevance keyword change is measured on the pages the relevance rules judged live since its replay.

Errors: a store failure propagates (the worker retries); `NoMeasure` counts as no pages yet."""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping
from datetime import datetime

from automind.acquisition.domain import gates, relevance_audit
from automind.acquisition.gates.application.journal import ChangeJournal
from automind.acquisition.gates.application.measure_ports import Budget, Budgets, Measure, NoMeasure, RelevanceMeasure
from automind.acquisition.gates.application.ports import ChangeStore, Clock, Experiments, GateEvents, TaskQueue
from automind.acquisition.gates.application.settle import settle
from automind.acquisition.gates.domain import relevance_change
from automind.acquisition.gates.domain.change import Change
from automind.shared.contracts.json import JsonObject
from automind.shared.contracts.llm import LLM
from automind.shared.provenance.versions import parse_key

log = logging.getLogger(__name__)
ALL_KINDS = tuple(gates.ObjectKind)


class ShadowGate:
    """The shadow gate over the journal, its store, the experiments, the measures, the budgets and the config."""

    def __init__(self, journal: ChangeJournal, store: ChangeStore, experiments: Experiments, measure: Measure,
                 relevance: RelevanceMeasure, budgets: Budgets, queue: TaskQueue, events: GateEvents, clock: Clock,
                 cfg: gates.GateConfig, relevance_cfg: relevance_audit.RelevanceGateConfig) -> None:  # fmt: skip
        self.journal, self.store, self.experiments, self.measure = journal, store, experiments, measure
        self.relevance, self.agent_budgets, self.queue, self.events, self.clock = (
            relevance,
            budgets,
            queue,
            events,
            clock,
        )
        self.cfg, self.relevance_cfg = cfg, relevance_cfg

    async def notify_read(self, read: Mapping[str, str]) -> int:
        """Pages a live reader just read (snapshot id → parser version key) queued for parser and rule changes in
        shadow (rule changes re-validate reader rows); returns how many tasks were queued."""
        if not read or not (self.events.in_shadow("parser") or self.events.in_shadow("rule")):
            return 0
        n = 0
        for c in await self.store.in_shadow((gates.ObjectKind.PARSER, gates.ObjectKind.RULE)):
            parser = c.object_kind == gates.ObjectKind.PARSER
            ids = [sid for sid, key in read.items() if _reader(key) == c.object_key] if parser else list(read)
            n += await self._enqueue(c, ids)
        return n

    async def notify_extracted(self, prompt_name: str | None, snapshot_ids: list[str]) -> int:
        """Pages the extractor just read queued for changes of that prompt and of the extractor's model."""
        n = 0
        for c in await self.store.in_shadow(("prompt", "role_model")):
            if (c.object_kind, c.object_key) in (("prompt", prompt_name), ("role_model", "extractor")):
                n += await self._enqueue(c, snapshot_ids)
        return n

    async def run(self, change_id: str, snapshot_id: str | None = None, *, llm: LLM | None = None,
                  budget: Budget | None = None, now: datetime | None = None) -> JsonObject:  # fmt: skip
        """Add one page (when given) to the change's shadow and decide."""
        now = now or self.clock.now()
        c = await self.journal.load(change_id)
        if c is None or c.status != gates.ChangeStatus.SHADOW or not c.open:
            return {"skipped": "not in shadow"}
        budget = budget or self.agent_budgets.of(c.agent)
        if relevance_change.applies(c):
            return await self._relevance(c, now, llm, budget)
        if snapshot_id:
            await self.experiments.add_page(change_id, snapshot_id)
        ids, started = await self.experiments.corpus(change_id)
        refs = await self.measure.refs(ids)
        old = new = gates.Metrics()
        if refs:
            try:
                old, new = await self.measure.measure(c, refs, llm=llm, charge=budget.charge)
            except NoMeasure as e:
                log.info("gate.shadow no measure change=%s: %s", change_id, e)
        verdict = gates.shadow_verdict(old, new, self.cfg, days=_days(started, now),
                                       budget_left=await budget.remaining() > 0,
                                       degraded=await self.measure.degraded(c))  # fmt: skip
        await self._decide(c, verdict, old, new, {}, now, len(refs))
        return {
            "change_id": change_id,
            "pages": len(refs),
            "verdict": verdict.verdict,
            "reasons": list(verdict.reasons),
        }

    async def decide_all(self, now: datetime | None = None) -> dict[str, str]:
        """The evaluator's daily pass: every change in shadow decided on time, even without new pages."""
        return {c.id: str((await self.run(c.id, now=now)).get("verdict", "skipped"))
                for c in await self.store.in_shadow(ALL_KINDS)}  # fmt: skip

    async def _relevance(self, c: Change, now: datetime, llm: LLM | None, budget: Budget) -> JsonObject:
        """The pages judged live since the replay passed (with the old keywords: the user saw that), re-judged."""
        _, started = await self.experiments.corpus(c.id)
        since = started or now
        rc, gc = self.relevance_cfg, self.cfg
        res = await self.relevance.measure(c, since, now, limit=rc.max_pages, llm=llm, charge=budget.charge)
        await self.experiments.pin(c.id, "shadow", res.snapshot_ids, now)
        verdict = relevance_audit.relevance_shadow_verdict(
            res.measure, rc, days=_days(started, now), min_pages=gc.shadow_min_pages,
            decide_days=gc.shadow_decide_days, max_days=gc.shadow_max_days,
            budget_left=await budget.remaining() > 0)  # fmt: skip
        extra: JsonObject = {"relevance": res.measure.as_dict()}
        await self._decide(c, verdict, res.old, res.new, extra, now, res.measure.pages)
        return {"change_id": c.id, "pages": res.measure.pages, "verdict": verdict.verdict,
                "reasons": list(verdict.reasons), **extra}  # fmt: skip

    async def _decide(self, c: Change, verdict: gates.Verdict, old: gates.Metrics, new: gates.Metrics,
                      extra: JsonObject, now: datetime, pages: int) -> None:  # fmt: skip
        await self.experiments.record(c.id, old, new)
        if verdict.verdict in gates.CLOSING:
            await settle(self.journal, self.experiments, c.id, "shadow", verdict, old, new, extra, now)
            if verdict.verdict == gates.GateVerdict.PASS:
                await self.events.refresh_overrides()
        log.info("gate.shadow change=%s pages=%d verdict=%s %s", c.id, pages, verdict.verdict, verdict.reason)

    async def _enqueue(self, c: Change, snapshot_ids: Iterable[str]) -> int:
        n = 0
        for sid in snapshot_ids:
            got = await self.queue.enqueue("gate_shadow", {"change_id": c.id, "snapshot_id": sid, "agent": c.agent},
                                           dedupe_key=f"gate_shadow:{c.id}:{sid}")  # fmt: skip
            n += got is not None
        return n


def _days(started: datetime | None, now: datetime) -> float:
    return max(0.0, (now - (started or now)).total_seconds() / 86400)


def _reader(key: str) -> str | None:
    try:
        return parse_key(key)[0]
    except ValueError:
        return None
