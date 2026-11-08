"""Spec 012 A4b: gold's services over fake ports — a load replaces each variant's gold (a dry run writes nothing, an
unknown source and a store down fail loudly), and a settled challenge becomes gold (others do not)."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime, timedelta

import pytest

from automind.acquisition.gold.application.challenges import ChallengeGold
from automind.acquisition.gold.application.load import DatasetGold, GoldLoad, ReferenceGold
from automind.acquisition.gold.application.ports import GoldStoreUnavailable
from automind.acquisition.gold.domain.config import GoldRules, MatchCfg
from automind.acquisition.gold.domain.records import (
    CandidateVariant,
    DatasetInfo,
    DatasetRow,
    GoldValue,
    StoredGold,
)
from automind.shared.contracts.json import JsonObject

RULES = GoldRules(
    tolerances={"co2_wltp": ("rel", 0.05), "curb_mass": ("abs", 30.0)}, units={"co2_wltp": "g/km", "curb_mass": "kg"}
)
INFO = DatasetInfo("eea_co2_2024", "EEA CO2", "eea_co2", "CC-BY-4.0", next_refresh_at=datetime(2026, 12, 1, tzinfo=UTC))


class Book:
    def __init__(self, down: bool = False) -> None:
        self.down = down
        self.loads: list[tuple[str, int, int]] = []
        self.replaced: dict[tuple[str, str], list[GoldValue]] = {}
        self.put_values: list[GoldValue] = []

    async def record_load(self, info: DatasetInfo, rows_read: int = 0, rows_matched: int = 0) -> None:
        if self.down:
            raise GoldStoreUnavailable("record_load: OperationalError")
        self.loads.append((info.id, rows_read, rows_matched))

    async def replace(self, dataset_id: str, variant_id: str, gold: Iterable[GoldValue]) -> int:
        self.replaced[(dataset_id, variant_id)] = list(gold)
        return len(self.replaced[(dataset_id, variant_id)])

    async def put(self, gold: GoldValue) -> None:
        self.put_values.append(gold)

    async def stored(self, variant_id: str, include_flagged: bool = False) -> list[StoredGold]:
        return []

    async def best(self, variant_id: str) -> dict[str, StoredGold]:
        return {}


class Reader:
    def __init__(self, rows: list[DatasetRow]) -> None:
        self._rows = rows
        self.asked: list[list[str]] = []

    def info(self) -> DatasetInfo:
        return INFO

    async def rows(self, makes: list[str]) -> list[DatasetRow]:
        self.asked.append(makes)
        return self._rows


class Reference:
    def info(self) -> DatasetInfo:
        return DatasetInfo("reference_set", "Reference vehicles", "reference_set", "internal", refresh_days=1)

    def entries(self) -> list[JsonObject]:
        return [{"make": "Kia", "model": "Sorento", "generation": "MQ4", "variant_name": "1.6 T-GDi PHEV",
                 "specs": {"curb_mass": 2100, "not_an_attribute": 1}, "sources": ["x"]}]  # fmt: skip


def _variant(vid: str, make: str = "Kia", fuel: str = "phev") -> CandidateVariant:
    return CandidateVariant(id=vid, make=make, model="Sorento", generation="MQ4", variant_name="1.6 T-GDi PHEV",
                            fuel=fuel, powertrain="PHEV", power_kw=195.0, engine_cc=1598, years_from=2020,
                            years_to=None)  # fmt: skip


def _row(kw: float, co2: float) -> DatasetRow:
    return DatasetRow(dataset="eea_co2", make="KIA", model="SORENTO", fuel="phev", power_kw=kw, displacement_cc=1598,
                      mass_running_order_kg=None, year_from=2024, year_to=2024, registrations=50,
                      values={"co2_wltp": co2}, units={"co2_wltp": "g/km"}, record_key=f"KIA|SORENTO|{kw}")  # fmt: skip


def _load(book: Book, reader: Reader) -> GoldLoad:
    return GoldLoad(
        book, {"reference_set": ReferenceGold(Reference(), RULES), "eea_co2": DatasetGold(reader, MatchCfg())}
    )


async def test_a_dataset_load_records_itself_and_replaces_every_variants_gold() -> None:
    book, reader = Book(), Reader([_row(118, 38.0)])
    gold = await _load(book, reader).run("eea_co2", [_variant("v1"), _variant("v2", make="Toyota")])
    assert reader.asked == [["KIA", "TOYOTA"]]
    assert [(g.variant_id, g.attribute, g.value_num, g.match_rule) for g in gold] == [
        ("v1", "co2_wltp", 38.0, "by_power")
    ]
    assert book.loads == [("eea_co2_2024", 1, 1)]
    assert book.replaced[("eea_co2_2024", "v2")] == []  # a variant without gold loses the old load's values


async def test_the_reference_set_names_its_variants_and_a_dry_run_writes_nothing() -> None:
    book = Book()
    gold = await _load(book, Reader([])).run("reference_set", [_variant("v1")], dry_run=True)
    assert [(g.attribute, g.value_num, g.confidence, g.unit, g.tolerance) for g in gold] == [
        ("curb_mass", 2100.0, "HIGH", "kg", 30.0)
    ]
    assert book.loads == [] and book.replaced == {}


async def test_an_unknown_source_and_a_store_down_fail_loudly() -> None:
    with pytest.raises(ValueError, match="unknown dataset"):
        await _load(Book(), Reader([])).run("nowhere", [])
    book = Book(down=True)
    with pytest.raises(GoldStoreUnavailable):
        await _load(book, Reader([_row(118, 38.0)])).run("eea_co2", [_variant("v1")])
    assert book.replaced == {}  # nothing replaced when the load could not be recorded


async def test_a_settled_challenge_becomes_medium_gold_and_others_do_not() -> None:
    book = Book()
    challenges = ChallengeGold(book, RULES)
    assert await challenges.record("v1", "co2_wltp", "CORRECTED", "41,5", "c1")
    assert not await challenges.record("v1", "co2_wltp", "REJECTED", "41", "c2")
    assert not await challenges.record("v1", "co2_wltp", "CONFIRMED", " ", "c3")
    (g,) = book.put_values
    assert (g.value_num, g.unit, g.origin, g.match_rule, g.confidence, g.record_key) == (
        41.5, "g/km", "challenge", "challenge_corrected", "MEDIUM", "c1")  # fmt: skip
    assert book.loads == [("challenges", 0, 0)]


async def test_a_challenge_is_not_written_when_the_store_is_down() -> None:
    book = Book(down=True)
    with pytest.raises(GoldStoreUnavailable):
        await ChallengeGold(book, RULES).record("v1", "co2_wltp", "CONFIRMED", 40, "c1")
    assert book.put_values == []


def test_best_gold_prefers_high_then_the_reference_set_then_the_newest() -> None:
    from automind.acquisition.gold.domain.choice import best_by_attribute

    t = datetime(2026, 11, 1, tzinfo=UTC)

    def g(gid: str, origin: str, confidence: str, age: int) -> StoredGold:
        return StoredGold(gid, "v1", "co2_wltp", 1.0, None, "g/km", 0.05, "rel", origin, "r", confidence, None,
                          t - timedelta(days=age))  # fmt: skip

    best = best_by_attribute([g("a", "challenge", "MEDIUM", 0), g("b", "dataset", "HIGH", 3),
                              g("c", "reference_set", "HIGH", 9), g("d", "reference_set", "HIGH", 1)])  # fmt: skip
    assert best["co2_wltp"].id == "d"
