"""Spec 011 T035: the gold loaders on trimmed live samples (tests/fixtures/gold), HTTP served by httpx.MockTransport.

No test here may reach the network: an autouse guard makes every socket connect fail.
"""

from __future__ import annotations

import csv
import json
import re
import socket
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

import httpx
import pytest

from automind.acquisition.gold.domain.match import DatasetRow
from automind.acquisition.gold.loaders import (
    SchemaChanged,
    eea_co2,
    eea_obfcm,
    meta,
    rdw,
    wanted_makes,
    weighted_median,
)
from automind.infrastructure.config import load_yaml

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "gold"


@pytest.fixture(autouse=True)
def _offline(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*_a: Any, **_k: Any) -> None:
        raise AssertionError("network access in a gold loader test")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


def _cfg(name: str) -> dict[str, Any]:
    return dict(load_yaml("gold_datasets.yaml")["datasets"][name])


def _makes_in(text: str) -> set[str]:
    m = re.search(r"(?:IN|in)\s*\(([^)]*)\)", text)
    return {x.strip().strip("'") for x in m.group(1).split(",")} if m else set()


# --- EEA CO2 (Discodata) ------------------------------------------------------------------------------------------


def _discodata(seen: list[str], mutate: Any = None) -> httpx.MockTransport:
    data = json.loads((FIX / "eea_co2_sample.json").read_text(encoding="utf-8"))

    def handler(req: httpx.Request) -> httpx.Response:
        assert req.method == "POST" and req.url.host == "discodata.eea.europa.eu"
        sql = parse_qs(req.content.decode())["query"][0]
        seen.append(sql)
        table = re.search(r"\.\[(co2cars_\w+)\]", sql).group(1)  # type: ignore[union-attr]
        makes = _makes_in(sql)
        rows = [r for r in data.get(table, {"results": []})["results"] if not makes or r["mk"] in makes]
        return httpx.Response(200, json=mutate(rows) if mutate else {"results": rows})

    return httpx.MockTransport(handler)


async def test_eea_co2_rows_from_the_grouped_query() -> None:
    seen: list[str] = []
    rows = await eea_co2.fetch_rows(_cfg("eea_co2"), "Kia", transport=_discodata(seen))
    assert len(seen) == 4  # one query per configured yearly final table
    assert all("[Mk] IN ('KIA')" in q and "SUM([R]) AS reg" in q and "GROUP BY" in q for q in seen)
    assert rows and {r.make for r in rows} == {"KIA"} and {r.model for r in rows} == {"SORENTO"}
    assert all(isinstance(r, DatasetRow) and r.dataset == "eea_co2" for r in rows)

    # Sorento MQ4 PHEV, 2024: the 118 kW is the 1.6 T-GDi engine (system 195 kW) → a key, not a max_power value
    phev = [r for r in rows if r.fuel == "phev" and r.power_kw == 118 and r.mass_running_order_kg == 2105]
    assert len(phev) == 1 and phev[0].registrations == 2058 and phev[0].year_from == phev[0].year_to == 2024
    assert phev[0].values == {"displacement": 1598, "curb_mass": 2105, "co2_wltp": 37, "consumption_wltp": 1.6,
                              "energy_wh_km": 182}  # fmt: skip
    assert phev[0].units["energy_wh_km"] == "Wh/km" and phev[0].conversions == {
        "curb_mass": "eu_running_order_minus_driver"
    }
    assert phev[0].details["basis"] == "weighted" and phev[0].details["reported_power_kw"] == 118
    assert phev[0].record_key == "KIA|SORENTO|phev|118|1598|2024"

    # mode H = hybrid (HEV or MHEV), diesel keeps its power as a gold value
    assert {r.fuel for r in rows} == {"phev", "hybrid", "diesel"}
    diesel = [r for r in rows if r.fuel == "diesel"]
    assert {r.values["max_power"] for r in diesel} >= {142.0} and all(r.displacement_cc == 2151 for r in diesel)
    assert weighted_median((r.values["curb_mass"], r.registrations) for r in diesel if r.power_kw == 142) == 1897


async def test_eea_co2_land_cruiser_150_names() -> None:
    rows = await eea_co2.fetch_rows(_cfg("eea_co2"), makes=["TOYOTA"], years=[2023], transport=_discodata([]))
    names = {r.model for r in rows}
    # the European name of the Prado J150 and its spelling variants; "LAND CRUISER" alone is also the J300
    assert {"TOYOTA LAND CRUISER (150 SERIES)", "LAND CRUISER (150 SERIES)", "LAND CRUISER"} <= names
    j150 = [r for r in rows if r.model == "TOYOTA LAND CRUISER (150 SERIES)" and r.power_kw == 150]
    assert sum(r.registrations for r in j150) > 5000 and all(
        r.fuel == "diesel" and r.displacement_cc == 2755 for r in j150
    )
    assert weighted_median((r.values["co2_wltp"], r.registrations) for r in j150) == 251


async def test_eea_co2_schema_change_fails_loudly() -> None:
    def drop_fc(rows: list[dict[str, Any]]) -> dict[str, Any]:
        return {"results": [{k: v for k, v in r.items() if k != "fc"} for r in rows]}

    with pytest.raises(SchemaChanged):
        await eea_co2.fetch_rows(_cfg("eea_co2"), "KIA", years=[2024], transport=_discodata([], drop_fc))

    def invalid(_rows: list[dict[str, Any]]) -> dict[str, Any]:
        return {"errors": [{"error": "Invalid column name 'Fc'.", "errorcode": 10003}]}

    with pytest.raises(SchemaChanged):
        await eea_co2.fetch_rows(_cfg("eea_co2"), "KIA", years=[2024], transport=_discodata([], invalid))


def test_make_names_are_checked_before_they_reach_sql() -> None:
    with pytest.raises(ValueError):
        wanted_makes("KIA; DROP TABLE x", None)
    assert wanted_makes(" kia", ["Toyota", "KIA"]) == ["KIA", "TOYOTA"] and wanted_makes(None, None) is None
    assert "IN ('LAND ROVER', 'O''REILLY')" in eea_co2.build_query(_cfg("eea_co2"), "t", ["LAND ROVER", "O'REILLY"])


# --- EEA OBFCM (raw CSV on the EEA datashare) ---------------------------------------------------------------------


def _datashare() -> httpx.MockTransport:
    body = (FIX / "eea_obfcm_sample.csv").read_bytes()

    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.host == "sdi.eea.europa.eu" and req.url.path.endswith("/2024_Cars_Raw.csv")
        assert req.headers["authorization"].startswith("Basic ")  # share token as WebDAV user
        return httpx.Response(200, content=body, headers={"content-type": "text/csv"})

    return httpx.MockTransport(handler)


def _expected_obfcm(make: str, model: str, fuel_type: str, kw: str, year: str) -> tuple[int, float, float]:
    with (FIX / "eea_obfcm_sample.csv").open(encoding="utf-8-sig", newline="") as f:
        rows = [
            r
            for r in csv.DictReader(f)
            if (r["Mk"], r["Cn"], r["Ft"], r["Ep (KW)"], r["Year"], r["Used in calculation"])
            == (make, model, fuel_type, kw, year, "1")
        ]
    fuel = sum(float(r["Total fuel consumed (lifetime) (l)"]) for r in rows)
    km = sum(float(r["Total distance travelled (lifetime) (km)"]) for r in rows)
    grids = [r["Total grid energy into the battery (lifetime) (kWh)"] for r in rows]
    grid = sum(float(g) for g in grids if g not in ("", "NULL"))
    return len(rows), round(100 * fuel / km, 2), round(100 * grid / km, 2)


async def test_eea_obfcm_real_consumption_per_model() -> None:
    rows = await eea_obfcm.fetch_rows(_cfg("eea_obfcm"), makes=["kia", "Toyota"], transport=_datashare())
    assert rows and {r.make for r in rows} <= {"KIA", "TOYOTA"} and all(r.registrations >= 10 for r in rows)
    by = {(r.model, r.fuel, r.power_kw, r.year_from): r for r in rows}

    phev = by[("SORENTO", "phev", 132.0, 2022)]
    n, l100, kwh = _expected_obfcm("KIA", "SORENTO", "petrol/electric", "132", "2022")
    assert phev.registrations == n and phev.values == {"consumption_real": l100, "energy_real_kwh_100km": kwh}
    assert 5.0 < l100 < 8.0  # real world, against 1.6 l/100 km WLTP weighted
    assert phev.details["wltp_consumption"] == 1.6 and 0 < phev.details["cd_engine_off_share"] < 1
    assert phev.units == {"consumption_real": "l/100km", "energy_real_kwh_100km": "kWh/100km"}

    lc = by[("TOYOTA LAND CRUISER (150 SERIES)", "diesel", 150.0, 2022)]
    n, l100, _ = _expected_obfcm("TOYOTA", "TOYOTA LAND CRUISER (150 SERIES)", "diesel", "150", "2022")
    assert lc.registrations == n and lc.values == {"consumption_real": l100} and lc.displacement_cc == 2755
    assert not lc.conversions  # OBFCM mass is a tie-break only, no curb_mass value

    only_kia = await eea_obfcm.fetch_rows(_cfg("eea_obfcm"), "KIA", transport=_datashare())
    assert {r.make for r in only_kia} == {"KIA"}


async def test_eea_obfcm_schema_change_fails_loudly() -> None:
    def handler(_req: httpx.Request) -> httpx.Response:
        text = (FIX / "eea_obfcm_sample.csv").read_text(encoding="utf-8-sig")
        return httpx.Response(200, text=text.replace("Used in calculation", "Used"))

    with pytest.raises(SchemaChanged):
        await eea_obfcm.fetch_rows(_cfg("eea_obfcm"), "KIA", transport=httpx.MockTransport(handler))


# --- RDW (SODA) ---------------------------------------------------------------------------------------------------


def _soda(seen: list[httpx.Request]) -> httpx.MockTransport:
    data = json.loads((FIX / "rdw_sample.json").read_text(encoding="utf-8"))

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        assert req.url.host == "opendata.rdw.nl"
        where = req.url.params["$where"]
        if req.url.path.endswith("/m9d7-ebf2.json"):
            makes = _makes_in(where.split("merk", 1)[1])
            rows = [] if req.url.params["$offset"] != "0" else [r for r in data["m9d7-ebf2"] if r["merk"] in makes]
            return httpx.Response(200, json=rows)
        plates = _makes_in(where)
        return httpx.Response(200, json=[r for r in data["8ys7-d773"] if r["kenteken"] in plates])

    return httpx.MockTransport(handler)


async def test_rdw_groups_with_fuel_data(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RDW_APP_TOKEN", "test-token")
    seen: list[httpx.Request] = []
    cfg = _cfg("rdw") | {"plates_per_query": 20}
    rows = await rdw.fetch_rows(cfg, "kia", transport=_soda(seen))
    vehicle_q = [r for r in seen if r.url.path.endswith("/m9d7-ebf2.json")]
    assert vehicle_q and "merk in('KIA')" in vehicle_q[0].url.params["$where"]
    assert vehicle_q[0].url.params["$having"] == "count(*) >= 2" and seen[0].headers["x-app-token"] == "test-token"
    assert len(seen) - len(vehicle_q) >= 2  # sample plates asked in batches of 20

    assert rows and {r.model for r in rows} == {"SORENTO"} and all(r.dataset == "rdw" for r in rows)
    top = max(rows, key=lambda r: r.registrations)
    assert top.fuel == "phev" and top.registrations == 671 and top.power_kw == 132.2
    assert top.details["electric_kw"] == 66.9 and top.details["hybrid_class"] == "OVC-HEV"
    assert "max_power" not in top.values and top.values["curb_mass"] == 2057 and top.year_from == 2022
    assert top.conversions == {"curb_mass": "eu_running_order_minus_driver"} and top.values["list_price_nl"] > 50000
    facelift = [r for r in rows if r.fuel == "phev" and r.power_kw == 117.6 and "range_wltp_km" in r.values]
    assert facelift and facelift[0].values["energy_wh_km"] == 182 and facelift[0].values["range_wltp_km"] == 55
    hev = [r for r in rows if r.fuel == "hybrid" and "consumption_wltp" in r.values]
    assert hev and all(r.details["hybrid_class"] == "NOVC-HEV" for r in hev)
    assert not any(re.search(r"ZZ\d{4}", r.record_key + json.dumps(dict(r.details))) for r in rows)  # no plates kept


async def test_rdw_land_cruiser_generations_and_nedc() -> None:
    rows = await rdw.fetch_rows(_cfg("rdw"), "TOYOTA", transport=_soda([]))
    j150 = [r for r in rows if str(r.details["variant"]).startswith("GDJ15")]
    j250 = [r for r in rows if str(r.details["variant"]).startswith("GDJ25")]
    assert j150 and j250 and {r.details["vehicle_kind"] for r in j150} == {"Personenauto", "Bedrijfsauto"}
    assert {r.power_kw for r in j250} == {151.0} and all(r.values["max_power"] == 151 for r in j250)
    # 2018 approvals carry NEDC only: kept in details, never as WLTP gold
    nedc = [r for r in j150 if r.details["nedc_consumption"] and "consumption_wltp" not in r.values]
    assert nedc and all("co2_wltp" not in r.values and r.values["max_power"] in (130, 150) for r in nedc)


def test_dataset_meta_ids() -> None:
    assert meta(_cfg("eea_co2"), eea_co2.version(_cfg("eea_co2"))).id == "eea_co2_2024"
    assert meta(_cfg("eea_obfcm"), eea_obfcm.version(_cfg("eea_obfcm"))).id == "eea_obfcm_2024"
    m = meta(_cfg("rdw"), rdw.version(_cfg("rdw")))
    assert (m.id, m.licence, m.kind) == ("rdw", "CC0", "rdw")
    assert meta(_cfg("eea_co2"), "2024").licence == "CC-BY-4.0"


# --- loaders → match → gold_values (needs the US1 core: migration 0019, match.match, gold.repo) ---------------------


async def test_load_writes_gold() -> None:
    pytest.importorskip(
        "automind.acquisition.gold.repo",
        reason="needs T016 (migration 0019), T022 (match.match) and T023 (gold.repo) from the US1 core branch",
    )
    from automind.acquisition.gold.domain import match

    if not hasattr(match, "match"):
        pytest.skip("needs T022 match.match from the US1 core branch")
    pytest.skip("TODO at merge with the US1 core: seed variants, run load for the three fixtures, assert gold rows")
