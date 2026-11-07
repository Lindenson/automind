"""The change journal (spec 011 US5 T100, FR-019, research R15): every agent change from proposal to its end.

`propose` checks the proposal against the levers, creates the candidate object and the `proposed` row in one
transaction (one open change per object) and queues `gate_replay:<id>`. The transitions — `advance` (replay,
shadow), `accept` (the new object live, the watch starts), `keep`, `reject`, `abandon`, `rollback` (the previous
object restored, a `system` row journals it) — record the gate's verdict and metrics and the one-sentence
explanation, and count `automind_acq_changes_total{agent,status}`. A transition claims the change atomically: when
another task moved it first, nothing is written and the change is returned as it is.

Errors: `GateStoreUnavailable` propagates (the worker retries the task); a lever refusal or an open change on the
object is not an error: `propose` returns None and counts it as refused."""

from __future__ import annotations

import logging
import uuid
from dataclasses import replace

from pydantic import BaseModel

from automind.acquisition.agents import levers
from automind.acquisition.domain import gates
from automind.acquisition.gates.application.ports import ChangeStore, Clock, GateEvents, LeverStates, Objects, TaskQueue
from automind.acquisition.gates.domain.change import OPEN, Change, metrics_of, sentence, with_gate
from automind.shared.contracts.json import JsonObject

log = logging.getLogger(__name__)


class ChangeJournal:
    """The journal over its store, the candidate objects, the lever state, the queue, the events and the clock."""

    def __init__(self, store: ChangeStore, objects: Objects, levers_now: LeverStates, queue: TaskQueue,
                 events: GateEvents, clock: Clock) -> None:  # fmt: skip
        self.store, self.objects, self.levers_now = store, objects, levers_now
        self.queue, self.events, self.clock = queue, events, clock

    async def load(self, change_id: str) -> Change | None:
        """The change, None when there is none."""
        return await self.store.load(change_id)

    async def check(self, agent: str, proposal: BaseModel) -> list[str]:
        """Every reason the levers refuse this proposal now; [] = it may be proposed."""
        return levers.validate(agent, proposal, await self.levers_now.state())

    async def propose(self, agent: str, proposal: BaseModel, reason: str, evidence: JsonObject | None = None, *,
                      cost_eur: float = 0.0) -> str | None:  # fmt: skip
        """Journal a proposal and queue its replay gate; its id, None when refused (see the module docstring)."""
        errs = await self.check(agent, proposal)
        if errs:
            log.info("journal.refused agent=%s %s", agent, "; ".join(errs))
            self.events.count(agent, "refused")
            return None
        change_id = new_id()
        c = await self.store.propose(change_id, agent, proposal, reason, dict(evidence or {}), cost_eur,
                                     self.clock.now())  # fmt: skip
        if c is None:
            log.info("journal.open_change agent=%s %s", agent, levers.object_of(proposal))
            self.events.count(agent, "refused")
            return None
        self.events.count(agent, "proposed")
        log.info("journal.proposed %s", c.explanation, extra={"event": "change.proposed", "change_id": change_id})
        await self.queue.enqueue("gate_replay", {"change_id": change_id, "agent": agent},
                                 dedupe_key=f"gate_replay:{change_id}")  # fmt: skip
        return change_id

    async def advance(self, change_id: str, phase: str, gate: str, verdict: gates.Verdict,
                      old: gates.Metrics | None = None, new: gates.Metrics | None = None,
                      extra: JsonObject | None = None) -> Change | None:  # fmt: skip
        """Record a gate result and move the change to `phase` (replay, shadow)."""
        c = await self.store.load(change_id)
        if c is None:
            return None
        c = replace(c, gates=with_gate(c, gate, verdict, old, new, self.clock.now(), extra), status=phase)
        c = await self.store.update(change_id, gates=c.gates, status=phase, explanation=sentence(c, phase),
                                    metrics_before=old.as_dict() if old else c.metrics_before)  # fmt: skip
        self.events.count(c.agent, phase)
        return c

    async def reject(self, change_id: str, gate: str, verdict: gates.Verdict, old: gates.Metrics | None = None,
                     new: gates.Metrics | None = None, extra: JsonObject | None = None) -> Change | None:  # fmt: skip
        """Close the change as rejected at `gate`; its candidate object is dropped."""
        return await self._close(change_id, "rejected", gate, verdict, old, new, extra)

    async def abandon(self, change_id: str, gate: str, verdict: gates.Verdict, old: gates.Metrics | None = None,
                      new: gates.Metrics | None = None, extra: JsonObject | None = None) -> Change | None:  # fmt: skip
        """Close the change as abandoned at `gate` (no evidence in time, or no budget)."""
        return await self._close(change_id, "abandoned", gate, verdict, old, new, extra)

    async def accept(self, change_id: str, verdict: gates.Verdict, old: gates.Metrics, new: gates.Metrics,
                     extra: JsonObject | None = None) -> Change | None:  # fmt: skip
        """Shadow passed: the new object live (the old one superseded, kept for rollback); the watch starts."""
        c = await self.store.claim(change_id, ("shadow",), "watch")
        if c is None:
            return await self.store.load(change_id)
        now = self.clock.now()
        g = with_gate(c, "shadow", verdict, old, new, now, extra)
        g["accept"] = {"at": now.isoformat(), "previous": await self.objects.activate(c, now)}
        c = replace(c, gates=g)
        c = await self.store.update(change_id, gates=g, status="watch", metrics_after=new.as_dict(),
                                    explanation=sentence(c, "accepted"))  # fmt: skip
        self._closed(c, "accepted", logging.INFO)
        return c

    async def keep(self, change_id: str, verdict: gates.Verdict, current: gates.Metrics) -> Change | None:
        """The watch ended without degradation: the change stays."""
        c = await self.store.claim(change_id, ("watch",), "kept")
        if c is None:
            return await self.store.load(change_id)
        c = replace(c, gates=with_gate(c, "watch", verdict, metrics_of(c, "shadow"), current, self.clock.now()))
        c = await self.store.update(change_id, gates=c.gates, status="kept", closed_at=self.clock.now(),
                                    explanation=sentence(c, "kept"))  # fmt: skip
        self.events.count(c.agent, "kept")
        return c

    async def rollback(self, change_id: str, by: str, verdict: gates.Verdict, current: gates.Metrics | None = None,
                       *, wrong_signals: int = 0, days: float | None = None) -> Change | None:  # fmt: skip
        """The previous object restored; the change `rolled_back`, a closed row by `by` journals the restore."""
        c = await self.store.claim(change_id, ("watch",), "rolled_back")
        if c is None:
            return await self.store.load(change_id)
        now = self.clock.now()
        c = replace(c, gates=with_gate(c, "watch", verdict, metrics_of(c, "shadow"), current, now))
        await self.objects.restore(c)
        explanation = sentence(c, "rolled_back", verdict=verdict, wrong_signals=wrong_signals, days=days)
        evidence: JsonObject = {"verdict": verdict.as_dict(), "wrong_signals": wrong_signals}
        row = await self.store.journal_restore(c, by, explanation, evidence, now)
        c = await self.store.update(change_id, gates=c.gates, status="rolled_back", closed_at=now, reverted_by=row,
                                    explanation=explanation)  # fmt: skip
        self._closed(c, "rolled_back", logging.WARNING)
        return c

    async def _close(self, change_id: str, status: str, gate: str, verdict: gates.Verdict, old: gates.Metrics | None,
                     new: gates.Metrics | None, extra: JsonObject | None) -> Change | None:  # fmt: skip
        c = await self.store.claim(change_id, OPEN, status)
        if c is None:
            return await self.store.load(change_id)
        now = self.clock.now()
        c = replace(c, gates=with_gate(c, gate, verdict, old, new, now, extra))
        await self.objects.drop(c)
        c = await self.store.update(change_id, gates=c.gates, status=status, closed_at=now,
                                    explanation=sentence(c, status, gate, verdict))  # fmt: skip
        self._closed(c, status, logging.INFO)
        return c

    def _closed(self, c: Change, status: str, level: int) -> None:
        self.events.count(c.agent, status)
        log.log(level, "journal.%s %s", status, c.explanation, extra={"event": f"change.{status}", "change_id": c.id})


def new_id() -> str:
    """A new change id."""
    return str(uuid.uuid4())
