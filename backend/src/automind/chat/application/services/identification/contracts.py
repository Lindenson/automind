"""Contracts of the identification service: what it is asked, the line-up and catalogue rows it works with, what a
fallback strategy is, what the resolver returns, and the reasons it gives up (spec 005, spec 008, spec 012 S7)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Literal, Protocol, TypedDict

from pydantic import BaseModel, Field

from automind.chat.domain.case import CaseCar, CaseFile, IdentifyOutcome
from automind.chat.domain.decision import CarState
from automind.chat.domain.identification import used
from automind.chat.domain.intake import LineupModel
from automind.shared.contracts.config import Reference

if TYPE_CHECKING:
    from automind.chat.application.ports import Ports


MAX_ATTEMPTS_PER_ITEM = 2  # default; config/search.yaml intake.max_attempts_per_item
CATALOG_STALE_YEARS = 4  # default; config/search.yaml intake.catalog_stale_years


@dataclass
class Lineup:
    """A make's models on sale in a market, each kept only where its document supports it (spec 005 R2), and the
    sources read (`url`, `name`, `type` MANUFACTURER | PUBLICATION)."""

    make: str
    models: list[LineupModel] = field(default_factory=list)
    sources: list[dict[str, str]] = field(default_factory=list)
    fetched_at: datetime | None = None


class LineupLookup(Protocol):
    """A make's line-up on a market (cache-first; `lineup.get_lineup`), None when no source supports one."""

    async def __call__(self, ports: Ports, make: str, market: str = "ES") -> Lineup | None: ...


class VariantRow(TypedDict):
    """A catalogue version as the plain row the policy, the confirmation card and the case keep
    (`catalogue.variant_dict`); the graph state carries it in an assessment's candidates."""

    id: str
    label: str
    make: str
    model: str
    generation: str | None
    generation_years_from: int | None
    generation_years_to: int | None
    variant_name: str
    powertrain: str
    trim: str | None
    trim_level: str | None
    price_eur: float | None
    transmission: str | None
    drive: str | None
    engine_cc: int | None
    power_kw: int | None
    body_class: str | None
    fuel: str | None


@dataclass(frozen=True)
class IntakeConfig:
    """config/search.yaml `intake`: how often to ask, the assumed use of a used car, the catalogue's staleness."""

    max_attempts_per_item: int
    km_per_year_used: int
    default_used_age: int
    catalog_stale_years: int

    @classmethod
    def of(cls, ref: Reference) -> IntakeConfig:
        """From config/search.yaml `intake`; a key the section does not set takes the code's default."""
        intake = (ref.search or {}).get("intake") or {}
        return cls(max_attempts_per_item=_int(intake.get("max_attempts_per_item", MAX_ATTEMPTS_PER_ITEM)),
                   km_per_year_used=_int(intake.get("km_per_year_used", used.KM_PER_YEAR_USED)),
                   default_used_age=_int(intake.get("default_used_age", used.DEFAULT_USED_AGE)),
                   catalog_stale_years=_int(intake.get("catalog_stale_years", CATALOG_STALE_YEARS)))  # fmt: skip


@dataclass
class IdentifyRequest:
    """Identify this car of the case now (`current_year`: the clock's year)."""

    case: CaseFile
    car: CaseCar
    current_year: int


@dataclass
class KnownModels:
    """The models known for a make. `lineup`: the make's line-up read (or None); `catalog`: models of the catalogue
    and config; `known`: both."""

    lineup: Lineup | None
    catalog: set[str]
    known: set[str]


@dataclass
class Placed:
    """A car whose make and model are known, placed on its market: the input of the fallback strategies.
    `lineup`: the line-up to identify with (the one listing the model, else one of the make's)."""

    case: CaseFile
    car: CaseCar
    year: int
    lineup: Lineup | None


class Fallback(Protocol):
    """One way to identify a placed car; None hands it to the next way (spec 008 FR-020: sourced first)."""

    async def identify(self, placed: Placed) -> IdentifyOutcome | None:
        """The outcome for the placed car, or None when this way cannot tell."""
        ...


class VariantIdentity(BaseModel):
    """Exact vehicle identity proposed by the resolver (a web reader: no tools)."""

    make: str = Field(description="Manufacturer, e.g. 'Toyota'")
    model: str = Field(description="Model, e.g. 'Land Cruiser Prado'")
    generation: str | None = Field(description="Generation code, e.g. 'J150', 'Mk8', 'F30'")
    generation_years_from: int | None = Field(description="First production year of this generation")
    generation_years_to: int | None = Field(description="Last production year of this generation (null if current)")
    variant_name: str = Field(description="Engine/trim, e.g. '3.0 D-4D 173 PS automatic'")
    powertrain: Literal["ICE", "BEV", "HEV", "PHEV", "MHEV"]
    body_class: Literal["HATCHBACK", "SEDAN", "WAGON", "COUPE", "CONVERTIBLE", "SUV", "MPV", "PICKUP"] | None = None
    vehicle_class: Literal["small", "compact", "mid_large", "premium_suv_4x4"] | None = None
    segment: str | None = Field(default=None, description="Market segment, e.g. 'C-SUV', 'D', 'large 4x4'")
    transmission: Literal["manual", "automatic", "dct", "cvt", "e-cvt", "single"] | None = Field(
        default=None, description="Gearbox of this version"
    )
    drive: Literal["FWD", "RWD", "AWD"] | None = Field(default=None, description="Driven wheels of this version")
    trim: str | None = Field(default=None, description="Equipment level name of this version, e.g. 'Klass', 'Homura'")
    trim_level: Literal["BASE", "MID", "TOP"] | None = Field(
        default=None, description="Position of this version in the model's Spanish price list: BASE = cheapest"
    )
    price_eur: int | None = Field(default=None, description="Official Spanish list price of this version (PVP), EUR")
    engine_cc: int | None = Field(default=None, description="Engine displacement in cm³ (e.g. 1498); null for BEV")
    power_kw: int | None = Field(default=None, description="Maximum power in kW")
    fuel: Literal["petrol", "diesel", "hybrid", "mhev", "phev", "bev", "lpg"] | None = Field(
        default=None, description="Fuel / energy of this version"
    )
    known_model: bool = Field(default=True, description="False if no such make/model exists or you are not sure")
    certainty: Literal["exact", "likely", "ambiguous"]
    alternatives: list[str] = Field(default_factory=list, description="Other plausible variants (max 3)")
    note: str = Field(default="", description="Short note, e.g. not sold new in Spain")


class Assessment(BaseModel):
    """A car looked up in the catalogue: the policy's view of it, the fitting rows (best first), its generations."""

    state: CarState
    candidates: list[VariantRow] = Field(default_factory=list)  # catalog variants that fit
    generations: list[str] = Field(default_factory=list)  # plausible generation codes


class UnknownModel(ValueError):
    """The make/model is not known to the catalog, config or the resolver (spec 004 US8 scenario 2)."""

    def __init__(self, name: str, closest: list[str], checked: list[str] | None = None) -> None:
        super().__init__(f"unknown model {name!r}")
        self.closest = closest
        self.checked = checked or []


class NotOnSale(ValueError):
    """The resolver could not name a version of the generation on sale with an engine (spec 007 F): the user is
    offered the catalogued engines instead of an invented variant."""


class GenerationMismatch(ValueError):
    """The resolver proposed a generation outside the requested years (never accepted silently)."""


def _int(v: object) -> int:
    if isinstance(v, int | float | str):
        return int(v)
    raise TypeError(f"config/search.yaml intake: a number expected, got {v!r}")
