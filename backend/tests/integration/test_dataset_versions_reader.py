"""Chat 6e001ee0: the engine identity reader `acquisition.api.dataset_versions` — stored gold first, then the cached
dataset rows, then one bounded live query (cached); never raises."""

from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace
from typing import Any

from sqlalchemy import delete

from automind.acquisition import api
from automind.acquisition.gold import repo
from automind.acquisition.gold import versions as gv
from automind.acquisition.gold.domain.match import DatasetRow, GoldValue
from automind.chat.application.services.identification import resolve
from automind.shared.infrastructure import db
from automind.shared.infrastructure.config.loader import reference


def _row(model: str, fuel: str, kw: float, cc: int, year: int, regs: int = 50, make: str = "KIA") -> DatasetRow:
    return DatasetRow(dataset="eea_co2", make=make, model=model, fuel=fuel, power_kw=kw, displacement_cc=cc,
                      mass_running_order_kg=None, year_from=year, year_to=year, registrations=regs, values={},
                      units={}, record_key=f"{make}|{model}|{fuel}|{kw}|{cc}|{year}")  # fmt: skip


def _ports(live: Any = None, timeout: float = 5.0) -> SimpleNamespace:
    intake = {"dataset_versions_timeout_s": timeout, "dataset_versions_min_registrations": 10}
    return SimpleNamespace(ref=SimpleNamespace(search={"intake": intake}), datasets=live)


async def _forget_cache(make: str) -> None:
    async with db.sessionmaker()() as s:
        await s.execute(delete(db.SearchCache).where(db.SearchCache.key == gv._key(make)))
        await s.commit()


async def test_stored_gold_keys_are_read_offline_without_a_live_query() -> None:
    await db.init_db()
    make = f"Goldkia{uuid.uuid4().hex[:6]}"
    ident = resolve.VariantIdentity(make=make, model="Sorento", generation="MQ4", variant_name="1.6 T-GDi PHEV",
                                    powertrain="PHEV", body_class="SUV", generation_years_from=2020,
                                    generation_years_to=None, engine_cc=1598, power_kw=195, fuel="phev",
                                    certainty="exact")  # fmt: skip
    v = await resolve.upsert_variant(ident, reference({}))
    await repo.upsert_dataset(repo.DatasetInfo("eea_co2_2024", "EEA CO2", "eea_co2", "CC-BY-4.0"))
    up = make.upper()
    keys = f"{up}|SORENTO|phev|132|1598|2021 ; {up}|SORENTO|phev|132|1598|2023 ; {up}|SORENTO|phev|118|1598|2024"
    await repo.replace("eea_co2_2024", v.id, [GoldValue(variant_id=v.id, attribute="co2_wltp", value_num=38,
                                                        unit="g/km", tolerance=0.05, tolerance_kind="rel",
                                                        origin="dataset", match_rule="by_power", confidence="MEDIUM",
                                                        dataset_id="eea_co2_2024", record_key=keys)])  # fmt: skip

    async def live(m: str) -> list[DatasetRow]:
        raise AssertionError("stored gold answers offline")

    got = await api.dataset_versions(make, "Sorento", "MQ4", "phev", 2020, ports=_ports(live))
    assert [(x.engine_kw, x.years_from, x.years_to) for x in got] == [(118, 2024, None), (132, 2021, 2023)]
    assert got[0].source_url and got[0].datasets == ["eea_co2"] and not got[0].power_is_max


async def test_live_query_once_then_the_cache_and_a_timeout_is_an_empty_list() -> None:
    await db.init_db()
    make = f"Livekia{uuid.uuid4().hex[:6]}"
    up = make.upper()
    calls: list[str] = []

    async def live(m: str) -> list[DatasetRow]:
        calls.append(m)
        return [_row("SORENTO", "phev", 132, 1598, 2022, make=up), _row("SORENTO", "phev", 118, 1598, 2024, make=up),
                _row("SORENTO", "phev", 99, 1598, 2024, regs=2, make=up),  # two imported cars: noise
                _row("SPORTAGE", "phev", 132, 1598, 2024, make=up)]  # fmt: skip

    await _forget_cache(make)
    first = await api.dataset_versions(make, "Sorento", None, "phev", 2020, ports=_ports(live))
    again = await api.dataset_versions(make, "Sorento", None, "phev", 2020, ports=_ports(live))
    assert calls == [make] and first == again
    assert [(x.engine_kw, x.years_from, x.years_to) for x in first] == [(118, 2024, None), (132, 2022, 2022)]

    slow_make = f"Slowkia{uuid.uuid4().hex[:6]}"

    async def slow(m: str) -> list[DatasetRow]:
        calls.append(m)
        await asyncio.sleep(1)
        return []

    await _forget_cache(slow_make)
    assert await api.dataset_versions(slow_make, "Sorento", ports=_ports(slow, timeout=0.05)) == []
    assert await api.dataset_versions(slow_make, "Sorento", ports=_ports(slow, timeout=0.05)) == []
    assert calls == [make, slow_make]  # a timed-out dataset is not waited for again (an empty answer is cached)
    assert await api.dataset_versions(f"Nolive{uuid.uuid4().hex[:6]}", "Sorento", ports=_ports(None)) == []
