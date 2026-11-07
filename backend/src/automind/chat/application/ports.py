"""Application ports: the interfaces the application layer depends on (constitution V, IX).

Infrastructure provides the implementations (`chat.infrastructure.adapters.live_ports`); tests provide fakes. The
application receives a `Ports` bundle and never imports infrastructure, so a graph runs with a scripted LLM and
fixture search. A store returns records of this module (`TurnRecord`, `JobRecord`, `MessageRecord`), never rows
of the database.

Errors, the same for every store: `StoreUnavailable` when its database cannot be reached or a statement fails
(the turn fails; it resumes from its checkpoint, where finished research is reused), `TurnBusy` when a turn of
the chat already runs, `VersionConflict` when the case moved on since it was read. No driver exception leaves a
store.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Literal, Protocol, TypedDict, Unpack

from automind.acquisition.api import (
    AcquireRequest,
    AcquireResult,
    DatasetVersion,
    LineupRead,
    VersionsRead,
    WebHint,
)
from automind.chat.domain.identification.ladder import Generation
from automind.chat.domain.intake import LineupModel
from automind.shared.contracts.config import Reference
from automind.shared.contracts.json import JsonObject
from automind.shared.contracts.llm import LLM

if TYPE_CHECKING:
    from automind.chat.application.services.feasibility.feasibility import FeasibilityStore
    from automind.chat.application.services.identification.contracts import LineupLookup

TurnStatus = Literal["RUNNING", "WAITING_CONFIRMATION", "DONE", "CANCELLED", "FAILED"]
JobStatus = Literal["PENDING", "RUNNING", "DONE", "FAILED", "SKIPPED"]
Role = Literal["user", "assistant", "edit"]  # "edit": a panel edit, kept apart from the person's words


class StoreUnavailable(RuntimeError):
    """A store could not read or write: its database is unreachable or the statement failed. The cause is chained."""


class TurnBusy(RuntimeError):
    """A turn of this chat is already running: the turn store checks it under a per-chat lock."""


class VersionConflict(RuntimeError):
    """The case changed since it was read (spec 007 J, T076): re-read and apply again."""

    def __init__(self, current: int) -> None:
        super().__init__(f"the case is at version {current}")
        self.current = current


@dataclass(frozen=True)
class TurnRecord:
    """A turn as stored: its chat, its order in the chat, its status and the budget it used."""

    id: str
    chat_id: str
    seq: int
    status: str  # a TurnStatus
    usage: JsonObject  # the budget snapshot (calls, cost, time), {} before the first one


@dataclass(frozen=True)
class JobRecord:
    """A research job as stored: one car × area of a turn, in a round."""

    id: str
    turn_id: str
    variant_id: str
    area: str
    round: int
    status: str  # a JobStatus
    attempts: int
    error: str | None


@dataclass(frozen=True)
class MessageRecord:
    """A chat message as stored: the person's words, an answer with its blocks, or a panel edit."""

    id: str
    chat_id: str
    turn_id: str | None
    role: str  # a Role
    text: str
    blocks: list[JsonObject]
    created_at: datetime


class TurnChanges(TypedDict, total=False):
    """What a turn update may set; a key not given is left as it is."""

    status: TurnStatus
    usage: JsonObject
    action: str | None
    fingerprint: str | None
    limits_reached: list[str]
    duration_ms: int
    case_version_after: int | None
    request_kind: str | None


class JobChanges(TypedDict, total=False):
    """What a job's mark may set besides its status."""

    docs: int
    accepted: int
    rejected: int
    error: str | None


class CaseRepo(Protocol):
    """The versions of a chat's case file (append-only; the latest is the case)."""

    async def latest(self, chat_id: str) -> tuple[int, JsonObject | None, str | None]:
        """(version, the case as stored, who changed it); (0, None, None) for a chat without a case."""
        ...

    async def save_version(self, chat_id: str, data: JsonObject, changed_by: str, change_log: list[str]) -> int:
        """Append a version; returns its number (a concurrent writer is rejected by the store)."""
        ...


class TurnRepo(Protocol):
    """The turns of the chats."""

    async def start(self, chat_id: str, user_message_id: str | None, case_version: int) -> TurnRecord:
        """A new RUNNING turn; raises TurnBusy when one already runs in the chat."""
        ...

    async def update(self, turn_id: str, **changes: Unpack[TurnChanges]) -> None:
        """Set the given fields; a final status also stamps the finish time."""
        ...

    async def get(self, turn_id: str) -> TurnRecord | None:
        """The turn, None when there is none."""
        ...

    async def active(self, chat_id: str) -> TurnRecord | None:
        """The chat's turn that is RUNNING or WAITING_CONFIRMATION, if any."""
        ...

    async def last_report_fingerprint(self, chat_id: str) -> str | None:
        """The fingerprint of the chat's last finished report (what it was computed from)."""
        ...

    async def running(self) -> list[TurnRecord]:
        """Every RUNNING turn (resumed after a restart)."""
        ...


class EventBus(Protocol):
    """The events of a chat as the UI receives them (ordered per chat)."""

    async def publish(self, chat_id: str, turn_id: str | None, type_: str, payload: JsonObject) -> int:
        """Append an event; returns its sequence number in the chat."""
        ...


class JobRepo(Protocol):
    """The research jobs of the turns."""

    async def create(self, chat_id: str, turn_id: str, variant_id: str, area: str, round_: int) -> JobRecord:
        """A PENDING job."""
        ...

    async def mark(self, job_id: str, status: JobStatus, **changes: Unpack[JobChanges]) -> None:
        """The job's new status with what it found; RUNNING counts an attempt, a final status stamps the time."""
        ...

    async def for_turn(self, turn_id: str) -> list[JobRecord]:
        """The jobs of a turn."""
        ...

    async def get(self, job_id: str) -> JobRecord | None:
        """The job, None when there is none."""
        ...

    async def skip_open(self, turn_id: str, reason: str = "cancelled") -> int:
        """Mark the turn's PENDING and RUNNING jobs SKIPPED; returns how many."""
        ...


class MessageRepo(Protocol):
    """The messages of the chats."""

    async def history(self, chat_id: str) -> list[MessageRecord]:
        """The chat's messages, oldest first."""
        ...

    async def save(self, chat_id: str, role: Role, text: str, blocks: list[JsonObject] | None = None, *,
                   message_id: str | None = None, turn_id: str | None = None) -> MessageRecord:  # fmt: skip
        """Store a message (a new id unless `message_id` is given)."""
        ...


class Estimator(Protocol):
    """Research cost estimate (FR-041): jobs are (variant_id, area)."""

    async def estimate(self, jobs: list[tuple[str, str]], rounds: int) -> float:
        """The expected cost in euros of running the jobs with up to `rounds` gap rounds."""
        ...


class ResearchHistory(Protocol):
    """What earlier research left per catalogue version (the engine's read model, `acquisition.api`): the planner's
    inputs. Raises `StoreUnavailable` when the store cannot be read (the turn fails and resumes from its checkpoint)."""

    async def powertrains(self, variant_ids: list[str]) -> dict[str, str | None]:
        """variant id -> its powertrain ("BEV", "PHEV", …), None when not known."""
        ...

    async def last_done(self, variant_ids: list[str]) -> dict[str, dict[str, datetime]]:
        """variant id -> area -> when its research last completed; versions never researched are absent."""
        ...

    async def unmet_areas(self, variant_ids: list[str]) -> dict[str, set[str]]:
        """variant id -> areas researched before whose evidence minimum was not reached."""
        ...

    async def registry_done(self, variant_ids: list[str]) -> dict[str, dict[str, datetime]]:
        """variant id -> area -> when its research last tried the registry's sources of the other markets."""
        ...


class Clock(Protocol):
    """The time of the system (a fixed one in tests)."""

    def now(self) -> datetime:
        """Now, timezone-aware."""
        ...


class VersionsStore(Protocol):
    """The shared cache of the versions of model generations (spec 008 US6, table `model_versions`)."""

    async def get(self, make: str, model: str, generation: str | None, year: int | None, new: bool,
                  ttl_days: int) -> Generation | None:  # fmt: skip
        """The cached versions of a generation younger than `ttl_days`, None when there are none."""
        ...

    async def put(self, g: Generation) -> None:
        """Cache the versions of a generation."""
        ...


class ComputationStore(Protocol):
    """The computations of a turn (tables `tco_estimates`, `simulations`; constitution IX): one row per estimate
    (its columns as keys) and the race simulation, if any."""

    async def record(self, turn_id: str, estimates: list[JsonObject], simulation: JsonObject | None) -> None:
        """Store the estimates and the simulation of the turn."""
        ...


class OutcomeFields(TypedDict, total=False):
    """What a turn's outcome records (spec 010 US1)."""

    request_kind: str | None
    action: str | None
    status: str
    language: str | None
    persona: str | None
    path: list[str]
    duration_ms: int
    cost_eur: float
    signals: dict[str, float]


class OutcomeStore(Protocol):
    """Turn outcomes and feedback (spec 010 US1, US2; tables `turn_outcomes`, `feedback`). Metrics only: a caller
    never fails a turn on its errors."""

    async def record(self, turn_id: str, chat_id: str, **fields: Unpack[OutcomeFields]) -> None:
        """Create or update the outcome of a turn (a waiting turn is recorded again when it ends)."""
        ...

    async def patch_previous(self, chat_id: str, turn_id: str, relation: str | None,
                             signals: dict[str, float]) -> None:  # fmt: skip
        """The next message tells how the previous answer landed (relation, corrections)."""
        ...

    async def add_signal(self, turn_id: str, key: str, amount: float = 1.0) -> None:
        """Count one more of a signal on a turn's outcome."""
        ...

    async def feedback(self, chat_id: str, kind: str, *, turn_id: str | None = None, text: str | None = None) -> str:
        """Store the person's feedback on an answer; returns its id."""
        ...


class AcquisitionPort(Protocol):
    """The acquisition engine bound to its ports (spec 011 contracts/acquire.md, strangler S8): the chat orders data
    and identity look-ups here and never searches, fetches or reads pages itself. Graph tests fake it. The models are
    those of `automind.acquisition.api`; its port-free read model is called on that module directly."""

    async def acquire(self, req: AcquireRequest,
                      emit: Callable[[str, str], Awaitable[None]] | None = None) -> AcquireResult:  # fmt: skip
        """Research the request's kinds for a version within the turn's budget; `emit` gets (stage, text)."""
        ...

    async def lineup(self, make: str, *, official: str | None, max_pages: int, market: str = "ES") -> LineupRead | None:
        """A make's models on sale on a market, read from its official site and one search."""
        ...

    async def versions(self, make: str, model: str, generation: str | None, *, year: int | None, queries: list[str],
                       limits: JsonObject, done: set[str] | None = None,
                       market: str = "ES") -> VersionsRead | None:  # fmt: skip
        """The versions of a model generation the sources list (the ladder's pool)."""
        ...

    async def generation_hints(self, query: str, *, lineup_url: str | None = None, user_url: str | None = None,
                               prices: bool = False, market: str = "ES") -> list[WebHint]:  # fmt: skip
        """Search results for the resolver (untrusted documents with their urls)."""
        ...

    async def dataset_versions(self, make: str, model: str, generation: str | None = None, fuel: str | None = None,
                               year_from: int | None = None) -> list[DatasetVersion]:  # fmt: skip
        """The model's versions registered in the EU (EEA CO2 datasets)."""
        ...


class MarketFacts(Protocol):
    """Market facts such as purchase incentives (spec 006 US5)."""

    async def done(self, market: str = "ES") -> datetime | None:
        """When the market's facts were last researched, None when never."""
        ...

    async def load(self, market: str = "ES") -> list[JsonObject]:
        """The market's facts as stored."""
        ...


class ModelsOnSale(Protocol):
    """The models known to be sold in Spain without a search (spec 007 US7): (make, model)."""

    async def __call__(self) -> list[tuple[str, LineupModel]]: ...


class SourceRef(Protocol):
    """A source the registry plans to read (only its domain is used here)."""

    @property
    def domain(self) -> str:
        """The site's domain ("motor.es")."""
        ...


class SpecSources(Protocol):
    """The registry's sources for an area (spec 010 US6-US8), best first."""

    async def sources_for(self, area: str, markets: list[str], limit: int) -> Sequence[SourceRef]:
        """Active sources first, then candidates the survey found open; never blocked or retired ones."""
        ...


class IntakeLog(Protocol):
    """One intake event (spec 005 R13): metrics only, never fails the turn: the implementation swallows its own
    failures (`chat.dialog.context.record_intake`)."""

    async def __call__(self, kind: str, car_key: str | None = None, item: str | None = None,
                       **details: object) -> None: ...  # fmt: skip


@dataclass
class Ports:
    """Everything the application reaches outside itself. An optional port left None turns its feature off."""

    llm: LLM
    cases: CaseRepo
    turns: TurnRepo
    events: EventBus
    jobs: JobRepo
    clock: Clock
    ref: Reference
    messages: MessageRepo
    estimator: Estimator
    computations: ComputationStore
    research: ResearchHistory  # spec 012 S9c: what earlier research left, for the planner
    acquisition: AcquisitionPort | None = None  # spec 011 S8: the engine (search, pages, readers live there)
    feasibility: FeasibilityStore | None = None  # spec 003 US3: used-price ranges and the checks of a turn
    lineup: LineupLookup | None = None  # spec 005: a make's line-up on a market; None: no look-up
    market_facts: MarketFacts | None = None  # spec 006 US5: incentives; None: none
    models_on_sale: ModelsOnSale | None = None  # spec 007 US7: models known without a search; None: none
    versions: VersionsStore | None = None  # spec 008: versions of model generations; None: no ladder (fallback)
    outcomes: OutcomeStore | None = None  # spec 010 US1/US2; None: not recorded (test fakes)
    registry: SpecSources | None = None  # spec 010 US6-US8: the source registry; None: config order only
