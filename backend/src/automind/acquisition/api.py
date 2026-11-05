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

from pydantic import BaseModel

__all__: list[str] = [
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
    ports (the chat passes its `Ports` today; tests pass fakes)."""
    facade = _engine("acquisition.facade")
    return await facade.acquire(req, emit, ports=ports)  # type: ignore[no-any-return]


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
