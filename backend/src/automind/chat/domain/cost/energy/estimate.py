"""The energy cost per powertrain (FR-001..FR-005, FR-013; R1-R3, R6): combustion, battery electric and plug-in
(utility factor, charge-sustaining estimate), with the charging mix and its price lines."""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

from automind.chat.domain.cost.energy.model import (
    CLTC_FACTOR,
    CS_MISSING,
    EV_CLTC_PLAUSIBLE,
    EV_MISSING,
    FUEL_MISSING,
    MAX_SHARE,
    PLUG_IN,
    EnergyCar,
    EnergyConfig,
    EnergyEstimate,
    EnergyPart,
    Price,
    Rates,
    UsageContext,
)


def fuel_consumption(car: EnergyCar, factor: Mapping[str, float]) -> tuple[float | None, str]:
    """Fuel l/100 km for a combustion car or hybrid: the user's own figure, real-world when sourced, else WLTP × the
    allowance, else NEDC."""
    if "FUEL" in car.stated:
        v, words = car.stated["FUEL"]
        return v, _yours(v, "l/100 km", words)
    if car.consumption_real:
        return car.consumption_real, f"real-world {car.consumption_real:g} (sourced test)"
    pt = (car.powertrain or "ICE").upper()
    if car.consumption:
        f = factor.get(pt, factor.get("ICE", 1.0))
        return round(car.consumption * f, 2), f"WLTP {car.consumption:g} × {f:g} real-use allowance (assumption)"
    if car.consumption_nedc:
        f = factor.get("NEDC", 1.0)
        return round(car.consumption_nedc * f, 2), (
            f"NEDC {car.consumption_nedc:g} × {f:g} real-use allowance (assumption)"
        )
    return None, ""


def estimate(car: EnergyCar, r: Rates, use: UsageContext) -> EnergyEstimate:
    pt = (car.powertrain or "ICE").upper()
    if pt == "BEV":
        return _with_alt(car, r, use, _bev)
    if pt in PLUG_IN:
        return _with_alt(car, r, use, _plug_in)
    return _combustion(car, r, use)


def _fuel_price(car: EnergyCar, r: Rates) -> tuple[Price, str]:
    return (r.diesel, "diesel") if car.fuel == "diesel" else (r.petrol, "petrol")


def _part(energy: str, km: float, per_100km: float, price: Price) -> EnergyPart:
    return EnergyPart(
        energy, round(km), round(per_100km, 2), price.unit, price.value, round(per_100km * km / 100 * price.value, 2)
    )


def _combustion(car: EnergyCar, r: Rates, use: UsageContext) -> EnergyEstimate:
    used, how = fuel_consumption(car, r.real_world_factor)
    if not used:
        return EnergyEstimate([], [f"{FUEL_MISSING} not found"], [FUEL_MISSING])
    price, what = _fuel_price(car, r)
    inputs = [f"consumption {used:g} l/100 km: {how}", price.line(), f"{use.annual_km:,} km/year"]
    return EnergyEstimate([_part(what, use.annual_km, used, price)], inputs)


def situation(use: UsageContext) -> tuple[str, bool]:
    """(YES | WORK | NO, assumed?) — unknown is assumed YES and labelled (research R5)."""
    hc = (use.home_charging or "UNKNOWN").upper()
    return ("YES", True) if hc not in ("YES", "WORK", "NO") else (hc, False)


def _mix(cfg: EnergyConfig, hc: str, plug_in: bool) -> dict[str, float]:
    m = dict(cfg.mix.get(hc) or cfg.mix["YES"])
    if plug_in:  # plug-in hybrids rarely fast-charge: their public share is AC
        m = {
            "home": m.get("home", 0.0),
            "public_ac": m.get("public_ac", 0.0) + m.get("public_dc", 0.0),
            "public_dc": 0.0,
        }
    return m


def _kwh_price(cfg: EnergyConfig, mix: Mapping[str, float]) -> float:
    return (
        mix.get("home", 0) * cfg.home.value
        + mix.get("public_ac", 0) * cfg.public_ac.value
        + mix.get("public_dc", 0) * cfg.public_dc.value
    )


def _losses(cfg: EnergyConfig, mix: Mapping[str, float]) -> float:
    return (mix.get("home", 0) + mix.get("public_ac", 0)) * cfg.losses_ac + mix.get("public_dc", 0) * cfg.losses_dc


def _mix_line(hc: str, assumed: bool, mix: Mapping[str, float]) -> str:
    where = {"YES": "home charging", "WORK": "charging at work", "NO": "no home charging"}[hc]
    tag = " (assumed — tell me if not)" if assumed else ""
    parts = [f"{k.replace('_', ' ')} {v * 100:.0f}%" for k, v in mix.items() if v]
    return f"{where}{tag}: {', '.join(parts)} (assumption)"


def _price_lines(cfg: EnergyConfig, mix: Mapping[str, float]) -> list[str]:
    names = {"home": cfg.home, "public_ac": cfg.public_ac, "public_dc": cfg.public_dc}
    return [names[k].line() for k, v in mix.items() if v]


def factors(cfg: EnergyConfig, use: UsageContext) -> tuple[float, list[str]]:
    """Multiplier on estimated electric consumption, relative to the mild-climate mixed use behind the allowance."""
    out, lines = 1.0, []
    clim = (use.climate or "").upper()
    cf = cfg.climate.get(clim, 1.0) if clim else 1.0
    if cf != 1.0:
        out *= cf
        lines.append(f"{clim.lower()} climate ×{cf:g} (assumption)")
    codes = {u.upper() for u in use.usage}
    share = (
        cfg.motorway_share.get("MOTORWAY")
        if "MOTORWAY" in codes
        else (cfg.motorway_share.get("CITY") if codes == {"CITY"} else None)
    )
    if share is not None:
        base = cfg.motorway_share.get("default", 0.3)
        mf = round(1 + cfg.motorway_extra * (share - base), 3)
        out *= mf
        lines.append(f"motorway share {share * 100:.0f}% ×{mf:g} (assumption)")
    return out, lines


def _ev_kwh(
    car: EnergyCar, r: Rates, use: UsageContext, mix: Mapping[str, float]
) -> tuple[float | None, list[str], list[str]]:
    """kWh/100 km bought from the grid, with how it was obtained and the factors applied."""
    allowance = r.real_world_factor.get("BEV", 1.2)
    loss = _losses(r.cfg, mix)
    if "KWH" in car.stated:  # what the car's display shows: battery side, the charging losses are added
        v, words = car.stated["KWH"]
        return v * (1 + loss), [_yours(v, "kWh/100 km", words)], [f"charging losses +{loss * 100:.0f}% (assumption)"]
    if car.consumption_ev_real:
        meter = car.ev_real_meter or "battery"
        kwh = car.consumption_ev_real * (1 + loss if meter == "battery" else 1)
        how = f"real-world {car.consumption_ev_real:g} kWh/100 km (sourced test, measured at the {meter})"
        fl = [f"charging losses +{loss * 100:.0f}% (assumption)"] if meter == "battery" else []
        return kwh, [how], fl
    wltp, derived = car.consumption_ev, False
    if wltp is None and car.powertrain == "BEV":
        wltp = car.consumption
    if wltp is None and car.battery_kwh and car.range_wltp:
        wltp, derived = car.battery_kwh / car.range_wltp * 100, True
    if wltp is None and car.consumption_ev_cltc:
        f, fl = factors(r.cfg, use)
        cltc = r.real_world_factor.get("CLTC", CLTC_FACTOR)
        how = (f"CLTC (China) {car.consumption_ev_cltc:g} kWh/100 km × {cltc:g} real-use allowance for the Chinese "
               "cycle (assumption)")  # fmt: skip
        return car.consumption_ev_cltc * cltc * f, [how], fl
    if wltp is None and car.cltc_pair and car.cltc_pair[0] and car.cltc_pair[1]:
        # Chinese pages rarely state kWh/100 km for a range-extended car (chat 2026-11-06): battery ÷ CLTC range is
        # battery-side CLTC energy, so the CLTC allowance, the climate/motorway factors and the losses are applied
        kwh_b, km, url = car.cltc_pair
        f, fl = factors(r.cfg, use)
        cltc = r.real_world_factor.get("CLTC", CLTC_FACTOR)
        base = kwh_b / km * 100
        if not EV_CLTC_PLAUSIBLE[0] <= base <= EV_CLTC_PLAUSIBLE[1]:
            return None, [], []
        fl.append(f"charging losses +{loss * 100:.0f}% (assumption)")
        how = (f"ESTIMATE {base:.1f} kWh/100 km ({kwh_b:g} kWh battery ÷ {km:g} km CLTC, China, both from {url}) "
               f"× {cltc:g} real-use allowance for the Chinese cycle")  # fmt: skip
        return base * cltc * f * (1 + loss), [how], fl
    if wltp is None:
        return None, [], []
    f, fl = factors(r.cfg, use)
    kwh = wltp * allowance * f
    if derived:  # usable kWh ÷ range is battery-side energy: losses are added once
        kwh *= 1 + loss
        fl.append(f"charging losses +{loss * 100:.0f}% (assumption)")
        how = (
            f"derived {wltp:.1f} kWh/100 km ({car.battery_kwh:g} kWh usable ÷ {car.range_wltp:g} km WLTP) "
            f"× {allowance:g} real-use allowance"
        )
    else:
        how = f"WLTP {wltp:g} kWh/100 km (at the plug) × {allowance:g} real-use allowance (assumption)"
    return kwh, [how], fl


def _bev(car: EnergyCar, r: Rates, use: UsageContext, hc: str, assumed: bool) -> EnergyEstimate:
    mix = _mix(r.cfg, hc, plug_in=False)
    kwh, how, fl = _ev_kwh(car, r, use, mix)
    if kwh is None:
        return EnergyEstimate([], [f"{EV_MISSING} not found"], [EV_MISSING])
    price = Price(round(_kwh_price(r.cfg, mix), 4), "kWh", "electricity")
    inputs = [
        f"consumption {kwh:.1f} kWh/100 km: {how[0]}",
        *fl,
        _mix_line(hc, assumed, mix),
        *_price_lines(r.cfg, mix),
        f"{use.annual_km:,} km/year",
    ]
    return EnergyEstimate([_part("electricity", use.annual_km, kwh, price)], inputs, factors=fl)


def electric_range(car: EnergyCar, r: Rates, use: UsageContext) -> tuple[float | None, str]:
    """Real electric range: the user's figure, sourced when found, else WLTP ÷ (allowance × climate and motorway)."""
    if "RANGE" in car.stated:
        v, words = car.stated["RANGE"]
        return v, f"real electric range {_yours(v, 'km', words)}"
    if car.range_real:
        return car.range_real, f"real-world electric range {car.range_real:g} km (sourced)"
    rng_cltc = car.cltc_pair[1] if car.cltc_pair else car.range_cltc
    if not car.range_wltp and rng_cltc:
        f, _ = factors(r.cfg, use)
        cltc = r.real_world_factor.get("CLTC", CLTC_FACTOR)
        real = rng_cltc / (cltc * f)
        return real, (f"real electric range ≈ {real:.0f} km (CLTC, China {rng_cltc:g} km ÷ {cltc * f:.2f}, "
                      "assumption)")  # fmt: skip
    if not car.range_wltp:
        return None, ""
    f, _ = factors(r.cfg, use)
    allowance = r.real_world_factor.get("BEV", 1.2)
    real = car.range_wltp / (allowance * f)
    return real, f"real electric range ≈ {real:.0f} km (WLTP {car.range_wltp:g} km ÷ {allowance * f:.2f}, assumption)"


def share(car: EnergyCar, r: Rates, use: UsageContext, hc: str) -> tuple[float | None, list[str]]:
    """Share of the yearly km driven on electricity (research R2)."""
    rng, rng_how = electric_range(car, r, use)
    if not rng:
        return None, []
    if use.daily_km:
        d, d_how = float(use.daily_km), f"{use.daily_km} km a day"
    else:
        d = use.annual_km / r.cfg.driving_days
        d_how = f"≈{d:.0f} km a day ({use.annual_km:,} km ÷ {r.cfg.driving_days} driving days, assumption)"
    h = r.cfg.charge_probability.get(hc, 0.9)
    s = min(MAX_SHARE, h * min(d, rng) / d) if d else 0.0
    return s, [
        d_how,
        rng_how,
        f"charged on {h * 100:.0f}% of driving days (assumption)",
        f"electric share {s * 100:.0f}%",
    ]


# EU utility factor (Regulation (EU) 2017/1151, Annex XXI, Sub-annex 8, Appendix 5): share of distance in charge
# depleting mode for an electric range d, with d_n = 800 km.
UF_K = (26.25, -38.94, -631.05, 5964.83, -25095.0, 60380.2, -87517.0, 75513.8, -35749.0, 7154.94)


UF_MAX = 0.85  # beyond ≈75 km the inverse is too sensitive: no estimate


CS_PLAUSIBLE = (3.5, 14.0)


def utility_factor(range_km: float) -> float:
    x = range_km / 800.0
    return 1.0 - math.exp(-sum(k * x ** (i + 1) for i, k in enumerate(UF_K)))


def estimate_cs(weighted: float | None, range_km: float | None) -> float | None:
    """Spec 009 FR-014: charge-sustaining l/100 km from the official weighted figure and electric range.
    weighted ≈ (1 − UF) × CS, so CS ≈ weighted / (1 − UF). None when the inputs cannot support it."""
    if not weighted or not range_km or weighted <= 0 or range_km <= 0:
        return None
    uf = utility_factor(range_km)
    if uf <= 0 or uf > UF_MAX:
        return None
    cs = weighted / (1.0 - uf)
    return round(cs, 2) if CS_PLAUSIBLE[0] <= cs <= CS_PLAUSIBLE[1] else None


def _plug_in(car: EnergyCar, r: Rates, use: UsageContext, hc: str, assumed: bool) -> EnergyEstimate:
    mix = _mix(r.cfg, hc, plug_in=True)
    kwh, how, fl = _ev_kwh(car, r, use, mix)
    s, s_lines = share(car, r, use, hc)
    yours = car.stated.get("CS")
    est = None if (car.consumption_cs or yours) else estimate_cs(car.consumption_weighted, car.range_wltp)
    missing = [
        m
        for m, ok in (
            (EV_MISSING, kwh is not None),
            ("electric range", s is not None),
            (CS_MISSING, bool(car.consumption_cs or yours or est)),
        )
        if not ok
    ]
    if missing or kwh is None or s is None or not (car.consumption_cs or yours or est):
        why = [f"missing: {', '.join(missing)}", "the weighted WLTP figure is not a real consumption and is not used"]
        return EnergyEstimate([], why, missing)
    fuel_price, what = _fuel_price(car, r)
    if yours:
        cs, cs_line = yours[0], f"{what} with an empty battery: {_yours(yours[0], 'l/100 km', yours[1])}"
    elif est is not None and not car.consumption_cs:
        f = r.real_world_factor.get("HEV", r.real_world_factor.get("ICE", 1.15))
        cs = est * f
        cs_line = (
            f"{what} {cs:.1f} l/100 km with an empty battery: ESTIMATE from the official weighted WLTP "
            f"{car.consumption_weighted:g} l/100 km and {car.range_wltp:g} km electric range by the EU utility "
            f"factor ({est:.1f} l/100 km) × {f:g} real-use allowance"
        )
    else:
        f = r.real_world_factor.get("HEV", r.real_world_factor.get("ICE", 1.15))
        cs = (car.consumption_cs or 0.0) * f
        cs_line = (
            f"{what} {cs:.1f} l/100 km: charge-sustaining {car.consumption_cs:g} × {f:g} real-use allowance "
            "(assumption)"
        )
    e_price = Price(round(_kwh_price(r.cfg, mix), 4), "kWh", "electricity")
    e_km, f_km = use.annual_km * s, use.annual_km * (1 - s)
    inputs = [
        *s_lines,
        f"electricity {kwh:.1f} kWh/100 km: {how[0]}",
        *fl,
        _mix_line(hc, assumed, mix),
        *_price_lines(r.cfg, mix),
        cs_line,
        fuel_price.line(),
        f"{use.annual_km:,} km/year",
    ]
    parts = [_part("electricity", e_km, kwh, e_price), _part(what, f_km, cs, fuel_price)]
    return EnergyEstimate(parts, inputs, electric_share=round(s, 3), factors=fl)


def _with_alt(car: EnergyCar, r: Rates, use: UsageContext, fn: Any) -> EnergyEstimate:
    hc, assumed = situation(use)
    main: EnergyEstimate = fn(car, r, use, hc, assumed)
    other = "NO" if hc in ("YES", "WORK") else "YES"
    alt: EnergyEstimate = fn(car, r, use, other, False)
    label = "without home charging" if other == "NO" else "with home charging"
    return EnergyEstimate(
        main.parts,
        main.inputs,
        main.missing,
        main.electric_share,
        main.factors,
        alt.eur_per_100km,
        label if alt.eur_per_100km is not None else None,
    )


def _yours(value: float, unit: str, words: str) -> str:
    return f'your figure {value:g} {unit} (you said: "{words}")'
