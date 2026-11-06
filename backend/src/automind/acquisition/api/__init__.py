"""Acquisition · acquisition.api: the engine's public interface — the chat orders data here and reads what is stored.

Owns: `contracts` — requests, results and the `Backend` protocol the engine implements (data only).
  This `__init__` — the functions: acquire, missing_critical, last_done, ev_counts, powertrains, registry_done,
  unmet_areas, tried_by_area, gearbox_families_mixed, reselect, recheck_value, revalidate_claims, recheck_minimums,
  lineup, versions, generation_hints, dataset_versions, record_challenge_gold; the catalogue (spec 012 T028):
  catalogue_models, find_variants, get_variant, upsert_variant, stale_areas, cached_lineup, store_lineup; the car read
  model: car_data, evidence_refs (`car` — its rows: CarData and the stored rows it holds).
Flow: caller → function here → `_backend()` loads `acquisition.backend` by name at the first call → engine.
  The chat orders "these kinds of data for this car, by this deadline" and gets values with confidence and sources,
  and for gaps the sources tried. Live calls run in the caller's process within its deadline and budget;
  background work runs in the worker.
Depends on: its own `contracts` only at import time (the engine is loaded at call time).
Must not depend on: any engine module at import time, so the chat's import graph holds this contract and nothing
  behind it (import-linter chat-uses-acquire-only, application-ports; constitution XIII).
Public API: the names in __all__; the only engine module the chat (chat.application, chat.dialog, chat.domain) and
  the web may import. Everything else under `automind.acquisition` is internal.
"""

from __future__ import annotations

import importlib
from typing import Any

from automind.acquisition.api.car import CarData
from automind.acquisition.api.contracts import (
    GEARBOX,
    AcquiredValue,
    AcquireRequest,
    AcquireResult,
    Backend,
    CatalogueVariant,
    DatasetVersion,
    Emit,
    Judged,
    KindResult,
    LineupEntry,
    LineupOut,
    LineupRead,
    Need,
    RecheckResult,
    RevalidateResult,
    SourceRef,
    StoredLineup,
    Tried,
    TriedOutcome,
    VariantDraft,
    VersionEntry,
    VersionsOut,
    VersionsRead,
    WebHint,
)

__all__: list[str] = [
    "GEARBOX",
    "AcquiredValue",
    "AcquireRequest",
    "AcquireResult",
    "Backend",
    "CatalogueVariant",
    "DatasetVersion",
    "Emit",
    "Judged",
    "KindResult",
    "LineupEntry",
    "LineupOut",
    "LineupRead",
    "Need",
    "RecheckResult",
    "RevalidateResult",
    "SourceRef",
    "StoredLineup",
    "Tried",
    "TriedOutcome",
    "VariantDraft",
    "VersionEntry",
    "VersionsOut",
    "VersionsRead",
    "WebHint",
    "acquire",
    "missing_critical",
    "last_done",
    "ev_counts",
    "powertrains",
    "registry_done",
    "unmet_areas",
    "tried_by_area",
    "gearbox_families_mixed",
    "reselect",
    "recheck_value",
    "revalidate_claims",
    "recheck_minimums",
    "lineup",
    "versions",
    "generation_hints",
    "dataset_versions",
    "record_challenge_gold",
    "catalogue_models",
    "find_variants",
    "get_variant",
    "upsert_variant",
    "stale_areas",
    "cached_lineup",
    "store_lineup",
    "car_data",
    "evidence_refs",
    "CarData",
]


async def acquire(req: AcquireRequest, emit: Emit | None = None, *, ports: Any = None) -> AcquireResult:
    """Research the requested kinds of data for one car. Raises only `BudgetExceeded` (the caller pauses and asks
    the user); any other failure is a `KindResult(ok=False)` and never fails the other kinds. `ports`: the engine's
    ports (`acquisition/ports.py: AcqPorts`; tests pass fakes); None: the live ones of this process."""
    b = _backend()
    return await b.acquire(req, emit, ports if ports is not None else b.live_ports())


async def missing_critical(variant_id: str, powertrain: str | None = None) -> list[str]:
    return await _backend().missing_critical(variant_id, powertrain)


async def last_done(variant_ids: list[str]) -> dict[str, dict[str, Any]]:
    """variant_id -> area -> completed_at (input to the planner's freshness check)."""
    return await _backend().last_done(variant_ids)


async def ev_counts(variant_ids: list[str]) -> dict[str, Any]:
    """EV values rejected per rule, and weighted plug-in figures kept out of the energy cost (spec 006 FR-022)."""
    return await _backend().ev_counts(variant_ids)


async def powertrains(variant_ids: list[str]) -> dict[str, str | None]:
    return await _backend().powertrains(variant_ids)


async def registry_done(variant_ids: list[str]) -> dict[str, dict[str, Any]]:
    """variant_id -> area -> when its research last tried the registry's sources with the escalation."""
    return await _backend().registry_done(variant_ids)


async def unmet_areas(variant_ids: list[str]) -> dict[str, set[str]]:
    """variant_id -> areas researched before whose evidence minimum was not reached."""
    return await _backend().unmet_areas(variant_ids)


async def tried_by_area(variant_id: str) -> dict[str, list[Tried]]:
    """area -> the sources the latest research of that area read for the car, with their outcomes ("no data" names
    them, spec 011 FR-022)."""
    return await _backend().tried_by_area(variant_id)


async def gearbox_families_mixed(variant_id: str) -> bool:
    """The accepted transmission claims of a variant name conflicting gearbox families."""
    return await _backend().gearbox_families_mixed(variant_id)


async def reselect(variant_id: str) -> None:
    """Recompute the selected values of a variant from its accepted claims."""
    await _backend().reselect(variant_id)


async def recheck_value(variant_id: str, attribute: str, *, rules: dict[str, Any] | None = None) -> RecheckResult:
    """A user challenge (spec 004 FR-022): the accepted claims behind one value checked again with the current rules
    (`rules`: config/plausibility.yaml); failing claims are rejected and the values selected again. No model call."""
    return await _backend().recheck_value(variant_id, attribute, rules)


async def revalidate_claims(rules: dict[str, Any] | None) -> RevalidateResult:
    """Data repair after rule fixes (spec 004 FR-027): spec claims checked again; returns what changed."""
    return await _backend().revalidate_claims(rules)


async def recheck_minimums(variant_id: str) -> None:
    """The area minimums of a variant's research runs again from its stored evidence."""
    await _backend().recheck_minimums(variant_id)


async def lineup(make: str, *, official: str | None, max_pages: int, market: str = "ES",
                 ports: Any = None) -> LineupRead | None:  # fmt: skip
    """A make's line-up on a market (Spain; for a car not sold in Spain: "EU", its home market such as "CN", "ANY")
    as the `lineup` web reader reads it from a search and the official site."""
    return await _backend().lineup(_ports(ports), make, official, max_pages, market)


async def versions(
    make: str, model: str, generation: str | None, *, year: int | None, queries: list[str], limits: dict[str, Any],
    done: set[str] | None = None, market: str = "ES", ports: Any = None,
) -> VersionsRead | None:  # fmt: skip
    """The versions of a model generation as the `versions` web reader reads them from the searches' pages
    (`market`: the searches' locale; another than ES for a car not sold in Spain)."""
    return await _backend().versions(_ports(ports), make, model, generation, year, queries, limits, done, market)


async def generation_hints(query: str, *, lineup_url: str | None = None, user_url: str | None = None,
                           prices: bool = False, market: str = "ES", ports: Any = None) -> list[WebHint]:  # fmt: skip
    """Search results and pages for the resolver (generations, engines, and for new cars the Spanish versions); a car
    not sold in Spain is looked up on `market` too, with the registry's spec sources there."""
    return await _backend().generation_hints(_ports(ports), query, lineup_url, user_url, prices, market)


async def dataset_versions(make: str, model: str, generation: str | None = None, fuel: str | None = None,
                           year_from: int | None = None, *, ports: Any = None) -> list[DatasetVersion]:  # fmt: skip
    """The distinct versions of a model registered in the EU (open datasets), newest first: offline from the stored
    gold values and cached dataset rows; when neither has the model, one bounded live dataset query (cached).
    Cheap and authoritative for EU-registered cars; never raises (a failure is an empty list)."""
    return await _backend().dataset_versions(_ports(ports), make, model, generation, fuel, year_from)


async def record_challenge_gold(
    variant_id: str, attribute: str, outcome: str, value: str | float | None, unit: str | None = None,
    challenge_id: str | None = None,
) -> bool:  # fmt: skip
    """A user challenge that ended CONFIRMED (the shown value) or CORRECTED (the newly selected value) becomes gold:
    origin `challenge`, rule `challenge_confirmed`/`challenge_corrected`, confidence MEDIUM (spec 011 FR-003).
    Returns whether a gold value was written."""
    return await _backend().record_challenge_gold(variant_id, attribute, outcome, value, unit, challenge_id)


async def catalogue_models(make: str) -> set[str]:
    """The model lines the catalogue has versions of for this make."""
    return await _backend().catalogue_models(make)


async def find_variants(make: str, model: str) -> list[CatalogueVariant]:
    """Every catalogued version of this make and model."""
    return await _backend().find_variants(make, model)


async def get_variant(variant_id: str) -> CatalogueVariant | None:
    return await _backend().get_variant(variant_id)


async def upsert_variant(draft: VariantDraft) -> CatalogueVariant:
    """The catalogue row of this version (one row per real version: an existing one is reused, its blanks filled)."""
    return await _backend().upsert_variant(draft)


async def stale_areas(variant_id: str, areas: tuple[str, ...]) -> list[str]:
    """The areas of a version never researched or older than their freshness (config: freshness days per area)."""
    return await _backend().stale_areas(variant_id, areas)


async def cached_lineup(make: str, market: str, ttl_days: int) -> StoredLineup | None:
    """A make's cached line-up on a market, unless older than `ttl_days`."""
    return await _backend().cached_lineup(make, market, ttl_days)


async def store_lineup(lineup: StoredLineup) -> None:
    await _backend().store_lineup(lineup)


async def car_data(variant_id: str) -> CarData | None:
    """Everything the engine has stored about one catalogued version (values, claims with evidence, runs, issues,
    reviews, reliability, the make's facts, retention, used prices, maintenance, rejected pages); None if unknown."""
    return await _backend().car_data(variant_id)


async def evidence_refs(ids: list[str]) -> dict[str, dict[str, str]]:
    """Evidence id -> its source as the report cites it (name, url, type, retrieved_at)."""
    return await _backend().evidence_refs(ids)


def _ports(ports: Any) -> Any:
    """The engine's ports: the caller's (tests, the chat's bound engine) or the live ones of this process."""
    return ports if ports is not None else _backend().live_ports()


def _backend() -> Backend:
    """The engine, loaded at the first call by module name: this interface imports no engine module, so the chat's
    import graph holds the contract and nothing behind it (import-linter `chat-uses-acquire-only`)."""
    global _BACKEND
    if _BACKEND is None:
        module = importlib.import_module("automind.acquisition.backend")
        backend: Backend = module.BACKEND
        _BACKEND = backend
    return _BACKEND


_BACKEND: Backend | None = None
