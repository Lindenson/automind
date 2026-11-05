"""Physical consistency of one variant's values (spec 011 research R8). Pure; thresholds from config/physics.yaml.

Six checks, each skipped when an input is missing:

1. `power_mass_accel`  0–100 km/h time vs kg/kW, within an envelope by powertrain/drivetrain ± slack
2. `torque_power`      combustion engines: P[kW] ≤ T[N·m] × rpm_max / 9549 (rpm_max by fuel); a torque below the
                       minimum the power implies points at the torque (a hybrid's engine-only torque next to the
                       system power)
3. `bev_range_energy`  battery kWh × 1000 / range km within the Wh/km band and within `rel` of the stated Wh/km
4. `co2_consumption`   WLTP CO2 g/km ≈ factor(fuel) × l/100 km ± rel
5. `displacement_geometry`  π/4 × bore² × stroke × cylinders within `rel` of the displacement
6. `top_speed_power`   top speed ≤ (2·η·P / (ρ·CdA))^(1/3) × (1 + slack) — only gross outliers

The outlier is the value whose removal makes the whole set consistent; several → the one with the fewest independent
families behind it; still tied → the check's own suspect (torque for `torque_power`), else none (no signal).
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

PETROL_LIKE = frozenset({"petrol", "hybrid", "mhev", "phev", "lpg", "cng", "e85", "hev"})


@dataclass(frozen=True)
class Facts:
    values: Mapping[str, float]  # attribute -> value in its canonical unit
    fuel: str | None = None  # petrol | diesel | hybrid | mhev | phev | bev | lpg
    powertrain: str | None = None  # ICE | HEV | MHEV | PHEV | BEV
    drivetrain: str | None = None  # FWD | RWD | AWD
    body: str | None = None
    families: Mapping[str, int] = field(default_factory=dict)  # attribute -> independent families behind it

    def without(self, attr: str) -> Facts:
        return Facts({k: v for k, v in self.values.items() if k != attr}, self.fuel, self.powertrain,
                     self.drivetrain, self.body, self.families)  # fmt: skip

    def get(self, *names: str) -> float | None:
        for n in names:
            v = self.values.get(n)
            if v is not None and v > 0:
                return float(v)
        return None

    @property
    def bev(self) -> bool:
        return (self.fuel or "").lower() == "bev" or (self.powertrain or "").upper() == "BEV"


@dataclass(frozen=True)
class Inconsistency:
    check: str
    values: dict[str, float]  # the values involved
    about: str  # the attribute the expected range is about
    expected: tuple[float | None, float | None]  # range of `about` the other values imply
    suspect: str | None = None  # the check's own suspect when removal and families do not decide


@dataclass(frozen=True)
class Outlier:
    attribute: str | None
    rule: str  # removal | families | suspect | tie | none
    inconsistencies: list[Inconsistency]


def _envelope(f: Facts, env: Mapping[str, Any]) -> list[list[float]] | None:
    keys = [f"{f.powertrain}|{f.drivetrain}", str(f.powertrain), "default"]
    for k in keys:
        if k in env and env[k]:
            return sorted(([float(x) for x in b] for b in env[k]), key=lambda b: b[0])
    return None


def _power_mass_accel(f: Facts, c: Mapping[str, Any]) -> Inconsistency | None:
    p, m, t = f.get("max_power"), f.get("curb_mass"), f.get("claimed_0_100")
    buckets = _envelope(f, c.get("envelope") or {})
    if p is None or m is None or t is None or not buckets:
        return None
    ratio = m / p
    bucket = next((b for b in buckets if ratio <= b[0]), None)
    if bucket is None:
        return None
    slack = float(c.get("slack", 0.15))
    lo, hi = bucket[1] * (1 - slack), bucket[2] * (1 + slack)
    if lo <= t <= hi:
        return None
    vals = {"max_power": p, "curb_mass": m, "claimed_0_100": t}
    return Inconsistency("power_mass_accel", vals, "claimed_0_100", (lo, hi))


def _torque_power(f: Facts, c: Mapping[str, Any]) -> Inconsistency | None:
    p, tq = f.get("max_power"), f.get("max_torque")
    if p is None or tq is None or f.bev:
        return None
    fuel = (f.fuel or "petrol").lower()
    rpm_cfg = c.get("rpm_max") or {}
    rpm = float(rpm_cfg.get("diesel" if fuel == "diesel" else "petrol", 7500))
    if fuel != "diesel" and fuel not in PETROL_LIKE:
        return None
    min_torque = p * 9549 / rpm
    if tq >= min_torque:
        return None
    return Inconsistency("torque_power", {"max_power": p, "max_torque": tq}, "max_torque", (min_torque, None),
                         suspect="max_torque")  # fmt: skip


def _bev_range_energy(f: Facts, c: Mapping[str, Any]) -> Inconsistency | None:
    kwh, km = f.get("battery_kwh"), f.get("range_wltp", "range_wltp_km")
    if not f.bev or kwh is None or km is None:
        return None
    wh_km = kwh * 1000 / km
    band = [float(x) for x in c.get("wh_km_band") or (120, 300)]
    vals = {"battery_kwh": kwh, "range_wltp": km}
    stated = f.get("energy_wh_km")
    if stated is None and f.get("consumption_ev") is not None:
        stated = float(f.get("consumption_ev") or 0) * 10  # kWh/100 km -> Wh/km
    rel = float(c.get("rel", 0.15))
    if not band[0] <= wh_km <= band[1]:
        return Inconsistency("bev_range_energy", vals, "range_wltp", (kwh * 1000 / band[1], kwh * 1000 / band[0]))
    if stated is not None and abs(wh_km - stated) > rel * stated:
        vals["energy_wh_km"] = stated
        return Inconsistency("bev_range_energy", vals, "range_wltp",
                             (kwh * 1000 / (stated * (1 + rel)), kwh * 1000 / (stated * (1 - rel))))  # fmt: skip
    return None


def _co2_consumption(f: Facts, c: Mapping[str, Any]) -> Inconsistency | None:
    co2, l100 = f.get("co2_wltp"), f.get("consumption_wltp", "consumption")
    fuel = (f.fuel or "").lower()
    if co2 is None or l100 is None or fuel in ("phev", "bev", "lpg", "cng", ""):
        return None
    factors = c.get("g_per_l100") or {}
    factor = float(factors.get("diesel" if fuel == "diesel" else "petrol", 23.8))
    expect, rel = factor * l100, float(c.get("rel", 0.08))
    if abs(co2 - expect) <= rel * expect:
        return None
    return Inconsistency("co2_consumption", {"co2_wltp": co2, "consumption": l100}, "co2_wltp",
                         (expect * (1 - rel), expect * (1 + rel)))  # fmt: skip


def _displacement_geometry(f: Facts, c: Mapping[str, Any]) -> Inconsistency | None:
    cc, bore, stroke, cyl = f.get("displacement"), f.get("bore"), f.get("stroke"), f.get("cylinders")
    if cc is None or bore is None or stroke is None or cyl is None:
        return None
    expect = math.pi / 4 * (bore / 10) ** 2 * (stroke / 10) * cyl  # mm -> cm
    rel = float(c.get("rel", 0.03))
    if abs(cc - expect) <= rel * expect:
        return None
    vals = {"displacement": cc, "bore": bore, "stroke": stroke, "cylinders": cyl}
    return Inconsistency("displacement_geometry", vals, "displacement", (expect * (1 - rel), expect * (1 + rel)))


def _top_speed_power(f: Facts, c: Mapping[str, Any]) -> Inconsistency | None:
    p, vmax = f.get("max_power"), f.get("top_speed")
    if p is None or vmax is None:
        return None
    cda_by = c.get("cda_by_body") or {}
    cda = float(cda_by.get((f.body or "").lower()) or cda_by.get("default", 0.75))
    eta, rho = float(c.get("efficiency", 0.85)), float(c.get("air_density", 1.2))
    limit = (2 * eta * p * 1000 / (rho * cda)) ** (1 / 3) * 3.6 * (1 + float(c.get("slack", 0.25)))
    if vmax <= limit:
        return None
    return Inconsistency("top_speed_power", {"max_power": p, "top_speed": vmax}, "top_speed", (None, limit))


CHECKS: dict[str, Callable[[Facts, Mapping[str, Any]], Inconsistency | None]] = {
    "power_mass_accel": _power_mass_accel,
    "torque_power": _torque_power,
    "bev_range_energy": _bev_range_energy,
    "co2_consumption": _co2_consumption,
    "displacement_geometry": _displacement_geometry,
    "top_speed_power": _top_speed_power,
}


def check_all(f: Facts, cfg: Mapping[str, Any]) -> list[Inconsistency]:
    """`cfg` is `config/physics.yaml: checks` (one mapping per check)."""
    out = []
    for name, fn in CHECKS.items():
        inc = fn(f, cfg.get(name) or {})
        if inc is not None:
            out.append(inc)
    return out


def outlier(f: Facts, cfg: Mapping[str, Any]) -> Outlier:
    incs = check_all(f, cfg)
    if not incs:
        return Outlier(None, "none", [])
    involved = sorted({a for i in incs for a in i.values})
    fixes = [a for a in involved if not check_all(f.without(a), cfg)]
    if len(fixes) == 1:
        return Outlier(fixes[0], "removal", incs)
    if not fixes:
        return Outlier(None, "tie", incs)
    fam = {a: int(f.families.get(a, 1)) for a in fixes}
    fewest = min(fam.values())
    least = [a for a in fixes if fam[a] == fewest]
    if len(least) == 1:
        return Outlier(least[0], "families", incs)
    suspects = {i.suspect for i in incs if i.suspect in least}
    if len(suspects) == 1:
        return Outlier(suspects.pop(), "suspect", incs)
    return Outlier(None, "tie", incs)
