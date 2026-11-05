"""T026: RDW Open Data (Netherlands vehicle register, CC0) through the Socrata SODA API.

Two grouped steps instead of 16 M rows: (1) `m9d7-ebf2` (vehicles) grouped per make / commercial name / vehicle kind /
type approval / variant / version / displacement / running-order mass with the count, first and last registration,
mean list price and one sample registration number; (2) `8ys7-d773` (fuel; it has no make column, so no server-side
join) for the sample numbers, `kenteken in (…)` in batches. The sample vehicle's fuel rows give the group's power and
WLTP values. Registration numbers are used only for that join and are not kept.

Pitfalls seen in the live data (2026-11-05): the fuel rows give the combustion engine (`nettomaximumvermogen`) and the
electric motor (`netto_max_vermogen_elektrisch`) separately — no system power for hybrids (Sorento PHEV 132.2 + 66.9
kW); older approvals carry only NEDC figures (`brandstofverbruik_gecombineerd`, kept in details, never WLTP); many
Land Cruisers are registered as vans (`Bedrijfsauto`, "TOYOTA LAND CRUISER VAN"); the RDW `variant` names the chassis
(GDJ150 = J150, GDJ250 = J250), which tells generations apart where the commercial name does not; the SODA JSON omits
null fields.
"""

from __future__ import annotations

import os
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

import httpx

from automind.acquisition.gold.domain.match import DatasetRow
from automind.acquisition.gold.loaders import (
    USER_AGENT,
    SchemaChanged,
    num,
    pos,
    quote,
    require,
    wanted_makes,
    year_of,
)

_GROUP = ("make", "model", "kind", "type_approval", "variant", "version", "displacement_cc", "mass_kg")
_FUEL = {"benzine": "petrol", "diesel": "diesel", "lpg": "lpg", "cng": "cng", "alcohol": "e85", "waterstof": "fcev"}
_ICE = frozenset(_FUEL.values()) - {"fcev"}


def vehicles_params(cfg: Mapping[str, Any], makes: list[str] | None, offset: int) -> dict[str, str]:
    c = cfg["columns"]
    group = ",".join(c[k] for k in _GROUP)
    where = [f"{c['first_registration']} >= {quote(str(cfg['first_registration_from']))}"]
    if makes:
        where.append(f"{c['make']} in({','.join(quote(m) for m in makes)})")
    if cfg.get("vehicle_kinds"):
        where.append(f"{c['kind']} in({','.join(quote(str(k)) for k in cfg['vehicle_kinds'])})")
    return {
        "$select": f"{group},count(*) as n,min({c['plate']}) as sample,min({c['first_registration']}) as first_reg,"
        f"max({c['first_registration']}) as last_reg,avg({c['list_price']}) as price",
        "$where": " AND ".join(where),
        "$group": group,
        "$having": f"count(*) >= {int(cfg.get('min_vehicles', 2))}",
        "$order": group,
        "$limit": str(int(cfg.get("page_size", 50000))),
        "$offset": str(offset),
    }


def fuel_params(cfg: Mapping[str, Any], plates: list[str]) -> dict[str, str]:
    f = cfg["fuel_columns"]
    return {
        "$select": ",".join(dict.fromkeys(f.values())),
        "$where": f"{f['plate']} in({','.join(quote(p) for p in plates)})",
        "$order": f"{f['plate']},{f['seq']}",
        "$limit": str(len(plates) * 4),
    }


async def _get(client: httpx.AsyncClient, url: str, params: Mapping[str, str]) -> list[dict[str, Any]]:
    r = await client.get(url, params=params)
    if r.status_code == 400 and "column" in r.text.lower():
        raise SchemaChanged(f"rdw: {r.text[:300]} (config/gold_datasets.yaml pins the columns)")
    r.raise_for_status()
    return list(r.json())


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


async def _groups(client: httpx.AsyncClient, cfg: Mapping[str, Any], makes: list[str] | None) -> list[dict[str, Any]]:
    url, page = f"{cfg['url']}{cfg['vehicles']}.json", int(cfg.get("page_size", 50000))
    out: list[dict[str, Any]] = []
    while True:
        batch = await _get(client, url, vehicles_params(cfg, makes, len(out)))
        out += batch
        if len(batch) < page:
            break
    if out:
        require({k for g in out for k in g}, {"make": cfg["columns"]["make"], "n": "n", "sample": "sample"}, "rdw")
    return out


async def _fuel(
    client: httpx.AsyncClient, cfg: Mapping[str, Any], plates: list[str]
) -> dict[str, list[dict[str, Any]]]:
    url, step, plate = f"{cfg['url']}{cfg['fuel']}.json", int(cfg.get("plates_per_query", 50)), cfg["fuel_columns"]
    by_plate: dict[str, list[dict[str, Any]]] = {}
    for i in range(0, len(plates), step):
        for r in await _get(client, url, fuel_params(cfg, plates[i : i + step])):
            by_plate.setdefault(str(r.get(plate["plate"])), []).append(r)
    return by_plate


def _headers(cfg: Mapping[str, Any]) -> dict[str, str]:
    token = os.environ.get(str(cfg.get("app_token_env") or "RDW_APP_TOKEN"), "")
    return {"User-Agent": USER_AGENT, **({"X-App-Token": token} if token else {})}


async def fetch_rows(
    cfg: Mapping[str, Any],
    make: str | None = None,
    *,
    makes: Iterable[str] | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> list[DatasetRow]:
    """Grouped register rows of `make`/`makes` (None = every make: ~100k groups, avoid) with their fuel data."""
    asked = wanted_makes(make, makes)
    async with httpx.AsyncClient(
        timeout=float(cfg.get("timeout_s", 120)), transport=transport, headers=_headers(cfg)
    ) as client:
        groups = await _groups(client, cfg, asked)
        fuel = await _fuel(client, cfg, sorted({str(g["sample"]) for g in groups if g.get("sample")}))
    return [r for g in groups if (r := to_row(cfg, g, fuel.get(str(g.get("sample")), []))) is not None]


def version(cfg: Mapping[str, Any]) -> str:
    """RDW is a live register: one dataset row `rdw`, versioned by load date in gold_datasets.loaded_at."""
    return ""
