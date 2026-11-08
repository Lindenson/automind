"""The records of gold: a group of an open dataset (`DatasetRow`), the catalogue variant it is matched to
(`CandidateVariant`, reduced to `VariantKey`), a gold value to write (`GoldValue`) and one as stored (`StoredGold`),
and the description of a dataset load (`DatasetInfo`). Plain frozen dataclasses: no ORM row reaches a rule."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime

from automind.shared.contracts.json import JsonObject


@dataclass(frozen=True)
class DatasetRow:
    """One group of an open dataset: the vehicles of one make / commercial name / fuel / power (/ mass / values) with
    their count. The matcher keys on make, model, fuel, power_kw, displacement_cc, years and mass (tie-break) and
    takes the registration-weighted median of `values` over the rows of one group (research R3)."""

    dataset: str  # loader kind: eea_co2 | eea_obfcm | rdw
    make: str  # as published (EEA "Mk", RDW "merk"); normalised by the matcher through config/makes.yaml
    model: str  # commercial name as published (EEA "Cn", RDW "handelsbenaming")
    fuel: str  # petrol | diesel | lpg | cng | e85 | hybrid | phev | bev | fcev | other ("hybrid" = HEV or MHEV)
    power_kw: float | None  # matching key: combustion-engine kW (also for hybrids and plug-ins), motor kW for a BEV
    displacement_cc: int | None
    mass_running_order_kg: float | None  # as published (EU running order: includes 75 kg driver); tie-break only
    year_from: int | None  # registration years the row covers
    year_to: int | None
    registrations: int  # weight (vehicles in the group)
    values: Mapping[str, float]  # gold attribute → value as published, unit in `units`
    units: Mapping[str, str]
    record_key: str  # dataset group key, stored as gold_values.record_key
    conversions: Mapping[str, str] = field(default_factory=dict)  # attribute → conversion rule (gold_datasets.yaml)
    details: JsonObject = field(default_factory=dict)  # not compared: fuel mode, type approval, PHEV shares…


@dataclass(frozen=True)
class CandidateVariant:
    """A catalogue variant gold may be loaded for (a `vehicle_variants` row)."""

    id: str
    make: str
    model: str
    generation: str | None
    variant_name: str
    fuel: str | None
    powertrain: str | None
    power_kw: float | None
    engine_cc: int | None
    years_from: int | None
    years_to: int | None


@dataclass(frozen=True)
class VariantKey:
    """What the matcher compares of a variant with a dataset row."""

    variant_id: str
    make: str
    model: str
    model_tokens: tuple[str, ...]
    fuel: str | None  # our vocabulary (vehicle_variants.fuel): petrol, diesel, hybrid, mhev, phev, bev, lpg
    power_kw: float | None  # catalogue power (the system power for hybrids)
    years: tuple[int | None, int | None] = (None, None)
    mass: float | None = None  # curb mass (kg) when known: tie-break only
    displacement_cc: int | None = None


@dataclass(frozen=True)
class GoldValue:
    """A gold value to write: the value of one attribute of one variant, its tolerance and where it came from."""

    variant_id: str
    attribute: str
    value_num: float | None
    unit: str
    tolerance: float
    tolerance_kind: str
    origin: str  # reference_set | dataset | challenge
    match_rule: str
    confidence: str  # HIGH | MEDIUM
    dataset_id: str | None = None
    record_key: str | None = None
    registrations: int | None = None
    value_text: str | None = None
    details: JsonObject = field(default_factory=dict)


@dataclass(frozen=True)
class StoredGold:
    """A gold value as stored (`gold_values`), with its id and when it was verified."""

    id: str
    variant_id: str
    attribute: str
    value_num: float | None
    value_text: str | None
    unit: str
    tolerance: float
    tolerance_kind: str
    origin: str
    match_rule: str
    confidence: str
    dataset_id: str | None
    verified_at: datetime


@dataclass(frozen=True)
class DatasetInfo:
    """A dataset load as `gold_datasets` records it. The loaders give `next_refresh_at`; the reference set and the
    challenges give `refresh_days` (counted from the load) or nothing."""

    id: str  # e.g. "eea_co2_2024", "rdw", "reference_set", "challenges"
    name: str
    kind: str  # eea_co2 | eea_obfcm | rdw | reference_set | challenge
    licence: str
    url: str | None = None
    version: str | None = None
    refresh_days: int | None = None
    next_refresh_at: datetime | None = None
