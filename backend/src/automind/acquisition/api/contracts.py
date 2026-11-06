"""Contracts of the acquisition engine's public interface (spec 011 contracts/acquire.md): requests, results and
the `Backend` protocol the engine implements. Data only — no engine module is imported here."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime
from enum import StrEnum
from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field

__all__: list[str] = [
    "AcquireRequest",
    "AcquireResult",
    "AcquiredValue",
    "Backend",
    "CatalogueVariant",
    "DatasetVersion",
    "Emit",
    "GEARBOX",
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
]


Emit = Callable[[str, str], Awaitable[None]]  # (stage, text) — progress for the chat


class Backend(Protocol):
    """What the engine provides to this interface (implemented by `acquisition/backend.py: EngineBackend`)."""

    def live_ports(self) -> Any: ...
    async def acquire(self, req: AcquireRequest, emit: Emit | None, ports: Any) -> AcquireResult: ...
    async def missing_critical(self, variant_id: str, powertrain: str | None) -> list[str]: ...
    async def last_done(self, variant_ids: list[str]) -> dict[str, dict[str, Any]]: ...
    async def ev_counts(self, variant_ids: list[str]) -> dict[str, Any]: ...
    async def powertrains(self, variant_ids: list[str]) -> dict[str, str | None]: ...
    async def registry_done(self, variant_ids: list[str]) -> dict[str, dict[str, Any]]: ...
    async def unmet_areas(self, variant_ids: list[str]) -> dict[str, set[str]]: ...
    async def tried_by_area(self, variant_id: str) -> dict[str, list[Tried]]: ...
    async def gearbox_families_mixed(self, variant_id: str) -> bool: ...
    async def reselect(self, variant_id: str) -> None: ...
    async def recheck_value(self, variant_id: str, attribute: str, rules: dict[str, Any] | None) -> RecheckResult: ...
    async def revalidate_claims(self, rules: dict[str, Any] | None) -> RevalidateResult: ...
    async def recheck_minimums(self, variant_id: str) -> None: ...
    async def lineup(self, ports: Any, make: str, official: str | None, max_pages: int,
                     market: str) -> LineupRead | None: ...  # fmt: skip
    async def versions(
        self, ports: Any, make: str, model: str, generation: str | None, year: int | None, queries: list[str],
        limits: dict[str, Any], done: set[str] | None, market: str,
    ) -> VersionsRead | None: ...  # fmt: skip
    async def generation_hints(self, ports: Any, query: str, lineup_url: str | None, user_url: str | None,
                               prices: bool, market: str) -> list[WebHint]: ...  # fmt: skip
    async def dataset_versions(self, ports: Any, make: str, model: str, generation: str | None, fuel: str | None,
                               year_from: int | None) -> list[DatasetVersion]: ...  # fmt: skip
    async def record_challenge_gold(self, variant_id: str, attribute: str, outcome: str, value: str | float | None,
                                    unit: str | None, challenge_id: str | None) -> bool: ...  # fmt: skip
    async def catalogue_models(self, make: str) -> set[str]: ...
    async def find_variants(self, make: str, model: str) -> list[CatalogueVariant]: ...
    async def get_variant(self, variant_id: str) -> CatalogueVariant | None: ...
    async def upsert_variant(self, draft: VariantDraft) -> CatalogueVariant: ...
    async def stale_areas(self, variant_id: str, areas: tuple[str, ...]) -> list[str]: ...
    async def cached_lineup(self, make: str, market: str, ttl_days: int) -> StoredLineup | None: ...
    async def store_lineup(self, lineup: StoredLineup) -> None: ...


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
    # where the car is sold when not in Spain (CaseCar.market: "EU", "CN", …; chat 2026-11-06). Outside Europe the
    # research also reads that market's sources in its language; prices still come from Europe only (009 FR-009)
    market: str | None = None


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


# --- the catalogue: one row per real version of a car, and the makes' line-ups (spec 012 T028) -------------------


class VariantDraft(BaseModel):
    """A version to put in the catalogue, its names already canonical (`canonical_key` built by the caller). The
    catalogue keeps one row per real version: an existing row of the same version is reused and its blanks filled."""

    canonical_key: str
    make: str
    model: str
    generation: str | None = None
    variant_name: str
    powertrain: str
    body_class: str | None = None
    generation_years_from: int | None = None
    generation_years_to: int | None = None
    vehicle_class: str | None = None
    segment: str | None = None
    transmission: str | None = None
    drive: str | None = None
    trim: str | None = None
    trim_level: str | None = None
    price_eur: int | None = None
    engine_cc: int | None = None
    power_kw: int | None = None
    fuel: str | None = None


class CatalogueVariant(BaseModel):
    """A catalogued version of a car (table `vehicle_variants`), as the chat reads it."""

    id: str
    make: str
    model: str
    generation: str | None = None
    variant_name: str
    powertrain: str
    body_class: str | None = None
    model_year_from: int | None = None
    market: str = "ES"
    generation_years_from: int | None = None
    generation_years_to: int | None = None
    vehicle_class: str | None = None
    segment: str | None = None
    brand_positioning: str | None = None
    transmission: str | None = None
    drive: str | None = None
    trim: str | None = None
    trim_level: str | None = None
    price_eur: float | None = None
    engine_cc: int | None = None
    power_kw: int | None = None
    fuel: str | None = None

    @property
    def label(self) -> str:
        gen = f" {self.generation}" if self.generation else ""
        return f"{self.make} {self.model}{gen} {self.variant_name}".replace("  ", " ").strip()


class StoredLineup(BaseModel):
    """A make's models on sale in a market as cached (table `brand_lineups`): models and sources as stored dicts."""

    make: str
    market: str = "ES"
    models: list[dict[str, Any]] = Field(default_factory=list)
    sources: list[dict[str, Any]] = Field(default_factory=list)
    fetched_at: datetime | None = None
