"""The ports of the gates (spec 011 US5): the change journal's store, the candidate objects, the experiments (pinned
corpora), the worker's queue, the journal's events and the lever state. The measures are in `measure_ports`.

Errors: every store raises `GateStoreUnavailable` when its database fails (the task fails and the worker retries
it; each write is one transaction, so a failed one leaves the change as it was)."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, TypedDict, Unpack

from pydantic import BaseModel

from automind.acquisition.agents.levers import LeverState
from automind.acquisition.domain import gates
from automind.acquisition.gates.domain.change import Change
from automind.shared.contracts.json import JsonObject


class GateStoreUnavailable(RuntimeError):
    """A gate store could not read or write (its database); the cause is chained."""


class ChangeFields(TypedDict, total=False):
    """What a journal update may set."""

    gates: JsonObject
    status: str
    explanation: str
    closed_at: datetime
    metrics_before: JsonObject | None
    metrics_after: JsonObject
    reverted_by: str


class ChangeStore(Protocol):
    """The change journal (`acq_changes`) with the candidate objects created beside a proposal."""

    async def load(self, change_id: str) -> Change | None:
        """The change, None when there is none."""
        ...

    async def propose(self, change_id: str, agent: str, proposal: BaseModel, reason: str, evidence: JsonObject,
                      cost_eur: float, now: datetime) -> Change | None:  # fmt: skip
        """The candidate object and the `proposed` row, in one transaction; None when the object already has an
        open change (the partial unique index)."""
        ...

    async def claim(self, change_id: str, expected: tuple[str, ...], status: str) -> Change | None:
        """Move an open change from one of `expected` to `status` atomically; None when another task moved it."""
        ...

    async def update(self, change_id: str, **fields: Unpack[ChangeFields]) -> Change:
        """Set the fields; returns the change as stored."""
        ...

    async def journal_restore(self, of: Change, by: str, explanation: str, evidence: JsonObject,
                              now: datetime) -> str:  # fmt: skip
        """A closed row journalling the restore of `of`'s previous version; returns its id."""
        ...

    async def ids_in(self, status: str) -> list[str]:
        """The open changes in `status`."""
        ...

    async def in_shadow(self, kinds: tuple[str, ...]) -> list[Change]:
        """The open changes of these kinds in shadow."""
        ...

    async def wrong_signals(self, component_like: str, since: datetime) -> int:
        """Wrong truth signals blamed to components matching the pattern since `since`."""
        ...


class Objects(Protocol):
    """The candidate objects behind changes (parser and prompt versions, rule and model overrides)."""

    async def activate(self, c: Change, now: datetime) -> JsonObject:
        """The new object active, the old one superseded, the experiment marked accepted, in one transaction;
        returns what to restore on rollback."""
        ...

    async def restore(self, c: Change) -> None:
        """The previous object back, the new one rejected."""
        ...

    async def drop(self, c: Change) -> None:
        """The candidate rejected (it never went live)."""
        ...


class Experiments(Protocol):
    """The gates' experiments (`acq_experiments`) and their pinned pages."""

    async def pin(self, change_id: str, phase: str, ids: list[str], now: datetime) -> None:
        """The experiment's corpus set to `ids` and pinned; pages dropped from it unpinned."""
        ...

    async def decide(self, change_id: str, decision: str, now: datetime) -> None:
        """The experiment decided; its pages unpinned unless another open experiment holds them."""
        ...

    async def start_shadow(self, change_id: str, now: datetime, ends: datetime) -> None:
        """The shadow phase started: no pages, no metrics yet."""
        ...

    async def add_page(self, change_id: str, snapshot_id: str) -> None:
        """A live page added to the shadow corpus atomically and pinned."""
        ...

    async def corpus(self, change_id: str) -> tuple[list[str], datetime | None]:
        """The experiment's pages and when its phase started."""
        ...

    async def record(self, change_id: str, old: gates.Metrics, new: gates.Metrics) -> None:
        """The latest metrics of both versions."""
        ...

    async def record_day(self, change_id: str, day: str, values: JsonObject) -> None:
        """One day of the watch."""
        ...


class TaskQueue(Protocol):
    """The worker's task queue."""

    async def enqueue(self, kind: str, payload: JsonObject, *, dedupe_key: str,
                      run_at: datetime | None = None) -> str | None:  # fmt: skip
        """A worker task; None when one with this key exists."""
        ...


class GateEvents(Protocol):
    """What the journal tells the rest of the engine: counts and the live overrides."""

    def count(self, agent: str, status: str) -> None:
        """`automind_acq_changes_total{agent,status}`; never fails."""
        ...

    def in_shadow(self, kind: str) -> bool:
        """A change of this object kind is in shadow (the live overrides know it without a query)."""
        ...

    async def refresh_overrides(self) -> None:
        """Live readers of this process pick up the new candidate or active objects at once."""
        ...


class LeverStates(Protocol):
    """The state the lever checks read."""

    async def state(self) -> LeverState:
        """What the lever checks need now (open objects, blocks, frozen parsers and sources, reverted changes)."""
        ...


class Clock(Protocol):
    """The time of the system (a fixed one in tests)."""

    def now(self) -> datetime:
        """Now, timezone-aware."""
        ...
