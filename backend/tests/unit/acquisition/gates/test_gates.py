"""The journal and the replay gate over fakes (spec 011 US5): a lever refusal and an open change are refusals, a
transition another task won leaves the change as it is, a rollback journals the restore, and a change without a
measure waits for evidence and is abandoned after `wait_days`."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any, Unpack

import pytest
from pydantic import BaseModel

from automind.acquisition.agents import levers
from automind.acquisition.agents.levers import LeverState, RuleProposal
from automind.acquisition.domain import gates, relevance_audit
from automind.acquisition.gates.application.journal import ChangeJournal
from automind.acquisition.gates.application.measure_ports import Charge, MetricsPair, NoMeasure
from automind.acquisition.gates.application.ports import ChangeFields
from automind.acquisition.gates.application.replay_gate import ReplayGate
from automind.acquisition.gates.domain.change import Change
from automind.acquisition.gates.domain.relevance_change import RelevanceResult
from automind.acquisition.snapshots.store import SnapshotRef
from automind.shared.contracts.json import JsonObject
from automind.shared.contracts.llm import LLM

T0 = datetime(2026, 11, 1, 3, tzinfo=UTC)


class _Store:
    def __init__(self) -> None:
        self.rows: dict[str, Change] = {}
        self.restores: list[str] = []
        self.open_objects: set[tuple[str, str]] = set()

    async def load(self, change_id: str) -> Change | None:
        return self.rows.get(change_id)

    async def propose(self, change_id: str, agent: str, proposal: BaseModel, reason: str, evidence: JsonObject,
                      cost_eur: float, now: datetime) -> Change | None:  # fmt: skip
        key = getattr(proposal, "path", "")
        if ("rule", key) in self.open_objects:
            return None
        self.open_objects.add(("rule", key))
        c = Change(change_id, f"agent:{agent}", "rule", key, "1", "2", "proposed", evidence=evidence, created_at=now,
                   explanation="proposed")  # fmt: skip
        self.rows[change_id] = c
        return c

    async def claim(self, change_id: str, expected: tuple[str, ...], status: str) -> Change | None:
        c = self.rows[change_id]
        if c.status not in expected or c.closed_at is not None:
            return None
        self.rows[change_id] = replace(c, status=status)
        return self.rows[change_id]

    async def update(self, change_id: str, **fields: Unpack[ChangeFields]) -> Change:
        kept = {k: v for k, v in fields.items() if k in Change.__dataclass_fields__}
        self.rows[change_id] = replace(self.rows[change_id], **kept)
        return self.rows[change_id]

    async def journal_restore(self, of: Change, by: str, explanation: str, evidence: JsonObject, now: datetime) -> str:
        self.restores.append(of.id)
        return "restore-1"

    async def ids_in(self, status: str) -> list[str]:
        return [c.id for c in self.rows.values() if c.status == status]

    async def in_shadow(self, kinds: tuple[str, ...]) -> list[Change]:
        return []

    async def wrong_signals(self, component_like: str, since: datetime) -> int:
        return 0


class _Objects:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def activate(self, c: Change, now: datetime) -> JsonObject:
        self.calls.append("activate")
        return {"id": None}

    async def restore(self, c: Change) -> None:
        self.calls.append("restore")

    async def drop(self, c: Change) -> None:
        self.calls.append("drop")


class _Levers:
    async def state(self) -> LeverState:
        return LeverState(agents_cfg={})  # type: ignore[call-arg]  # the lever checks are replaced in these tests


class _Queue:
    def __init__(self) -> None:
        self.tasks: list[tuple[str, str]] = []

    async def enqueue(self, kind: str, payload: JsonObject, *, dedupe_key: str,
                      run_at: datetime | None = None) -> str | None:  # fmt: skip
        self.tasks.append((kind, dedupe_key))
        return dedupe_key


class _Events:
    def __init__(self) -> None:
        self.counted: list[tuple[str, str]] = []

    def count(self, agent: str, status: str) -> None:
        self.counted.append((agent, status))

    def in_shadow(self, kind: str) -> bool:
        return False

    async def refresh_overrides(self) -> None:
        return None


class _Clock:
    def __init__(self, now: datetime = T0) -> None:
        self.t = now

    def now(self) -> datetime:
        return self.t


def _journal(store: _Store, objects: _Objects | None = None, *, events: _Events | None = None,
             queue: _Queue | None = None) -> ChangeJournal:  # fmt: skip
    return ChangeJournal(store, objects or _Objects(), _Levers(), queue or _Queue(), events or _Events(), _Clock())


async def test_a_lever_refusal_and_an_open_change_are_refusals(monkeypatch: pytest.MonkeyPatch) -> None:
    refusals = iter([[], [], ["frozen"]])
    monkeypatch.setattr(levers, "validate", lambda agent, proposal, state: next(refusals))
    store, events, queue = _Store(), _Events(), _Queue()
    j = _journal(store, events=events, queue=queue)
    cid = await j.propose("rule_auditor", RuleProposal(path="plausibility.x", value=2), "why")
    assert cid is not None and queue.tasks == [("gate_replay", f"gate_replay:{cid}")]
    assert await j.propose("rule_auditor", RuleProposal(path="plausibility.x", value=3), "again") is None
    assert await j.propose("rule_auditor", RuleProposal(path="plausibility.y", value=3), "frozen") is None
    assert events.counted == [("rule_auditor", "proposed"), ("rule_auditor", "refused"), ("rule_auditor", "refused")]


async def test_a_transition_another_task_won_changes_nothing() -> None:
    store, objects = _Store(), _Objects()
    store.rows["c1"] = Change("c1", "agent:rule_auditor", "rule", "plausibility.x", "1", "2", "kept", closed_at=T0)
    j = _journal(store, objects)
    got = await j.reject("c1", "replay", gates.Verdict("fail", ("worse",)))
    assert got == store.rows["c1"] and got is not None and got.status == "kept" and objects.calls == []


async def test_a_rollback_restores_and_journals_the_restore() -> None:
    store, objects = _Store(), _Objects()
    store.rows["c1"] = Change("c1", "agent:parser_doctor", "parser", "km77", "km77@v4", "km77@v5", "watch")
    c = await _journal(store, objects).rollback("c1", "system", gates.Verdict("rollback", ("3 wrong values",)),
                                                wrong_signals=3, days=2)  # fmt: skip
    assert c is not None and c.status == "rolled_back" and c.closed_at == T0
    assert objects.calls == ["restore"] and store.restores == ["c1"]
    assert "km77 parser v5 rolled back: 3 wrong values blamed to v5 in 2 days; previous v4 restored" in c.explanation


class _NoMeasure:
    async def corpus(self, c: Change, now: datetime) -> list[SnapshotRef]:
        return []

    async def refs(self, ids: list[str]) -> list[SnapshotRef]:
        return []

    async def live_pages(self, c: Change, since: datetime) -> list[SnapshotRef]:
        return []

    async def measure(self, c: Change, refs: list[SnapshotRef], *, since: datetime | None = None,
                      llm: LLM | None = None, charge: Charge | None = None) -> MetricsPair:  # fmt: skip
        raise NoMeasure("no offline measure for plausibility.x")

    async def degraded(self, c: Change) -> bool:
        return False


class _Experiments:
    def __init__(self) -> None:
        self.decided: list[str] = []

    async def pin(self, change_id: str, phase: str, ids: list[str], now: datetime) -> None: ...
    async def decide(self, change_id: str, decision: str, now: datetime) -> None:
        self.decided.append(decision)

    async def start_shadow(self, change_id: str, now: datetime, ends: datetime) -> None: ...
    async def add_page(self, change_id: str, snapshot_id: str) -> None: ...
    async def corpus(self, change_id: str) -> tuple[list[str], datetime | None]:
        return [], None

    async def record(self, change_id: str, old: gates.Metrics, new: gates.Metrics) -> None: ...
    async def record_day(self, change_id: str, day: str, values: JsonObject) -> None: ...


class _Relevance:
    async def measure(self, c: Change, since: datetime, until: datetime, *, limit: int, llm: LLM | None = None,
                      charge: Charge | None = None) -> RelevanceResult:  # fmt: skip
        raise AssertionError("not a relevance change")


class _Budget:
    async def charge(self, eur: float) -> None: ...
    async def remaining(self) -> float:
        return 1.0


class _Budgets:
    def of(self, agent: str) -> Any:
        return _Budget()


async def test_no_measure_waits_then_abandons() -> None:
    store, queue, exps = _Store(), _Queue(), _Experiments()
    store.rows["c1"] = Change("c1", "agent:rule_auditor", "rule", "plausibility.x", "1", "2", "proposed", created_at=T0)
    j = _journal(store, queue=queue)
    gate = ReplayGate(j, exps, _NoMeasure(), _Relevance(), _Budgets(), queue, _Events(), _Clock(), gates.GateConfig(),
                      relevance_audit.RelevanceGateConfig())  # fmt: skip
    first = await gate.run("c1", now=T0 + timedelta(days=1))
    assert first["verdict"] == "insufficient_evidence" and store.rows["c1"].status == "replay"
    assert queue.tasks == [("gate_replay", "gate_replay:c1:2026-11-03")]
    last = await gate.run("c1", now=T0 + timedelta(days=8))
    assert last["verdict"] == "abandon" and store.rows["c1"].status == "abandoned" and exps.decided == ["abandoned"]
