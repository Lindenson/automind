"""The acquisition engine's public interface (spec 011, contracts/acquire.md).

The only engine module the chat (`automind.application`, `automind.orchestration`, `automind.domain`) may import
(FR-005, FR-006). The chat orders data here — "these kinds of data for this car, by this deadline" — and receives
values with confidence and sources, and for gaps the sources tried. Live calls run in the caller's process within
the caller's deadline and budget (research R5); background work runs in the worker. Everything else under
`automind.acquisition` is internal.

This module imports only its models at import time: the engine (pipeline, read model, gold store) is loaded when a
function is called (`_engine`), so the chat's import graph holds this contract and nothing behind it (import-linter
`application-ports`, `chat-uses-acquire-only`; constitution XIII).
"""

from __future__ import annotations

import importlib
from collections.abc import Awaitable, Callable
from datetime import datetime
from enum import StrEnum
from types import ModuleType
from typing import Any, Literal

from pydantic import BaseModel, Field

__all__: list[str] = [
    "DatasetVersion",
    "LineupEntry",
    "LineupOut",
    "LineupRead",
    "VersionEntry",
    "VersionsOut",
    "VersionsRead",
    "WebHint",
    "dataset_versions",
    "generation_hints",
    "lineup",
    "versions",
    "AcquireRequest",
    "AcquireResult",
    "AcquiredValue",
    "Emit",
    "KindResult",
    "Need",
    "SourceRef",
    "Tried",
    "acquire",
    "ev_counts",
    "Judged",
    "RecheckResult",
    "RevalidateResult",
    "gearbox_families_mixed",
    "last_done",
    "missing_critical",
    "powertrains",
    "recheck_minimums",
    "recheck_value",
    "record_challenge_gold",
    "registry_done",
    "reselect",
    "revalidate_claims",
    "unmet_areas",
]

Emit = Callable[[str, str], Awaitable[None]]  # (stage, text) — progress for the chat


def _engine(module: str) -> ModuleType:
    """An engine module, loaded at call time (see the module docstring)."""
    return importlib.import_module(f"automind.{module}")


class Need(StrEnum):
    CACHED = "cached"  # read the engine's stored data only; never search or fetch
    STANDARD = "standard"  # cache-first; research what is missing or stale (round 0)
    FOLLOW_UP = "follow_up"  # a gap round (round > 0)
    FRESH = "fresh"  # "find it": past the search cache, wider queries, the registry's other markets too
    ESCALATE = "escalate"  # an area left short before: the registry's other markets too
    REFRESH = "refresh"  # prefetch: like STANDARD, background budget, no emit


class AcquireRequest(BaseModel):
    job_id: str  # research_jobs.id (chat) or acq_tasks.id (prefetch)
    variant_id: str
    kinds: list[str]  # areas: specs, engineering, price, maintenance, ... (one per call today)
    need: Need = Need.STANDARD
    round: int = 0
    deadline: datetime | None = None  # the job timeout; the caller's asyncio.timeout enforces it today
    car_year: int | None = None


class SourceRef(BaseModel):
    domain: str
    url: str
    quote: str  # verbatim excerpt (I)
    source_type: str
    unverified: bool = False
    producer: Literal["reader", "extractor", "dataset", "user"]
    producer_version: str | None = None
    model: str | None = None


class AcquiredValue(BaseModel):
    attribute: str
    value: float | str | None
    unit: str | None
    confidence: Literal["HIGH", "MEDIUM", "LOW"]
    provenance: str
    sources: list[SourceRef]


TriedOutcome = Literal["accepted", "rejected", "robots", "junk", "empty", "error", "not_reached"]


class Tried(BaseModel):
    domain: str
    outcome: TriedOutcome
    reason: str | None = None


class KindResult(BaseModel):
    """Today's JobResult, plus what was tried."""

    kind: str
    ok: bool = True
    docs: int = 0
    accepted: int = 0
    rejected: int = 0
    minimum_met: bool = False
    error: str | None = None
    hits: list[dict[str, Any]] = []
    tried: list[Tried] = []
    stage_versions: dict[str, str] = {}


class AcquireResult(BaseModel):
    job_id: str
    variant_id: str
    round: int
    kinds: list[KindResult]
    values: list[AcquiredValue] = []


async def acquire(req: AcquireRequest, emit: Emit | None = None, *, ports: Any = None) -> AcquireResult:
    """Research the requested kinds of data for one car. Raises only `BudgetExceeded` (the caller pauses and asks
    the user); any other failure is a `KindResult(ok=False)` and never fails the other kinds. `ports`: the engine's
    ports (`acquisition/ports.py: AcqPorts`; tests pass fakes); None: the live ones of this process."""
    facade = _engine("acquisition.facade")
    return await facade.acquire(req, emit, ports=_ports(ports))  # type: ignore[no-any-return]


# --- read model: stored data only, no network or model call ------------------------------------------------------


async def missing_critical(variant_id: str, powertrain: str | None = None) -> list[str]:
    return await _engine("acquisition.read").missing_critical(variant_id, powertrain)  # type: ignore[no-any-return]


async def last_done(variant_ids: list[str]) -> dict[str, dict[str, Any]]:
    """variant_id -> area -> completed_at (input to the planner's freshness check)."""
    return await _engine("acquisition.read").last_done(variant_ids)  # type: ignore[no-any-return]


async def ev_counts(variant_ids: list[str]) -> dict[str, Any]:
    """EV values rejected per rule, and weighted plug-in figures kept out of the energy cost (spec 006 FR-022)."""
    return await _engine("acquisition.read").ev_counts(variant_ids)  # type: ignore[no-any-return]


async def powertrains(variant_ids: list[str]) -> dict[str, str | None]:
    return await _engine("acquisition.read").powertrains(variant_ids)  # type: ignore[no-any-return]


async def registry_done(variant_ids: list[str]) -> dict[str, dict[str, Any]]:
    """variant_id -> area -> when its research last tried the registry's sources with the escalation."""
    return await _engine("acquisition.read").registry_done(variant_ids)  # type: ignore[no-any-return]


async def unmet_areas(variant_ids: list[str]) -> dict[str, set[str]]:
    """variant_id -> areas researched before whose evidence minimum was not reached."""
    return await _engine("acquisition.read").unmet_areas(variant_ids)  # type: ignore[no-any-return]


async def gearbox_families_mixed(variant_id: str) -> bool:
    """The accepted transmission claims of a variant name conflicting gearbox families."""
    return await _engine("acquisition.facade").gearbox_families_mixed(variant_id)  # type: ignore[no-any-return]


async def reselect(variant_id: str) -> None:
    """Recompute the selected values of a variant from its accepted claims."""
    await _engine("acquisition.facade").reselect(variant_id)


# --- challenge and repair: stored claims against the current rules -------------------------------------------------


class Judged(BaseModel):
    """One claim behind a challenged value: its source, whether it passed, and who produced it (blame input)."""

    domain: str
    area: str
    claim_id: str
    excerpt: str | None = None
    by: str | None = None  # READER | LLM | LLM_EXCERPT (the quote is not on the page)
    ok: bool


class RecheckResult(BaseModel):
    rejected: list[dict[str, Any]] = []  # {"source", "value", "why"} per claim that failed
    kept: list[str] = []  # domains of the claims that passed
    judged: list[Judged] = []
    claim_id: str | None = None  # the claim behind the shown value (spec 010 FR-006)


class RevalidateResult(BaseModel):
    stats: dict[str, int] = {}  # "<old status>-><new status>:<attribute>" -> claims
    changed: list[str] = []  # variant ids whose claims changed


async def recheck_value(variant_id: str, attribute: str, *, rules: dict[str, Any] | None = None) -> RecheckResult:
    """A user challenge (spec 004 FR-022): the accepted claims behind one value checked again with the current rules
    (`rules`: config/plausibility.yaml); failing claims are rejected and the values selected again. No model call."""
    return await _engine("acquisition.recheck").recheck_value(variant_id, attribute, rules=rules)  # type: ignore[no-any-return]


async def revalidate_claims(rules: dict[str, Any] | None) -> RevalidateResult:
    """Data repair after rule fixes (spec 004 FR-027): spec claims checked again; returns what changed."""
    return await _engine("acquisition.recheck").revalidate_claims(rules)  # type: ignore[no-any-return]


async def recheck_minimums(variant_id: str) -> None:
    """The area minimums of a variant's research runs again from its stored evidence."""
    await _engine("acquisition.recheck").recheck_minimums(variant_id)


# --- identity readers (strangler S8): the chat keeps its caches and checks, the engine searches and reads ----------


class LineupEntry(BaseModel):
    model: str
    body: str = ""
    powertrains: list[str] = Field(default_factory=list)
    price_from_eur: int | None = None
    excerpt: str = ""
    source_url: str = ""


class LineupOut(BaseModel):
    models: list[LineupEntry] = Field(default_factory=list)


class LineupRead(BaseModel):
    """What the `lineup` web reader listed, and the pages it read (url -> (title, text)) for the chat's checks."""

    docs: dict[str, tuple[str, str]]
    out: LineupOut


GEARBOX = Literal["manual", "automatic", "dct", "cvt", "e-cvt", "single"]


class VersionEntry(BaseModel):
    engine: str
    fuel: Literal["petrol", "diesel", "hybrid", "mhev", "phev", "bev", "lpg"] | None = None
    displacement_l: float | None = None
    power_cv: int | None = None
    power_kw: int | None = None
    gearboxes: list[GEARBOX] = Field(default_factory=list)
    drives: list[Literal["FWD", "RWD", "AWD"]] = Field(default_factory=list)
    years_from: int | None = None
    years_to: int | None = None
    excerpt: str = ""
    source_url: str = ""


class VersionsOut(BaseModel):
    generation: str | None = None
    generation_years_from: int | None = None
    generation_years_to: int | None = None
    body_class: Literal["HATCHBACK", "SEDAN", "WAGON", "COUPE", "CONVERTIBLE", "SUV", "MPV", "PICKUP"] | None = None
    versions: list[VersionEntry] = Field(default_factory=list)


class VersionsRead(BaseModel):
    """What the `versions` web reader listed, and the pages it read (url -> (title, text)) for the chat's checks."""

    docs: dict[str, tuple[str, str]]
    out: VersionsOut


class WebHint(BaseModel):
    """A search result or page for the resolver (its text is page content: untrusted)."""

    url: str
    title: str
    text: str


async def lineup(make: str, *, official: str | None, max_pages: int, ports: Any = None) -> LineupRead | None:
    """A make's line-up in Spain as the `lineup` web reader reads it from a search and the official site."""
    identity = _engine("acquisition.pipeline.identity")
    return await identity.lineup(_ports(ports), make, official=official, max_pages=max_pages)  # type: ignore[no-any-return]


async def versions(
    make: str, model: str, generation: str | None, *, year: int | None, queries: list[str], limits: dict[str, Any],
    done: set[str] | None = None, ports: Any = None,
) -> VersionsRead | None:  # fmt: skip
    """The versions of a model generation as the `versions` web reader reads them from the searches' pages."""
    identity = _engine("acquisition.pipeline.identity")
    return await identity.versions(_ports(ports), make, model, generation, year=year, queries=queries, limits=limits,  # type: ignore[no-any-return]
                                   done=done)  # fmt: skip


async def generation_hints(query: str, *, lineup_url: str | None = None, user_url: str | None = None,
                           prices: bool = False, ports: Any = None) -> list[WebHint]:  # fmt: skip
    """Search results and pages for the resolver (generations, engines, and for new cars the Spanish versions)."""
    identity = _engine("acquisition.pipeline.identity")
    return await identity.generation_hints(_ports(ports), query, lineup_url=lineup_url, user_url=user_url,  # type: ignore[no-any-return]
                                           prices=prices)  # fmt: skip


class DatasetVersion(BaseModel):
    """A version of a model as the open registration datasets list it (EEA CO2; one engine: fuel, kW, cm3).
    `engine_kw` is the combustion engine's power (for a hybrid or plug-in NOT the system power); `power_is_max`:
    a combustion car, whose engine kW is its power. `years_to` None: still registered in the newest year."""

    fuel: str
    engine_kw: int | None = None
    displacement_cc: int | None = None
    years_from: int | None = None
    years_to: int | None = None
    registrations: int = 0  # 0: not known (a stored group key)
    power_is_max: bool = False
    datasets: list[str] = Field(default_factory=list)
    names: list[str] = Field(default_factory=list)  # commercial names as published
    source_url: str = ""


async def dataset_versions(make: str, model: str, generation: str | None = None, fuel: str | None = None,
                           year_from: int | None = None, *, ports: Any = None) -> list[DatasetVersion]:  # fmt: skip
    """The distinct versions of a model registered in the EU (open datasets), newest first: offline from the stored
    gold values and cached dataset rows; when neither has the model, one bounded live dataset query (cached).
    Cheap and authoritative for EU-registered cars; never raises (a failure is an empty list)."""
    gv = _engine("acquisition.gold.versions")
    found = await gv.registered_versions(_ports(ports), make, model, generation, fuel, year_from)
    url = gv.source_url()
    return [DatasetVersion(fuel=v.fuel, engine_kw=v.engine_kw, displacement_cc=v.displacement_cc,
                           years_from=v.years_from, years_to=v.years_to, registrations=v.registrations,
                           power_is_max=v.power_is_max, datasets=list(v.datasets), names=list(v.names),
                           source_url=url) for v in found]  # fmt: skip


def _ports(ports: Any) -> Any:
    """The engine's ports: the caller's (tests, the chat's bound engine) or the live ones of this process."""
    return ports if ports is not None else _engine("acquisition.infrastructure.wiring").live_acq_ports()


# --- gold ----------------------------------------------------------------------------------------------------------


async def record_challenge_gold(
    variant_id: str, attribute: str, outcome: str, value: str | float | None, unit: str | None = None,
    challenge_id: str | None = None,
) -> bool:  # fmt: skip
    """A user challenge that ended CONFIRMED (the shown value) or CORRECTED (the newly selected value) becomes gold:
    origin `challenge`, rule `challenge_confirmed`/`challenge_corrected`, confidence MEDIUM (spec 011 FR-003).
    Returns whether a gold value was written."""
    gold = _engine("acquisition.gold.repo")
    return await gold.record_challenge(variant_id, attribute, outcome, value, challenge_id, unit)  # type: ignore[no-any-return]
