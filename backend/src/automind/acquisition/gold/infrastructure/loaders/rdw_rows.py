"""RDW register groups → `DatasetRow`s (the second half of `rdw.py`): the sample vehicle's fuel rows give the
group's fuel, power and WLTP values; NEDC figures go to the details only."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from automind.acquisition.gold.domain.records import DatasetRow
from automind.acquisition.gold.infrastructure.loaders import num, pos, year_of

_FUEL = {"benzine": "petrol", "diesel": "diesel", "lpg": "lpg", "cng": "cng", "alcohol": "e85", "waterstof": "fcev"}
_ICE = frozenset(_FUEL.values()) - {"fcev"}


def to_row(cfg: Mapping[str, Any], g: Mapping[str, Any], fuel_rows: Sequence[Mapping[str, Any]]) -> DatasetRow | None:
    c, f = cfg["columns"], cfg["fuel_columns"]
    make, model = str(g.get(c["make"]) or "").strip(), " ".join(str(g.get(c["model"]) or "").split())
    if not fuel_rows or not make or not model:
        return None
    fuel, m = _fuel_of(fuel_rows, f), _merged(fuel_rows)
    raw = {
        **_fuel_values(fuel, m, f),
        "displacement": pos(g.get(c["displacement_cc"])),
        "curb_mass": pos(g.get(c["mass_kg"])),
        "list_price_nl": pos(g.get("price")),
    }
    values = {k: round(v, 2) for k, v in raw.items() if v is not None}
    cc, kw = pos(g.get(c["displacement_cc"])), pos(m.get(f["electric_kw" if fuel == "bev" else "power_kw"]))
    ident = [str(g.get(c[k]) or "-") for k in ("type_approval", "variant", "version", "mass_kg")]
    return DatasetRow(
        dataset="rdw",
        make=make,
        model=model,
        fuel=fuel,
        power_kw=kw,
        displacement_cc=int(cc) if cc else None,
        mass_running_order_kg=pos(g.get(c["mass_kg"])),
        year_from=year_of(g.get("first_reg")),
        year_to=year_of(g.get("last_reg")),
        registrations=int(num(g.get("n")) or 0),
        values=values,
        units={k: str(cfg["units"][k]) for k in values},
        record_key="|".join([make, model, *ident]),
        conversions={a: r for a, r in (cfg.get("conversions") or {}).items() if a in values},
        details=_details(fuel, g, m, c, f),
    )


def _fuel_of(rows: Sequence[Mapping[str, Any]], f: Mapping[str, str]) -> str:
    kinds = {str(r.get(f["fuel"]) or "").strip().lower() for r in rows}
    hybrid = {str(r.get(f["hybrid_class"]) or "").upper() for r in rows}
    if "OVC-HEV" in hybrid:
        return "phev"
    if "NOVC-HEV" in hybrid or ("elektriciteit" in kinds and len(kinds) > 1):
        return "hybrid"
    if kinds == {"elektriciteit"}:
        return "bev"
    return next((_FUEL[k] for k in sorted(kinds) if k in _FUEL), "other")


def _merged(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """The first non-empty value of each field over the vehicle's fuel rows (ordered by brandstof_volgnummer)."""
    out: dict[str, Any] = {}
    for r in rows:
        for k, v in r.items():
            out.setdefault(k, v)
    return out


def _fuel_values(fuel: str, m: Mapping[str, Any], f: Mapping[str, str]) -> dict[str, float | None]:
    plug, bev = fuel == "phev", fuel == "bev"
    return {
        "max_power": pos(m.get(f["power_kw"])) if fuel in _ICE else pos(m.get(f["electric_kw"])) if bev else None,
        "co2_wltp": None if bev else pos(m.get(f["co2_wltp_weighted" if plug else "co2_wltp"])),
        "consumption_wltp": None if bev else pos(m.get(f["consumption_wltp_weighted" if plug else "consumption_wltp"])),
        "energy_wh_km": pos(m.get(f["energy_bev"])) if bev else pos(m.get(f["energy_phev"])) if plug else None,
        "range_wltp_km": pos(m.get(f["range_bev"])) if bev else pos(m.get(f["range_phev"])) if plug else None,
    }


def _details(
    fuel: str, g: Mapping[str, Any], m: Mapping[str, Any], c: Mapping[str, str], f: Mapping[str, str]
) -> dict[str, Any]:
    return {
        "vehicle_kind": g.get(c["kind"]),
        "type_approval": g.get(c["type_approval"]),
        "variant": g.get(c["variant"]),
        "version": g.get(c["version"]),
        "hybrid_class": m.get(f["hybrid_class"]),
        "engine_kw": pos(m.get(f["power_kw"])),
        "electric_kw": pos(m.get(f["electric_kw"])),
        "basis": "weighted" if fuel == "phev" else "combined",
        "nedc_consumption": pos(m.get("brandstofverbruik_gecombineerd")),
        "nedc_co2": pos(m.get("co2_uitstoot_gecombineerd")),
    }
