"""Plausibility rules after unit normalisation (spec 003 FR-014; research R8). Pure.

Rules are data (config/plausibility.yaml), injected by the caller: ranges by powertrain/fuel, and
cross-attribute checks against values already known for the same car. Conservative by design.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Context:
    powertrain: str | None = None  # ICE | HEV | PHEV | MHEV | BEV
    fuel: str | None = None  # diesel | petrol | electric …
    known: Mapping[str, float] = field(default_factory=dict)  # canonical values already selected for the car
    transmission: str | None = None  # the identified variant's gearbox (spec 004 FR-028)
    drive: str | None = None  # FWD | RWD | AWD


@dataclass(frozen=True)
class PlausibilityResult:
    ok: bool
    rule_id: str | None = None
    message: str = ""


OK = PlausibilityResult(True)


def _pt_key(ctx: Context) -> str:
    pt = (ctx.powertrain or "").upper()
    fuel = (ctx.fuel or "").lower()
    if pt in ("ICE", "MHEV") and "diesel" in fuel:
        return "ICE_DIESEL"
    if pt in ("ICE", "MHEV"):
        return "ICE_PETROL"
    return pt or "ANY"


def _kw_per_t(power_kw: float | None, mass_kg: float | None) -> float | None:
    if not power_kw or not mass_kg:
        return None
    return power_kw / (mass_kg / 1000)


def _range(attribute: str, v: float, ctx: Context, rules: Mapping[str, Any]) -> PlausibilityResult:
    by_pt = (rules.get("by_powertrain") or {}).get(attribute)
    if by_pt:
        key = _pt_key(ctx)
        used = key if key in by_pt else "ANY"
        rng = by_pt.get(used)
        if rng and not (float(rng[0]) <= v <= float(rng[1])):
            return PlausibilityResult(False, f"{attribute}.{used}", f"{attribute}={v:g} outside {rng[0]}–{rng[1]}")
    pr = rules.get("price_eur")
    if attribute == "official_price_es" and pr and not (float(pr["min"]) <= v <= float(pr["max"])):
        return PlausibilityResult(False, "price_eur", f"price €{v:,.0f} outside €{pr['min']:,}–€{pr['max']:,}")
    return OK


def _cross(rule: Mapping[str, Any], attribute: str, v: float, known: Mapping[str, float]) -> PlausibilityResult:
    rid = str(rule["id"])
    pw = _kw_per_t(known.get("max_power"), known.get("curb_mass"))
    if rid == "pw_ratio_max" and attribute in ("max_power", "curb_mass") and pw is not None:
        if pw > float(rule["max_kw_per_t"]):
            return PlausibilityResult(False, rid, f"power-to-weight {pw:.0f} kW/t is not a road car")
    elif "below_kw_per_t" in rule and attribute in ("claimed_0_100", "measured_0_100") and pw is not None:
        if pw < float(rule["below_kw_per_t"]) and v < float(rule["min_0_100_s"]):
            return PlausibilityResult(False, rid, f"0–100 in {v:g} s is too quick for {pw:.0f} kW/t")
    elif rid == "measured_vs_claimed" and attribute == "measured_0_100" and known.get("claimed_0_100"):
        claimed = float(known["claimed_0_100"])
        if abs(v - claimed) / claimed > float(rule["max_rel_diff"]):
            return PlausibilityResult(False, rid, f"measured {v:g} s vs claimed {claimed:g} s")
    return OK


def check(attribute: str, value: float | str, ctx: Context, rules: Mapping[str, Any]) -> PlausibilityResult:
    if not isinstance(value, (int, float)):
        return OK
    v = float(value)
    r = _range(attribute, v, ctx, rules)
    if not r.ok:
        return r
    known = {**ctx.known, attribute: v}
    for rule in rules.get("cross") or []:
        r = _cross(rule, attribute, v, known)
        if not r.ok:
            return r
    return OK
