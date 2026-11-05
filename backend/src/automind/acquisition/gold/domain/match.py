"""Gold matching: dataset rows → variants (spec 011 research R3). Pure.

PLACEHOLDER from the loaders branch (T024–T026): only the `DatasetRow` shape the loaders produce. The matching itself
(`VariantKey`, `match`, `flag`) is T022; when both branches meet, T022's module wins and keeps these field names.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any


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
    details: Mapping[str, Any] = field(default_factory=dict)  # not compared: fuel mode, type approval, PHEV shares…
