"""T024: EEA CO2 monitoring of new passenger cars (Reg. (EU) 2019/631) through the Discodata SQL API.

One grouped query per yearly final table and make: a row per distinct (make, commercial name, fuel type, fuel mode,
kW, cm3, running-order mass, WLTP CO2, l/100 km, Wh/km) with the summed registrations — tens of KB per make and year
instead of the 1–3 GB yearly CSV. Rows of one make/name/fuel/kW group differ by trim (mass, CO2); the matcher takes
their registration-weighted median.

Pitfalls seen in the live data (2026-11-05): for HEV/PHEV `Ep (KW)` is the combustion engine's power, not the system
power (Kia Sorento MQ4 PHEV: 132 kW = 180 PS engine, system 195 kW = 265 PS; the 2024 facelift 118 kW); mode H is
both full and mild hybrid; commercial names are free text ("TOYOTA LAND CRUISER (150 SERIES)", "LANDCRUISER",
truncated "…(150 SERIE"); a BEV's `Ep (KW)` is often not its max power (Kia "NIRO EV 150KW" reported with
29 kW); the electric range is not in the Discodata tables.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

import httpx

from automind.acquisition.gold.domain.records import DatasetRow
from automind.acquisition.gold.infrastructure.loaders import (
    USER_AGENT,
    SchemaChanged,
    fuel_of,
    num,
    pos,
    quote,
    require,
    wanted_makes,
)

# query alias → pinned column key (aliases keep the JSON keys short and Discodata needs one on every column)
_ALIASES = {
    "mk": "make",
    "cn": "model",
    "ft": "fuel_type",
    "fm": "fuel_mode",
    "kw": "power_kw",
    "cc": "displacement_cc",
    "m": "mass_kg",
    "co2": "co2_wltp",
    "fc": "consumption_wltp",
    "z": "energy_wh_km",
    "yr": "year",
}


_ICE = frozenset({"petrol", "diesel", "lpg", "cng", "e85"})


def build_query(cfg: Mapping[str, Any], table: str, makes: list[str] | None) -> str:
    cols = cfg["columns"]
    keys = [_col(cols[k]) for k in _ALIASES.values()]
    select = ", ".join(f"{_col(cols[k])} AS {alias}" for alias, k in _ALIASES.items())
    where = f" WHERE {_col(cols['make'])} IN ({', '.join(quote(m) for m in makes)})" if makes else ""
    return (
        f"SELECT {select}, SUM({_col(cols['registrations'])}) AS reg "
        f"FROM {cfg['database']}.[{table}]{where} GROUP BY {', '.join(keys)}"
    )


def to_row(cfg: Mapping[str, Any], rec: Mapping[str, Any], year: int) -> DatasetRow | None:
    reg = int(num(rec.get("reg")) or 0)
    make, model = str(rec.get("mk") or "").strip(), " ".join(str(rec.get("cn") or "").split())
    if reg <= 0 or not make or not model:
        return None
    fuel = fuel_of(rec.get("ft"), rec.get("fm"))
    values = _values(fuel, rec)
    units = {k: str(cfg["units"][k]) for k in values}
    kw, cc = pos(rec.get("kw")), pos(rec.get("cc"))
    yr = int(num(rec.get("yr")) or year)
    return DatasetRow(
        dataset="eea_co2",
        make=make,
        model=model,
        fuel=fuel,
        power_kw=kw,
        displacement_cc=int(cc) if cc else None,
        mass_running_order_kg=pos(rec.get("m")),
        year_from=yr,
        year_to=yr,
        registrations=reg,
        values=values,
        units=units,
        record_key=f"{make}|{model}|{fuel}|{int(kw) if kw else '-'}|{int(cc) if cc else '-'}|{yr}",
        conversions={a: r for a, r in (cfg.get("conversions") or {}).items() if a in values},
        details={
            "fuel_type": rec.get("ft"),
            "fuel_mode": rec.get("fm"),
            "basis": "weighted" if fuel == "phev" else "combined",  # PHEV CO2 and l/100 km are WLTP weighted
            "reported_power_kw": kw if fuel not in _ICE else None,
        },
    )


async def fetch_rows(
    cfg: Mapping[str, Any],
    make: str | None = None,
    *,
    makes: Iterable[str] | None = None,
    years: Iterable[int] | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> list[DatasetRow]:
    """Grouped rows of every configured yearly table (or only `years`) for `make`/`makes` (None = all makes)."""
    asked = wanted_makes(make, makes)
    keep_years = set(years) if years is not None else None
    rows: list[DatasetRow] = []
    headers = {"User-Agent": USER_AGENT}
    timeout = float(cfg.get("timeout_s", 180))
    async with httpx.AsyncClient(timeout=timeout, transport=transport, headers=headers) as client:
        for t in cfg["tables"]:
            if keep_years is not None and int(t["year"]) not in keep_years:
                continue
            recs = await _query(client, str(cfg["url"]), build_query(cfg, str(t["name"]), asked))
            _check(recs, str(t["name"]))
            rows += [r for rec in recs if (r := to_row(cfg, rec, int(t["year"]))) is not None]
    return rows


def version(cfg: Mapping[str, Any]) -> str:
    """Dataset version for gold_datasets: the newest final year, e.g. "2024" → id eea_co2_2024."""
    return str(max(int(t["year"]) for t in cfg["tables"]))


def _col(name: str) -> str:
    return f"[{name}]"


async def _query(client: httpx.AsyncClient, url: str, sql: str) -> list[dict[str, Any]]:
    r = await client.post(url, data={"query": sql})
    r.raise_for_status()
    body = r.json()
    if errors := body.get("errors"):
        if any("column" in str(e.get("error", "")).lower() for e in errors):
            raise SchemaChanged(f"eea_co2: {errors} (config/gold_datasets.yaml pins the columns)")
        raise RuntimeError(f"discodata: {errors}")
    return list(body.get("results") or [])


def _values(fuel: str, rec: Mapping[str, Any]) -> dict[str, float]:
    vals = {
        # a hybrid's engine power is not the car's max power and a BEV's is often a continuous rating: for them
        # the reported kW is only a matching key, never a gold value
        "max_power": pos(rec.get("kw")) if fuel in _ICE else None,
        "displacement": pos(rec.get("cc")),
        "curb_mass": pos(rec.get("m")),
        "co2_wltp": num(rec.get("co2")),
        "consumption_wltp": pos(rec.get("fc")) if fuel != "bev" else None,
        "energy_wh_km": pos(rec.get("z")) if fuel in ("bev", "phev") else None,
    }
    return {k: v for k, v in vals.items() if v is not None}


def _check(recs: list[dict[str, Any]], table: str) -> None:
    if recs:
        require(recs[0], {**{a: a for a in _ALIASES}, "reg": "reg"}, f"eea_co2 {table}")
