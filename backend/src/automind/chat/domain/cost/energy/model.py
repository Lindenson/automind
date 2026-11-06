"""The energy-cost model (spec 006 US1): powertrain groups and limits, prices with their basis and freshness, the
energy config, the usage context, the car facts and the estimate with its parts."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

PLUG_IN = ("PHEV", "EREV")


ELECTRIC = ("BEV", *PLUG_IN)


MAX_SHARE = 0.95


CLTC_FACTOR = 1.4  # default real-use allowance of a CLTC figure (config/rates.yaml real_world_factor.CLTC)


CS_MISSING = "fuel consumption with an empty battery"


# battery ÷ CLTC range outside this (kWh/100 km, battery side) is no road car's consumption: no estimate
EV_CLTC_PLAUSIBLE = (11.0, 30.0)


EV_MISSING = "electric consumption (kWh/100 km)"


FUEL_MISSING = "fuel consumption"


@dataclass(frozen=True)
class Price:
    value: float
    unit: str  # "kWh" | "l"
    label: str  # "home electricity (typical fixed tariff)"
    basis: str = "ASSUMPTION"  # ASSUMPTION | SOURCED | USER
    as_of: str | None = None
    stale: bool = False

    def line(self) -> str:
        when = f", {self.as_of}" if self.as_of else ""
        tag = {"USER": "your price", "SOURCED": "sourced"}.get(self.basis, "assumption")
        old = ", outdated" if self.stale else ""
        return f"{self.label} €{self.value:.2f}/{self.unit} ({tag}{when}{old})"


@dataclass(frozen=True)
class EnergyConfig:
    home: Price = Price(0.25, "kWh", "home electricity")
    public_ac: Price = Price(0.45, "kWh", "public AC charging")
    public_dc: Price = Price(0.60, "kWh", "public DC fast charging")
    driving_days: int = 300
    charge_probability: Mapping[str, float] = field(default_factory=lambda: {"YES": 0.9, "WORK": 0.9, "NO": 0.25})
    mix: Mapping[str, Mapping[str, float]] = field(
        default_factory=lambda: {
            "YES": {"home": 0.85, "public_ac": 0.05, "public_dc": 0.10},
            "WORK": {"home": 0.85, "public_ac": 0.05, "public_dc": 0.10},
            "NO": {"home": 0.0, "public_ac": 0.40, "public_dc": 0.60},
        }
    )
    losses_ac: float = 0.10
    losses_dc: float = 0.05
    climate: Mapping[str, float] = field(
        default_factory=lambda: {"HOT": 1.08, "MILD": 1.0, "COLD": 1.15, "MOUNTAIN": 1.20}
    )
    motorway_share: Mapping[str, float] = field(default_factory=lambda: {"MOTORWAY": 0.6, "CITY": 0.1, "default": 0.3})
    motorway_extra: float = 0.25

    petrol: Price | None = None  # sourced fuel prices (energy.yaml); None → rates.yaml
    diesel: Price | None = None

    @classmethod
    def from_config(
        cls,
        d: Mapping[str, Any] | None,
        home_override: float | None = None,
        ac_override: float | None = None,
        dc_override: float | None = None,
        night: bool = False,
        today: str | None = None,
    ) -> EnergyConfig:
        d = d or {}
        base = cls()
        p = d.get("prices") or {}
        habits = d.get("habits") or {}
        losses = d.get("losses") or {}
        mw = d.get("motorway") or {}
        home_key, home_label = (
            ("home_night", "home electricity (night tariff)")
            if night
            else ("home_fixed", "home electricity (typical fixed tariff)")
        )
        return cls(
            petrol=_price(p["petrol"], base.home, None, "petrol", today) if p.get("petrol") else None,
            diesel=_price(p["diesel"], base.home, None, "diesel", today) if p.get("diesel") else None,
            home=_price(p.get(home_key), base.home, home_override, home_label, today),
            public_ac=_price(p.get("public_ac"), base.public_ac, ac_override, "public AC charging", today),
            public_dc=_price(p.get("public_dc"), base.public_dc, dc_override, "public DC fast charging", today),
            driving_days=int(habits.get("driving_days", base.driving_days)),
            charge_probability={**base.charge_probability, **(habits.get("charge_probability") or {})},
            mix={**base.mix, **(d.get("mix") or {})},
            losses_ac=float(losses.get("home_ac", base.losses_ac)),
            losses_dc=float(losses.get("dc", base.losses_dc)),
            climate={**base.climate, **(d.get("climate") or {})},
            motorway_share={**base.motorway_share, **(mw.get("share") or {})},
            motorway_extra=float(mw.get("extra", base.motorway_extra)),
        )


def _price(
    entry: Mapping[str, Any] | None, default: Price, override: float | None, label: str, today: str | None = None
) -> Price:
    """A configured price with its date and basis; a user's own price wins. Older than `freshness_days` → stale."""
    if override is not None:
        return Price(float(override), "kWh", label, "USER")
    if not entry:
        return Price(default.value, default.unit, label)
    basis = "SOURCED" if entry.get("basis") == "sourced" else "ASSUMPTION"
    as_of = str(entry["as_of"]) if entry.get("as_of") else None
    return Price(
        float(entry["value"]),
        str(entry.get("unit") or "kWh"),
        label,
        basis,
        as_of,
        _stale(as_of, entry.get("freshness_days"), today),
    )


def _stale(as_of: str | None, days: Any, today: str | None) -> bool:
    if not (as_of and days and today):
        return False
    from datetime import date  # noqa: PLC0415 - only for this comparison

    try:
        return (date.fromisoformat(today[:10]) - date.fromisoformat(as_of[:10])).days > int(days)
    except ValueError:
        return False


@dataclass(frozen=True)
class UsageContext:
    annual_km: int
    daily_km: int | None = None
    climate: str | None = None  # HOT | MILD | COLD | MOUNTAIN
    usage: tuple[str, ...] = ()  # case usage codes (MOTORWAY, CITY…)
    home_charging: str = "UNKNOWN"  # YES | WORK | NO | UNKNOWN


@dataclass(frozen=True)
class EnergyCar:
    powertrain: str
    fuel: str | None = None  # petrol | diesel
    consumption: float | None = None  # official WLTP (l/100 km; kWh/100 km for a BEV in older rows)
    consumption_real: float | None = None
    consumption_nedc: float | None = None
    consumption_ev: float | None = None  # WLTP electric kWh/100 km (at the plug)
    consumption_ev_real: float | None = None  # tested kWh/100 km
    ev_real_meter: str | None = None  # "plug" | "battery" | None (unknown → battery, the honest upper cost)
    consumption_cs: float | None = None  # PHEV fuel with an empty battery
    consumption_weighted: float | None = None  # PHEV official WLTP weighted l/100 km: only for the CS estimate
    battery_kwh: float | None = None  # usable
    range_wltp: float | None = None
    range_real: float | None = None
    # a car sold only in China (chat 2026-11-06): its CLTC figures, used only without WLTP or real-world ones, with
    # their own real-use allowance (rates.yaml real_world_factor.CLTC)
    consumption_ev_cltc: float | None = None
    range_cltc: float | None = None
    # (battery kWh, CLTC range km, url) read on one page: the kWh/100 km estimate only from such a pair, never
    # from a battery and a range of different versions (Li L9 1st gen 42.8 kWh with the 2026 car's 420 km)
    cltc_pair: tuple[float, float, str] | None = None
    # the user's own figures (FUEL, CS, KWH, RANGE -> (value, their words)): used instead of sourced or estimated
    stated: Mapping[str, tuple[float, str]] = field(default_factory=dict)


@dataclass(frozen=True)
class EnergyPart:
    energy: str  # electricity | petrol | diesel
    km: int
    per_100km: float
    unit: str
    price: float
    annual_eur: float


@dataclass(frozen=True)
class EnergyEstimate:
    parts: list[EnergyPart]
    inputs: list[str]
    missing: list[str] = field(default_factory=list)
    electric_share: float | None = None
    factors: list[str] = field(default_factory=list)
    alt_eur_per_100km: float | None = None  # the other charging scenario (home ↔ public), BEV/PHEV
    alt_label: str | None = None

    @property
    def annual_eur(self) -> float | None:
        return round(sum(p.annual_eur for p in self.parts), 2) if self.parts and not self.missing else None

    @property
    def eur_per_100km(self) -> float | None:
        km = sum(p.km for p in self.parts)
        a = self.annual_eur
        return round(a / km * 100, 2) if a is not None and km else None

    @property
    def label(self) -> str:
        if self.missing:
            return f"Energy: cannot be computed — missing: {', '.join(self.missing)}"
        return f"Energy ({' + '.join(p.energy for p in self.parts)})"


@dataclass(frozen=True)
class Rates:
    """What the energy model needs from the TCO rates."""

    petrol: Price
    diesel: Price
    real_world_factor: Mapping[str, float]
    cfg: EnergyConfig
