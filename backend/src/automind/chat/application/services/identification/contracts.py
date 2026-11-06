"""Contracts of the identification service: what it is asked, what a fallback strategy is, what the resolver
returns, and the reasons it gives up (spec 005, spec 008, spec 012 S7)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field

from automind.chat.domain.case import CaseCar, CaseFile, IdentifyOutcome
from automind.chat.domain.decision import CarState

LineupLookup = Callable[..., Awaitable[Any]]
"""(ports, make[, market=]) -> lineup.Lineup | None: a make's models on a market (spec 005); None: no look-up."""


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

    lineup: Any
    catalog: set[str]
    known: set[str]


@dataclass
class Placed:
    """A car whose make and model are known, placed on its market: the input of the fallback strategies.
    `lineup`: the line-up to identify with (the one listing the model, else one of the make's)."""

    case: CaseFile
    car: CaseCar
    year: int
    lineup: Any


class Fallback(Protocol):
    """One way to identify a placed car; None hands it to the next way (spec 008 FR-020: sourced first)."""

    async def identify(self, placed: Placed) -> IdentifyOutcome | None: ...


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
    candidates: list[dict[str, Any]] = Field(default_factory=list)  # catalog variants that fit
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
