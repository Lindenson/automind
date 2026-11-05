"""Chat 6e001ee0: the registered versions of a model from the open datasets (acquisition.gold.domain.versions) and
their option labels (domain.ladder.registered_label)."""

from __future__ import annotations

from automind.acquisition.gold.domain.versions import IdRow, group, rows_of_keys
from automind.domain import ladder

# the EEA group keys stored with the Kia Sorento MQ4 PHEV gold values (live database, 2026-11-05)
SORENTO_KEYS = [
    "KIA|SORENTO/PHEV/5S/GOLD/UVO/1.6 T|phev|132|1598|2021 ; KIA|SORENTO/PHEV/7S/SILBER/UVO/1.6|phev|132|1598|2021 ; "
    "KIA|SORENTO|phev|118|1598|2024 ; KIA|SORENTO|phev|132|1598|2021 ; KIA|SORENTO|phev|132|1598|2022 ; "
    "KIA|SORENTO|phev|132|1598|2023",
    "KIA|SORENTO|-|-|-|2015 ; KIA|SORENTO|e4*2007/46*1530*01|F5H24|A63DSO|2015",  # RDW keys: not EEA groups
]


def _row(model: str, fuel: str, kw: float | None, cc: int | None, year: int, regs: int = 100,
         make: str = "KIA") -> IdRow:  # fmt: skip
    return IdRow("eea_co2", make, model, fuel, kw, cc, year, year, regs)


def test_stored_keys_give_the_pre_facelift_and_the_facelift_engine_newest_first() -> None:
    rows = rows_of_keys(SORENTO_KEYS)
    assert {r.year_from for r in rows} == {2021, 2022, 2023, 2024}  # the RDW keys are skipped
    found = group(rows, "Kia", "Sorento", fuel="phev", year_from=2020)
    assert [(v.engine_kw, v.displacement_cc, v.years_from, v.years_to) for v in found] == [
        (118, 1598, 2024, None),  # the facelift's engine, still registered
        (132, 1598, 2021, 2023),  # the first engine, not registered after 2023
    ]
    assert not any(v.power_is_max for v in found)  # a plug-in's kW is its combustion engine's, never its power


def test_groups_by_engine_over_years_and_names_and_filters_model_fuel_year_and_noise() -> None:
    rows = [
        _row("SORENTO", "diesel", 142, 2151, 2021),
        _row("SORENTO", "diesel", 142.4, 2151, 2024),
        _row("SORENTO/PHEV/7S", "phev", 132, 1598, 2022),
        _row("SORENTO", "hybrid", 132, 1598, 2023),
        _row("SPORTAGE", "diesel", 100, 1598, 2024),  # another model
        _row("SORENTO", "diesel", 147, 2199, 2019),  # before the generation
        _row("SORENTO", "petrol", 199, 2497, 2023, regs=3),  # three imported cars: noise
        _row("SORENTO", "diesel", 142, 2151, 2022, make="HYUNDAI"),  # another make
    ]
    found = group(rows, "Kia", "Sorento", year_from=2020, min_registrations=10)
    assert {(v.fuel, v.engine_kw, v.years_from, v.years_to) for v in found} == {
        ("diesel", 142, 2021, None), ("phev", 132, 2022, 2022), ("hybrid", 132, 2023, 2023),
    }  # fmt: skip
    diesel = next(v for v in found if v.fuel == "diesel")
    assert diesel.power_is_max and diesel.registrations == 200 and diesel.names == ("SORENTO",)
    assert group(rows, "Kia", "Sorento", fuel="hev", year_from=2020)[0].fuel == "hybrid"  # HEV is "hybrid"
    assert group(rows, "Kia", "Sorento", fuel="bev") == []


def test_model_tokens_match_a_name_with_the_make_and_a_two_word_model() -> None:
    rows = [_row("TOYOTA LANDCRUISER (150 SERIE", "diesel", 130, 2755, 2021, make="TOYOTA")]
    assert group(rows, "Toyota", "Land Cruiser", year_from=2020)
    assert not group(rows, "Toyota", "Cruiser X", year_from=2020)


def test_registered_label_never_shows_a_hybrid_engine_kw_as_the_power() -> None:
    words = {"engine": "двигатель", "diesel": "дизель"}
    assert ladder.registered_label("phev", 1598, 118, False, 2024, None, words) == "1.6 PHEV · двигатель 118 kW · 2024–"
    assert ladder.registered_label("phev", 1598, 132, False, 2021, 2023, {}) == "1.6 PHEV · engine 132 kW · 2021–2023"
    diesel = ladder.registered_label("diesel", 2151, 142, True, 2021, None, words)
    assert diesel == "2.2 дизель · 142 kW (193 CV) · 2021–"
    assert ladder.years_text(2024, 2024) == "2024" and ladder.years_text(None, None) == ""
