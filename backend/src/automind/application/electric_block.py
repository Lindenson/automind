"""The compact "electric" report section (spec 006 US7, FR-019, contracts/blocks-electric-and-tco.md).

The same rows for every electric or plug-in car; a value that was not found is null ("not found" in the UI).
Computed values (real range from factors, full-charge time, electric share, cost per 100 km) carry their inputs.
A combustion car in the same comparison appears only with its cost per 100 km, so both compare on one scale.
"""

from __future__ import annotations

from typing import Any

from automind.domain import energy as en
from automind.domain import tco

ROWS = ["battery", "range", "consumption", "charging_home", "charging_dc", "electric_share", "cost_per_100km",
        "label"]  # fmt: skip
TITLE = {"en": "Electric", "ru": "Электро", "es": "Eléctrico"}


def _num(car: dict[str, Any], key: str) -> float | None:
    sv = car["values"].get(key)
    return sv.value_num if sv is not None and sv.available else None


def _txt(car: dict[str, Any], key: str) -> str | None:
    sv = car["values"].get(key)
    return sv.value_text if sv is not None and sv.available else None


def _estimate(e: tco.TcoEstimate) -> en.EnergyEstimate | None:
    item = next((i for i in e.items if i.kind == "ENERGY"), None)
    return item.estimate if item is not None else None


def _cost(est: en.EnergyEstimate | None, home: str) -> dict[str, Any]:
    if est is None or est.eur_per_100km is None:
        return {"used_eur": None, "home_eur": None, "public_eur": None, "missing": list(est.missing) if est else []}
    at_home = home in ("YES", "WORK", "UNKNOWN")
    alt = est.alt_eur_per_100km
    return {"used_eur": est.eur_per_100km, "home_eur": est.eur_per_100km if at_home else alt,
            "public_eur": alt if at_home else est.eur_per_100km, "missing": []}  # fmt: skip


def _car_values(car: dict[str, Any], t: tco.TcoCar, est: en.EnergyEstimate | None, r: tco.TcoRates,
                label: dict[str, Any] | None) -> dict[str, Any]:  # fmt: skip
    use = t.use or en.UsageContext(annual_km=15000)
    ecar = tco._energy_car(t)  # noqa: SLF001 - same model the cost uses
    real, real_how = en.electric_range(ecar, tco.energy_rates(r), use)
    ac = _num(car, "charge_ac_kw")
    usable = t.battery_kwh
    full_h = round(usable / (ac * 0.9), 1) if usable and ac else None  # 90 % average of the AC peak (assumption)
    return {
        "battery": {"usable_kwh": usable, "gross_kwh": _num(car, "battery_gross_kwh"),
                    "chemistry": _txt(car, "battery_chemistry")},
        "range": {"wltp_km": t.range_wltp, "real_km": round(real) if real else None,
                  "real_basis": "SOURCED" if t.range_real else ("ASSUMPTION" if real else None),
                  "how": real_how or None},
        "consumption": {"kwh_per_100km": t.consumption_ev or (t.consumption if t.powertrain == "BEV" else None),
                        "real_kwh_per_100km": t.consumption_ev_real},
        "charging_home": {"ac_kw": ac, "full_h": full_h},
        "charging_dc": {"peak_kw": _num(car, "charge_dc_peak_kw"), "min_10_80": _num(car, "charge_dc_10_80_min")},
        "electric_share": {"share": est.electric_share if est else None,
                           "inputs": [i for i in (est.inputs if est else []) if "share" in i or "day" in i]},
        "cost_per_100km": _cost(est, use.home_charging),
        "label": label,
    }  # fmt: skip


def build(cars: list[dict[str, Any]], tcars: list[tco.TcoCar], estimates: list[tco.TcoEstimate],
          rates: tco.TcoRates, labels: dict[str, Any], lang: str | None,
          incentives: dict[str, list[dict[str, Any]]] | None = None) -> dict[str, Any] | None:  # fmt: skip
    """None when no electric or plug-in car is compared."""
    by_id = {e.car_id: e for e in estimates}
    rows, others = [], []
    for car, t in zip(cars, tcars, strict=True):
        est = _estimate(by_id[t.car_id]) if t.car_id in by_id else None
        if t.powertrain in en.ELECTRIC:
            rows.append({"car_id": t.car_id, "label": t.label, "powertrain": t.powertrain,
                         "values": _car_values(car, t, est, rates, labels.get(t.car_id))})  # fmt: skip
        else:
            others.append({"car_id": t.car_id, "label": t.label,
                           "cost_per_100km_eur": est.eur_per_100km if est else None,
                           "label_dgt": labels.get(t.car_id)})  # fmt: skip
    if not rows:
        return None
    cfg = rates.energy
    notes = [p.line() for p in (cfg.home, cfg.public_ac, cfg.public_dc)]
    seen: dict[str, dict[str, Any]] = {}
    for items in (incentives or {}).values():  # one list for the section: the facts are about the market
        for i in items:
            seen.setdefault(i["key"], i)
    return {"type": "electric", "title": TITLE.get((lang or "en")[:2], TITLE["en"]), "rows": ROWS, "cars": rows,
            "not_electric": others, "notes": notes,
            **({"incentives": list(seen.values())} if seen else {})}  # fmt: skip
