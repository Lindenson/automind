"""The ownership-cost model (FR-033..FR-035; R9): rates, maintenance schedules, big tickets, the car facts the cost
uses, and the estimate with its items."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

from automind.chat.domain.cost import energy as en

RULES_VERSION = "tco-1.2"  # 1.2: energy model per powertrain (spec 006)


Basis = Literal["SOURCED", "ASSUMPTION"]


Kind = Literal["MAINTENANCE", "ENERGY", "TYRES", "ROAD_TAX", "BIG_TICKET", "BASE_RESERVE", "DEPRECIATION"]


CLASSES = ("small", "compact", "mid_large", "premium_suv_4x4")


@dataclass(frozen=True)
class TcoRates:
    fuel_eur_per_l: float
    diesel_eur_per_l: float
    electricity_eur_per_kwh: float
    labour_eur_per_h: float
    annual_km: int
    horizon_years: int
    tyre_life_km: Mapping[str, float]
    tyre_set_eur: Mapping[str, float]
    service_hours: Mapping[str, float]
    service_parts_eur: Mapping[str, float]
    default_interval_km: Mapping[str, float]
    big_ticket_default_eur: float
    road_tax_eur_per_cvf: float | None
    base_reserve: Mapping[str, list[float]]  # class -> per age band [0-4, 5-9, 10-14, 15+]
    max_maintenance_eur: Mapping[str, float] = field(default_factory=dict)  # sanity cap per class and year
    real_world_factor: Mapping[str, float] = field(default_factory=dict)  # official cycle → real use, per powertrain
    energy: en.EnergyConfig = field(default_factory=en.EnergyConfig)  # config/energy.yaml (spec 006)

    @classmethod
    def from_config(cls, d: Mapping[str, Any], overrides: Mapping[str, float | None] | None = None) -> TcoRates:
        o = {k: v for k, v in (overrides or {}).items() if v is not None}
        table = d["base_reserve_eur_per_year"]
        energy = en.EnergyConfig.from_config(
            d.get("energy"),
            home_override=o.get("home_electricity_eur_per_kwh", o.get("electricity_eur_per_kwh")),
            ac_override=o.get("public_ac_eur_per_kwh"),
            dc_override=o.get("public_dc_eur_per_kwh"),
            night=bool(o.get("night_tariff")),
            today=d.get("today"),
        )
        petrol = energy.petrol.value if energy.petrol else d["fuel_eur_per_l"]
        diesel = energy.diesel.value if energy.diesel else d["diesel_eur_per_l"]
        return cls(
            fuel_eur_per_l=float(o.get("fuel_eur_per_l", petrol)),
            diesel_eur_per_l=float(o.get("diesel_eur_per_l", diesel)),
            electricity_eur_per_kwh=float(o.get("electricity_eur_per_kwh", d["electricity_eur_per_kwh"])),
            labour_eur_per_h=float(o.get("labour_eur_per_h", d["labour_eur_per_h"])),
            annual_km=int(d["annual_km"]),
            horizon_years=int(d["horizon_years"]),
            tyre_life_km=dict(d["tyre_life_km"]),
            tyre_set_eur=dict(d["tyre_set_eur"]),
            service_hours=dict(d["service_hours"]),
            service_parts_eur=dict(d["service_parts_eur"]),
            default_interval_km=dict(d["default_interval_km"]),
            big_ticket_default_eur=float(d["big_ticket_default_eur"]),
            road_tax_eur_per_cvf=d.get("road_tax_eur_per_cvf"),
            base_reserve={k: [float(x) for x in v] for k, v in table.items() if k in CLASSES},
            max_maintenance_eur={k: float(v) for k, v in (d.get("max_maintenance_eur_per_year") or {}).items()},
            real_world_factor={k: float(v) for k, v in (d.get("real_world_factor") or {}).items()},
            energy=energy,
        )


@dataclass(frozen=True)
class MaintenanceSched:
    item: str
    interval_km: float | None = None
    interval_months: float | None = None
    cost_eur: float | None = None  # sourced price of this service, if published
    evidence_ids: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class BigTicket:
    component: str
    age_from: int | None = None
    age_to: int | None = None
    mileage_from: int | None = None
    mileage_to: int | None = None
    cost_eur: float | None = None
    evidence_ids: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class TcoCar:
    car_id: str
    label: str
    powertrain: str
    fuel: str | None = None  # petrol | diesel (ICE/hybrids)
    consumption: float | None = None  # official WLTP, l/100 km or kWh/100 km (BEV)
    consumption_real: float | None = None  # real-world (tests), preferred for the fuel bill
    consumption_nedc: float | None = None  # old cycle, used only without WLTP and real-world figures
    vehicle_class: str | None = None
    condition: str = "NEW"
    age_years: int | None = None
    mileage_km: int | None = None
    fiscal_hp: float | None = None
    road_tax_eur: float | None = None  # sourced annual road tax
    maintenance: list[MaintenanceSched] = field(default_factory=list)
    big_tickets: list[BigTicket] = field(default_factory=list)
    price_eur: float | None = None  # official new price (ES)
    used_price_eur: float | None = None  # spec 008: sourced used price for its year (a used car's value now)
    retention: Mapping[int, float] = field(default_factory=dict)  # sourced value share after N years (3, 5)
    retention_curve: Mapping[float, float] = field(default_factory=dict)  # class curve (assumption), age -> share
    # spec 006: electric facts and the user's use (daily km, climate, home charging) for the energy model
    consumption_ev: float | None = None
    consumption_ev_real: float | None = None
    ev_real_meter: str | None = None
    consumption_cs: float | None = None
    consumption_weighted: float | None = None  # PHEV official WLTP weighted l/100 km (spec 009 FR-014 estimate)
    battery_kwh: float | None = None
    range_wltp: float | None = None
    range_real: float | None = None
    consumption_ev_cltc: float | None = None  # a car sold only in China: its CLTC figures (chat 2026-11-06)
    range_cltc: float | None = None
    # (battery kWh, CLTC range km, url) read on one page: one version's pair for the kWh/100 km estimate
    cltc_pair: tuple[float, float, str] | None = None
    use: en.UsageContext | None = None
    new_in_market: bool = False  # a make recently arrived in Spain: no class depreciation curve (spec 006 FR-018)
    stated: Mapping[str, tuple[float, str]] = field(default_factory=dict)  # the user's own consumption figures


@dataclass(frozen=True)
class TcoItem:
    kind: Kind
    label: str
    annual_eur: float | None
    five_year_eur: float | None
    basis: Basis
    inputs: list[str]
    evidence_ids: list[str] = field(default_factory=list)
    parts: list[en.EnergyPart] = field(default_factory=list)  # ENERGY only: electricity / fuel split (spec 006)
    missing: list[str] = field(default_factory=list)  # ENERGY only: inputs that stop the computation
    estimate: en.EnergyEstimate | None = None  # ENERGY only


@dataclass(frozen=True)
class TcoEstimate:
    car_id: str
    label: str
    condition: str
    age_years: int | None
    annual_km: int
    items: list[TcoItem]
    annual_total: float  # running cost per year (without depreciation)
    five_year_total: float  # total over `years` (running + depreciation); the name is kept for stored rows
    rules_version: str = RULES_VERSION
    years: int = 5  # the period the totals cover
    depreciation_left_out: bool = False  # another compared car has no value data: totals are running cost only

    @property
    def period_total(self) -> float:
        return self.five_year_total
