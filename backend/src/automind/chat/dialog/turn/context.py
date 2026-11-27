"""What every graph node receives through LangGraph's runtime context: the ports, the turn, its budget and the case.

Built by the turn execution for each run of the graph (`ainvoke`: a new turn, a resume, a restart); nodes import it
from here (never from the runner). Events a node publishes (`status`, `progress`, any `emit`) go to the chat's event
bus under this turn. The case file is read once per run (spec 014 D3): `case()` reads it on first use, `save_case`
writes it with the version it was read at and keeps the cache current; nothing else writes the case during a run.
The last report's fingerprint is read once per run too (spec 015 T211): a report ends the turn, so no policy pass
of the same run sees a newer one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from automind.chat.application.ports import Ports, VersionConflict
from automind.chat.application.services.report.blocks import car_view
from automind.chat.application.services.research.contracts import GridCell
from automind.chat.dialog.turn.cached import Cached
from automind.chat.domain.case import CaseFile
from automind.shared.contracts.json import JsonObject
from automind.shared.metering.usage import TurnBudget


@dataclass(frozen=True)
class StoredCase:
    """The case file as the store holds it: its version and its JSON (None: the chat has no case yet)."""

    version: int
    data: JsonObject | None


@dataclass
class TurnContext:
    """The ports, the chat and turn ids, the budget all usage of this run is charged to, and the run's case."""

    ports: Ports
    chat_id: str
    turn_id: str
    budget: TurnBudget
    _case: Cached[StoredCase] = field(init=False, repr=False)
    _fingerprint: Cached[str | None] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._case = Cached(self._read_case)
        self._fingerprint = Cached(lambda: self.ports.turns.last_report_fingerprint(self.chat_id))

    async def emit(self, type_: str, payload: dict[str, Any]) -> int:
        """Publish an event of this turn; returns its sequence number in the chat."""
        return await self.ports.events.publish(self.chat_id, self.turn_id, type_, payload)

    async def status(self, stage: str, text: str, **extra: Any) -> None:
        """A progress line for the user ("understanding", "researching", …)."""
        await self.emit("status", {"stage": stage, "text": text, **extra})

    async def progress(self, cell: GridCell) -> None:
        """A cell of the research grid (the research service's `ResearchEvents`)."""
        await self.emit("progress", dict(cell))

    async def case(self) -> CaseFile:
        """The chat's case file (an empty one when there is none): read from the store on the run's first use, then
        from the cache. Every call returns a new object, so a node may change it freely before `save_case`.
        Raises `StoreUnavailable` when the store cannot be read."""
        stored = await self._case.get()
        return CaseFile.model_validate(stored.data) if stored.data else CaseFile()

    async def case_version(self) -> int:
        """The case version this run last read or wrote (0: no case yet)."""
        return (await self._case.get()).version

    async def last_report_fingerprint(self) -> str | None:
        """The fingerprint of the chat's last report (None: no report yet), read from the store on the run's first
        use, then from the cache. Raises `StoreUnavailable` when the store cannot be read."""
        return await self._fingerprint.get()

    async def save_case(self, case: CaseFile, changes: list[str], *, publish: bool = True) -> int:
        """Save `case` as the next version after the one this run read (`changes`: its change log) and, when
        `publish`, tell the client (`case_file` event). Returns the new version; the cache holds what was saved.
        Raises `VersionConflict` when the case moved on since it was read (the cache is dropped, so the next
        `case()` reads afresh; `@node` then runs the node once more) and `StoreUnavailable` from the store."""
        expected = await self.case_version()
        data = case.model_dump(mode="json")
        try:
            version = await self.ports.cases.save_version(self.chat_id, data, "hub", changes, expected=expected)
        except VersionConflict:
            self._case.forget()
            raise
        self._case.put(StoredCase(version, _as_read(data)))
        if publish:
            await self.emit("case_file", {"version": version, "case": await car_view.case_payload(case),
                                          "changes": changes})  # fmt: skip
        return version

    async def _read_case(self) -> StoredCase:
        version, data, _ = await self.ports.cases.latest(self.chat_id)
        return StoredCase(version, data)


def _as_read(data: JsonObject) -> JsonObject:
    """`data` as a read of the store gives it back: the store (Postgres `jsonb`) orders the keys of every object by
    length, then bytes. A cached case thus iterates its dicts exactly like the read it replaces."""
    return {k: _as_read_value(data[k]) for k in sorted(data, key=lambda k: (len(k.encode()), k.encode()))}


def _as_read_value(value: object) -> object:
    if isinstance(value, dict):
        return _as_read(value)
    if isinstance(value, list):
        return [_as_read_value(v) for v in value]
    return value
