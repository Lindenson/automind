"""Application ports: the interfaces the application layer depends on (constitution V, IX).

Infrastructure provides real implementations; tests provide fakes (tests/fakes). Application code
receives a `Ports` bundle instead of importing infrastructure, so graph workflows can run with a
scripted LLM and fixture search.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from automind.domain.ladder import Generation
from automind.shared.contracts.config import Reference
from automind.shared.contracts.llm import LLM


class TurnBusy(RuntimeError):
    """A turn of this chat is already running: the turn store checks it under a per-chat lock."""


class VersionConflict(RuntimeError):
    """The case changed since it was read (spec 007 J, T076): re-read and apply again."""

    def __init__(self, current: int) -> None:
        super().__init__(f"the case is at version {current}")
        self.current = current


class CaseRepo(Protocol):
    async def latest(self, chat_id: str) -> tuple[int, dict[str, Any] | None, str | None]: ...

    async def save_version(self, chat_id: str, data: dict[str, Any], changed_by: str, change_log: list[str]) -> int: ...


class TurnRepo(Protocol):
    async def start(self, chat_id: str, user_message_id: str | None, case_version: int) -> Any: ...

    async def update(self, turn_id: str, **values: Any) -> None: ...

    async def get(self, turn_id: str) -> Any | None: ...

    async def active(self, chat_id: str) -> Any | None: ...

    async def last_report_fingerprint(self, chat_id: str) -> str | None: ...

    async def running(self) -> list[Any]: ...


class EventBus(Protocol):
    async def publish(self, chat_id: str, turn_id: str | None, type_: str, payload: dict[str, Any]) -> int: ...


class CatalogRepo(Protocol):
    async def find(self, make: str, model: str, generation: str | None, year: int | None) -> list[Any]: ...


class JobRepo(Protocol):
    async def create(self, chat_id: str, turn_id: str, variant_id: str, area: str, round_: int) -> Any: ...

    async def mark(self, job_id: str, status: str, **values: Any) -> None: ...

    async def for_turn(self, turn_id: str) -> list[Any]: ...

    async def get(self, job_id: str) -> Any | None: ...

    async def skip_open(self, turn_id: str, reason: str = "cancelled") -> int: ...


class MessageRepo(Protocol):
    async def history(self, chat_id: str) -> list[Any]: ...


class Estimator(Protocol):
    """Research cost estimate (FR-041): jobs are (variant_id, area)."""

    async def estimate(self, jobs: list[tuple[str, str]], rounds: int) -> float: ...


class Clock(Protocol):
    def now(self) -> datetime: ...


class VersionsStore(Protocol):
    """The shared cache of the versions of model generations (spec 008 US6, table `model_versions`)."""

    async def get(self, make: str, model: str, generation: str | None, year: int | None, new: bool,
                  ttl_days: int) -> Generation | None: ...  # fmt: skip

    async def put(self, g: Generation) -> None: ...


class OutcomeStore(Protocol):
    """Turn outcomes and feedback (spec 010 US1, US2; tables `turn_outcomes`, `feedback`)."""

    async def record(self, turn_id: str, chat_id: str, **fields: Any) -> None: ...

    async def patch_previous(self, chat_id: str, turn_id: str, relation: str | None,
                             signals: dict[str, float]) -> None: ...  # fmt: skip

    async def add_signal(self, turn_id: str, key: str, amount: float = 1.0) -> None: ...

    async def feedback(self, chat_id: str, kind: str, **fields: Any) -> str: ...


class AcquisitionPort(Protocol):
    """The acquisition engine bound to its ports (spec 011 contracts/acquire.md, strangler S8): the chat orders data
    and identity look-ups here and never searches, fetches or reads pages itself. Graph tests fake it. The models are
    those of `automind.acquisition.api`; its port-free read model is called on that module directly."""

    async def acquire(self, req: Any, emit: Callable[[str, str], Awaitable[None]] | None = None) -> Any: ...

    async def lineup(self, make: str, *, official: str | None, max_pages: int, market: str = "ES") -> Any: ...

    async def versions(self, make: str, model: str, generation: str | None, *, year: int | None, queries: list[str],
                       limits: dict[str, Any], done: set[str] | None = None,
                       market: str = "ES") -> Any: ...  # fmt: skip

    async def generation_hints(self, query: str, *, lineup_url: str | None = None, user_url: str | None = None,
                               prices: bool = False, market: str = "ES") -> list[Any]: ...  # fmt: skip

    async def dataset_versions(self, make: str, model: str, generation: str | None = None, fuel: str | None = None,
                               year_from: int | None = None) -> list[Any]: ...  # fmt: skip


Emit = Callable[[str, dict[str, Any]], Awaitable[None]]
"""Progress/event callback: (type, payload)."""


@dataclass
class Ports:
    llm: LLM
    cases: CaseRepo
    turns: TurnRepo
    events: EventBus
    jobs: JobRepo
    clock: Clock
    ref: Reference
    messages: MessageRepo
    estimator: Estimator
    acquisition: AcquisitionPort | None = None  # spec 011 S8: the engine (search, pages, readers live there)
    feasibility: Any = None  # application.feasibility.FeasibilityStore (spec 003 US3)
    # async (ports, make, market='ES') -> application.lineup.Lineup | None (spec 005); None: no lookup
    lineup: Any = None
    # spec 006 US5: market facts (incentives): upsert(rows, evidence_id), done() -> datetime | None, load(); None: none
    market_facts: Any = None
    # spec 007 US7: async () -> [(make, domain.intake.LineupModel)] sold in ES, known without a search; None: none
    models_on_sale: Any = None
    versions: VersionsStore | None = None  # spec 008: versions of model generations; None: no ladder (fallback)
    outcomes: OutcomeStore | None = None  # spec 010 US1/US2; None: not recorded (test fakes)
    metrics: Any = None  # spec 010: inc(name, **labels) for Prometheus counters; None: not counted
    registry: Any = None  # spec 010 US6-US8: acquisition.registry.api.RegistryPort; None: config order only
