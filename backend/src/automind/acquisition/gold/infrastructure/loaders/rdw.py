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
from collections.abc import Iterable, Mapping
from typing import Any

import httpx

from automind.acquisition.gold.domain.records import DatasetRow
from automind.acquisition.gold.infrastructure.loaders import (
    USER_AGENT,
    SchemaChanged,
    quote,
    require,
    wanted_makes,
)
from automind.acquisition.gold.infrastructure.loaders.rdw_rows import to_row

_GROUP = ("make", "model", "kind", "type_approval", "variant", "version", "displacement_cc", "mass_kg")


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


async def _get(client: httpx.AsyncClient, url: str, params: Mapping[str, str]) -> list[dict[str, Any]]:
    r = await client.get(url, params=params)
    if r.status_code == 400 and "column" in r.text.lower():
        raise SchemaChanged(f"rdw: {r.text[:300]} (config/gold_datasets.yaml pins the columns)")
    r.raise_for_status()
    return list(r.json())


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
