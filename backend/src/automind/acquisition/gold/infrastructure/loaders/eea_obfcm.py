"""T025: EEA real-world fuel/energy consumption (OBFCM, Impl. Reg. (EU) 2021/392).

The EEA publishes, per collection year, a raw CSV with one row per vehicle (anonymised id, lifetime fuel, distance,
PHEV charge-depleting distances and grid energy, plus the vehicle's EEA CO2 fields Mk/Cn/Ft/Fm/Ep/Ec/M/Year) and an
aggregate per manufacturer × fuel only. Per-model gold needs the raw file (2.1 GB for cars 2024), so the loader
streams it once, keeps the rows of the asked makes that the EEA used in its calculation, and sums them per make /
commercial name / fuel / kW / cm3 / registration year:

- `consumption_real` (l/100 km) = 100 × Σ fuel / Σ distance — never mixed with WLTP (research R3);
- `energy_real_kwh_100km` (kWh/100 km, PHEV) = 100 × Σ grid energy / Σ distance;
- details: vehicles, distance, PHEV share of distance in charge-depleting mode (engine off / total), WLTP l/100 km.

Live sample 2026-11-05 (first 190 MB): Kia Sorento PHEV (132 kW, 2022 registrations, 131 cars) 6.3 l/100 km +
6.6 kWh/100 km real against 1.6 l/100 km WLTP weighted, 22 % of distance driven electrically; Sorento HEV 8.0;
Land Cruiser 150 2.8 D 10.2. BEVs carry no OBFCM data.
"""

from __future__ import annotations

import csv
from collections import Counter
from collections.abc import AsyncIterator, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

import httpx

from automind.acquisition.gold.domain.records import DatasetRow
from automind.acquisition.gold.infrastructure.loaders import (
    USER_AGENT,
    fuel_of,
    num,
    pos,
    require,
    wanted_makes,
    weighted_median,
)

_KEYS = ("make", "model", "fuel_type", "fuel_mode", "power_kw", "displacement_cc", "year")
_SUMS = ("fuel_l", "distance_km", "cd_engine_off_km", "cd_engine_on_km", "grid_kwh")


async def aggregate(
    lines: AsyncIterator[str], cols: Mapping[str, str], makes: list[str] | None
) -> dict[tuple[str, ...], _Group]:
    """Sum the used rows of the asked makes per group (pure apart from consuming `lines`)."""
    ix: dict[str, int] | None = None
    groups: dict[tuple[str, ...], _Group] = {}
    asked = set(makes) if makes else None
    async for line in lines:
        if not line.strip():
            continue
        row = next(csv.reader([line]))
        if ix is None:
            ix = _index(row, cols)
            continue
        if len(row) <= max(ix.values()) or row[ix["used"]].strip() != "1":
            continue
        if asked is not None and row[ix["make"]].strip().upper() not in asked:
            continue
        rec = {k: num(row[ix[k]]) for k in _SUMS}
        if not rec["distance_km"] or rec["distance_km"] <= 0:
            continue
        groups.setdefault(_key(row, ix), _Group()).add(rec, pos(row[ix["mass_kg"]]), pos(row[ix["consumption_wltp"]]))
    if ix is None:
        raise RuntimeError("eea_obfcm: empty file")
    return groups


def to_row(cfg: Mapping[str, Any], key: tuple[str, ...], g: _Group) -> DatasetRow | None:
    make, model, ft, fm, kw_s, cc_s, yr_s = key
    fuel = fuel_of(ft, fm)
    values = _values(fuel, g)
    if g.n < int(cfg.get("min_vehicles", 10)) or not values or not make or not model:
        return None
    kw, cc, yr = pos(kw_s), pos(cc_s), num(yr_s)
    year = int(yr) if yr else None
    return DatasetRow(
        dataset="eea_obfcm",
        make=make,
        model=model,
        fuel=fuel,
        power_kw=kw,
        displacement_cc=int(cc) if cc else None,
        mass_running_order_kg=weighted_median(g.mass.items()),
        year_from=year,
        year_to=year,
        registrations=g.n,
        values=values,
        units={k: str(cfg["units"][k]) for k in values},
        record_key=f"{make}|{model}|{fuel}|{int(kw) if kw else '-'}|{int(cc) if cc else '-'}|{year or '-'}",
        details=_details(fuel, g, fm, int(cfg.get("collection_year", 0))),
    )


async def fetch_rows(
    cfg: Mapping[str, Any],
    make: str | None = None,
    *,
    makes: Iterable[str] | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> list[DatasetRow]:
    """One streamed pass over the collection's raw CSV; pass every make needed in `makes` (the file is ~2 GB)."""
    groups = await aggregate(_lines(cfg, transport), cfg["columns"], wanted_makes(make, makes))
    return [r for key, g in sorted(groups.items()) if (r := to_row(cfg, key, g)) is not None]


def version(cfg: Mapping[str, Any]) -> str:
    """Dataset version: the collection year, e.g. "2024" → id eea_obfcm_2024."""
    return str(cfg["collection_year"])


@dataclass
class _Group:
    n: int = 0
    sums: dict[str, float] = field(default_factory=lambda: dict.fromkeys(_SUMS, 0.0))
    mass: Counter[float] = field(default_factory=Counter)
    wltp: Counter[float] = field(default_factory=Counter)

    def add(self, rec: Mapping[str, float | None], mass: float | None, wltp: float | None) -> None:
        self.n += 1
        for k in _SUMS:
            self.sums[k] += rec.get(k) or 0.0
        if mass:
            self.mass[mass] += 1
        if wltp:
            self.wltp[wltp] += 1


async def _lines(cfg: Mapping[str, Any], transport: httpx.AsyncBaseTransport | None) -> AsyncIterator[str]:
    timeout = httpx.Timeout(float(cfg.get("timeout_s", 1800)), connect=30.0)
    auth = (str(cfg["share_token"]), "") if cfg.get("share_token") else None
    async with (
        httpx.AsyncClient(timeout=timeout, transport=transport, headers={"User-Agent": USER_AGENT}) as client,
        client.stream("GET", str(cfg["url"]), auth=auth) as r,
    ):
        r.raise_for_status()
        async for line in r.aiter_lines():
            yield line


def _index(header: list[str], cols: Mapping[str, str]) -> dict[str, int]:
    header = [h.lstrip("﻿").strip() for h in header]
    require(header, cols, "eea_obfcm")
    return {k: header.index(v) for k, v in cols.items()}


def _key(row: list[str], ix: Mapping[str, int]) -> tuple[str, ...]:
    return tuple(" ".join(row[ix[k]].split()) for k in _KEYS)


def _values(fuel: str, g: _Group) -> dict[str, float]:
    km = g.sums["distance_km"]
    out: dict[str, float] = {}
    if fuel != "bev" and g.sums["fuel_l"] > 0:
        out["consumption_real"] = round(100 * g.sums["fuel_l"] / km, 2)
    if fuel == "phev" and g.sums["grid_kwh"] > 0:
        out["energy_real_kwh_100km"] = round(100 * g.sums["grid_kwh"] / km, 2)
    return out


def _details(fuel: str, g: _Group, mode: str, collection_year: int) -> dict[str, Any]:
    km = g.sums["distance_km"]
    d: dict[str, Any] = {
        "fuel_mode": mode,
        "vehicles": g.n,
        "distance_km": round(km),
        "collection_year": collection_year,
        "wltp_consumption": weighted_median(g.wltp.items()),
    }
    if fuel == "phev":
        d["cd_engine_off_share"] = round(g.sums["cd_engine_off_km"] / km, 3)
        d["cd_share"] = round((g.sums["cd_engine_off_km"] + g.sums["cd_engine_on_km"]) / km, 3)
    return d
