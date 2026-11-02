"""Drag race simulation v0.1 (spec 001 FR-023..FR-028, research R9). Pure and deterministic."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass, field
from dataclasses import replace as _replace
from typing import Any, TypeVar

_T = TypeVar("_T")

MODEL_VERSION = "dragrace-0.1.0"
G = 9.81
DT = 0.005
SAMPLE_EVERY = 10  # -> 0.05 s

BODY_DEFAULTS = {  # (Cd, frontal area m²)
    "HATCHBACK": (0.31, 2.2),
    "SEDAN": (0.28, 2.2),
    "SUV": (0.34, 2.6),
    "COUPE": (0.30, 2.0),
    "WAGON": (0.30, 2.25),
    "CONVERTIBLE": (0.33, 2.0),
    "MPV": (0.33, 2.6),
    "PICKUP": (0.40, 2.9),
}
DRIVEN_FRACTION = {"FWD": 0.55, "RWD": 0.52, "AWD": 1.0}


@dataclass(frozen=True)
class RaceSettings:
    surface: str = "DRY"  # DRY | WET
    extra_load_kg: float = 0.0
    temperature_c: float = 20.0
    altitude_m: float = 0.0


@dataclass(frozen=True)
class CarInput:
    car_id: str
    label: str
    powertrain: str  # ICE | BEV | HEV | PHEV | MHEV
    power_kw: float | None
    mass_kg: float | None
    drivetrain: str | None = None
    transmission: str | None = None
    top_speed_kmh: float | None = None
    body_class: str | None = None
    cd: float | None = None
    frontal_area_m2: float | None = None
    claimed_0_100: float | None = None


@dataclass
class CarResult:
    car_id: str
    label: str
    rank: int = 0
    t_0_100: float | None = None
    t_0_200: float | None = None
    t_400m: float | None = None
    v_400m: float | None = None
    claimed_0_100: float | None = None
    t: list[float] = field(default_factory=list)
    v_kmh: list[float] = field(default_factory=list)
    s_m: list[float] = field(default_factory=list)
    assumptions: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass
class RaceResult:
    model_version: str
    settings: RaceSettings
    results: list[CarResult]
    excluded: list[dict[str, Any]]
    input_hash: str


def air_density(temp_c: float, alt_m: float) -> float:
    p = 101325.0 * (1 - 2.25577e-5 * alt_m) ** 5.25588
    return float(p / (287.05 * (temp_c + 273.15)))


def _assume(items: list[dict[str, Any]], name: str, value: _T, unit: str | None, reason: str) -> _T:
    items.append({"name": name, "value": value, "unit": unit, "reason": reason})
    return value


@dataclass(frozen=True)
class _Params:
    """Physical parameters for one car after defaults/assumptions are applied."""

    cd: float
    area: float
    crr: float
    eta: float
    p_w: float
    m: float
    m_eff: float
    vmax: float
    rho: float
    f_trac: float
    ev: bool
    f_max: float = 0.0  # BEV: constant-force region limit
    k: float = 1.0  # ICE/hybrid: power utilisation incl. shifts


def _assumptions(car: CarInput, st: RaceSettings, res: CarResult) -> _Params:
    """Fill missing inputs with labelled assumptions (order of `res.assumptions` is part of the output)."""
    a = res.assumptions
    body = car.body_class if car.body_class in BODY_DEFAULTS else "HATCHBACK"
    cd = car.cd if car.cd else _assume(a, "drag_coefficient", BODY_DEFAULTS[body][0], None, f"default for {body}")
    area = (
        car.frontal_area_m2
        if car.frontal_area_m2
        else _assume(a, "frontal_area", BODY_DEFAULTS[body][1], "m²", f"default for {body}")
    )
    drive = (
        car.drivetrain
        if car.drivetrain in DRIVEN_FRACTION
        else _assume(a, "drivetrain", "FWD", None, "unknown drivetrain")
    )
    frac = _assume(a, "driven_axle_load_fraction", DRIVEN_FRACTION[drive], None, f"{drive} static + transfer")
    wet = st.surface == "WET"
    mu = _assume(a, "tyre_grip_mu", 0.7 if wet else 1.0, None, "wet road" if wet else "dry road, street tyres")
    crr = _assume(a, "rolling_resistance", 0.014 if wet else 0.012, None, "typical passenger tyre")
    ev = car.powertrain == "BEV"
    eta = _assume(a, "drivetrain_efficiency", 0.90 if ev else 0.85, None, "BEV" if ev else "ICE/hybrid")
    rot = _assume(a, "rotational_inertia_factor", 0.05 if ev else 0.08, None, "BEV" if ev else "ICE/hybrid")
    p_w = car.power_kw * 1000  # type: ignore[operator]
    m = car.mass_kg + st.extra_load_kg  # type: ignore[operator]
    vmax = (car.top_speed_kmh or 250.0) / 3.6
    if not car.top_speed_kmh:
        _assume(a, "top_speed", 250, "km/h", "unknown top speed")
    base = _Params(
        cd=cd, area=area, crr=crr, eta=eta, p_w=p_w, m=m, m_eff=m * (1 + rot), vmax=vmax,
        rho=air_density(st.temperature_c, st.altitude_m), f_trac=mu * m * G * frac, ev=ev,
    )  # fmt: skip
    if ev:
        v_base = _assume(a, "motor_base_speed", round(0.35 * vmax * 3.6, 1), "km/h", "0.35 × top speed") / 3.6
        return _replace(base, f_max=eta * p_w / v_base)
    gearbox = (car.transmission or "").lower()
    manual = "manual" in gearbox or "manuel" in gearbox
    k = _assume(
        a,
        "power_utilisation_k",
        0.80 if manual else 0.85,
        None,
        "manual gearbox incl. shifts" if manual else "automatic/DCT incl. shifts",
    )
    if car.powertrain in ("HEV", "PHEV"):
        res.notes.append("combined system power simplification")
    return _replace(base, k=k)


def _forces(p: _Params, v: float) -> float:
    """Net longitudinal force (N) at speed v (m/s): min(power, traction) − aero drag − rolling resistance."""
    vv = max(v, 2.0)
    if v >= p.vmax:
        f_pow = 0.0
    elif p.ev:
        f_pow = min(p.f_max, p.eta * p.p_w / vv)
    else:
        f_pow = p.eta * p.p_w * p.k / vv
    return min(f_pow, p.f_trac) - 0.5 * p.rho * p.cd * p.area * v * v - p.crr * p.m * G


def _crossing(t: float, v: float, v_new: float, target: float) -> float | None:
    """Interpolated time at which speed crosses `target` during this step, if it does."""
    return t + DT * (target - v) / (v_new - v) if v < target <= v_new else None


def _integrate(p: _Params, res: CarResult) -> None:
    """Explicit Euler integration over 400 m (max 60 s), sampling the time series."""
    t = v = s = 0.0
    step = 0
    t100: float | None = None
    t200: float | None = None
    while s < 400.0 and t < 60.0:
        v_new = max(0.0, v + _forces(p, v) / p.m_eff * DT)
        s_new = s + v_new * DT
        t100 = t100 if t100 is not None else _crossing(t, v, v_new, 100 / 3.6)
        t200 = t200 if t200 is not None else _crossing(t, v, v_new, 200 / 3.6)
        if s < 400.0 <= s_new:
            frac400 = (400.0 - s) / (s_new - s)
            res.t_400m = round(t + DT * frac400, 2)
            res.v_400m = round((v + (v_new - v) * frac400) * 3.6, 1)
        t, v, s = t + DT, v_new, s_new
        step += 1
        if step % SAMPLE_EVERY == 0 or s >= 400.0:
            res.t.append(round(t, 2))
            res.v_kmh.append(round(v * 3.6, 1))
            res.s_m.append(round(min(s, 400.0), 1))
    res.t_0_100 = round(t100, 2) if t100 is not None else None
    res.t_0_200 = round(t200, 2) if t200 is not None else None


def _simulate_one(car: CarInput, st: RaceSettings) -> CarResult:
    res = CarResult(car.car_id, car.label, claimed_0_100=car.claimed_0_100)
    _integrate(_assumptions(car, st, res), res)
    return res


def _hash(cars: list[CarInput], st: RaceSettings) -> str:
    payload = json.dumps({"v": MODEL_VERSION, "cars": [asdict(c) for c in cars], "s": asdict(st)}, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()


def simulate(cars: list[CarInput], settings: RaceSettings | None = None) -> RaceResult:
    st = settings or RaceSettings()
    ok, excluded = [], []
    for c in cars:
        missing = [n for n, val in (("power", c.power_kw), ("weight", c.mass_kg)) if not val]
        if missing:
            excluded.append({"car_id": c.car_id, "label": c.label, "reason": f"missing {', '.join(missing)}"})
        else:
            ok.append(_simulate_one(c, st))
    ok.sort(key=lambda r: (r.t_400m if r.t_400m is not None else math.inf, r.car_id))
    for i, r in enumerate(ok, 1):
        r.rank = i
    return RaceResult(MODEL_VERSION, st, ok, excluded, _hash(cars, st))
