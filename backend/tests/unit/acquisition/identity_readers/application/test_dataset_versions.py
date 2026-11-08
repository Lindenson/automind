"""Spec 012 A4b: the registered-versions reader over fake ports — stored gold answers offline, then the cache, then
one live query cached for the refresh period; a failed query is cached as empty for a day; a store down is an empty
list, never an error."""

from __future__ import annotations

import asyncio

from automind.acquisition.gold.domain.config import MatchCfg
from automind.acquisition.gold.domain.records import DatasetRow
from automind.acquisition.identity_readers.application.dataset_versions import DatasetVersions
from automind.acquisition.identity_readers.application.ports import IdentityStoreUnavailable, LiveRows
from automind.acquisition.identity_readers.domain.registered import IdRow, VersionLimits

LIMITS = VersionLimits(timeout_s=0.05, min_registrations=10)


class Book:
    def __init__(self, stored: list[IdRow] | None = None, cached: list[IdRow] | None = None,
                 down: bool = False) -> None:  # fmt: skip
        self._stored = stored or []
        self._cached = cached
        self.down = down
        self.kept: list[tuple[str, int, float]] = []

    async def stored(self, make: str, model: str) -> list[IdRow]:
        if self.down:
            raise IdentityStoreUnavailable("stored: OperationalError")
        return self._stored

    async def cached(self, make: str) -> list[IdRow] | None:
        return self._cached

    async def cache(self, make: str, rows: list[IdRow], days: float) -> None:
        self.kept.append((make, len(rows), days))


def _row(kw: float, year: int, regs: int = 50, model: str = "SORENTO") -> DatasetRow:
    return DatasetRow(dataset="eea_co2", make="KIA", model=model, fuel="phev", power_kw=kw, displacement_cc=1598,
                      mass_running_order_kg=None, year_from=year, year_to=year, registrations=regs, values={},
                      units={}, record_key=f"KIA|{model}|{kw}|{year}")  # fmt: skip


def _id(kw: float, year: int) -> IdRow:
    return IdRow("eea_co2", "KIA", "SORENTO", "phev", kw, 1598, year, year)


def _reader(book: Book, live: LiveRows | None = None) -> DatasetVersions:
    return DatasetVersions(book, live, LIMITS, MatchCfg(), refresh_days=30)


async def test_stored_gold_answers_without_the_live_query() -> None:
    async def live(make: str) -> list[DatasetRow]:
        raise AssertionError("stored gold answers offline")

    got = await _reader(Book(stored=[_id(132, 2021), _id(118, 2024)]), live).run("Kia", "Sorento", "phev")
    assert [(v.engine_kw, v.years_from, v.years_to) for v in got] == [(118, 2024, None), (132, 2021, 2021)]


async def test_one_live_query_is_cached_for_the_refresh_period_and_noise_dropped() -> None:
    calls: list[str] = []

    async def live(make: str) -> list[DatasetRow]:
        calls.append(make)
        return [_row(132, 2022), _row(118, 2024), _row(99, 2024, regs=2), _row(132, 2024, model="SPORTAGE")]

    book = Book()
    got = await _reader(book, live).run("Kia", "Sorento", "phev", 2020)
    assert calls == ["Kia"] and book.kept == [("Kia", 4, 30)]
    assert [(v.engine_kw, v.years_from) for v in got] == [(118, 2024), (132, 2022)]
    assert await _reader(Book(cached=[_id(118, 2024)]), live).run("Kia", "Sorento") != []
    assert calls == ["Kia"]  # the cache answered


async def test_a_slow_query_is_cached_empty_for_a_day_and_a_store_down_is_an_empty_list() -> None:
    async def slow(make: str) -> list[DatasetRow]:
        await asyncio.sleep(1)
        return []

    book = Book()
    assert await _reader(book, slow).run("Kia", "Sorento") == []
    assert book.kept == [("Kia", 0, 1.0)]
    assert await _reader(Book(down=True), slow).run("Kia", "Sorento") == []
    assert await _reader(Book(), None).run("Kia", "Sorento") == []  # no live port: stored and cached only
