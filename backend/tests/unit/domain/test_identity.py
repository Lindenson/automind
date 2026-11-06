"""Variant identity: aliases, canonical keys, generation years, de-dup (FR-007, FR-008, FR-024; R6)."""

import pytest
from rapidfuzz import fuzz

from automind.shared.vehicle.identity import (
    Aliases,
    canonical_key,
    generation_matches,
    is_duplicate,
    normalize_generation,
    normalize_make_model,
    plausible_generations,
)

ALIASES = Aliases.from_config(
    {
        "makes": {"vw": "Volkswagen", "mercedes": "Mercedes-Benz", "landrover": "Land Rover", "toyota": "Toyota"},
        "models": {
            "Land Rover|prado": {"make": "Toyota", "model": "Land Cruiser Prado"},
            "Toyota|prado": "Land Cruiser Prado",
            "Toyota|lc prado": "Land Cruiser Prado",
            "Land Rover|rr sport": "Range Rover Sport",
        },
        "generations": {
            "Toyota|Land Cruiser Prado": {"j150": "J150", "150": "J150", "j250": "J250", "250": "J250"},
            "Land Rover|Range Rover Sport": {"l320": "L320", "mk1": "L320"},
        },
    }
)


def test_make_aliases():
    assert normalize_make_model("VW", "golf", ALIASES) == ("Volkswagen", "golf")
    assert normalize_make_model("mercedes", "C-Class", ALIASES) == ("Mercedes-Benz", "C-Class")


def test_wrong_make_alias_is_corrected():
    assert normalize_make_model("Land Rover", "Prado", ALIASES) == ("Toyota", "Land Cruiser Prado")
    assert normalize_make_model("toyota", "LC Prado", ALIASES) == ("Toyota", "Land Cruiser Prado")


@pytest.mark.parametrize("raw", ["J150", "150", "j150", " 150 "])
def test_generation_aliases(raw):
    assert normalize_generation("Toyota", "Land Cruiser Prado", raw, ALIASES) == "J150"


def test_canonical_key_equal_for_alias_spellings():
    a = canonical_key("Land Rover", "Prado", "150", "3.0 D-4D", "ICE", ALIASES)
    b = canonical_key("Toyota", "Land Cruiser Prado", "J150", "3.0 D-4D", "ICE", ALIASES)
    assert a == b == "toyota|land cruiser prado|j150|3.0 d-4d|ice"
    c = canonical_key("Land Rover", "RR Sport", "Mk1", "TDV6", "ICE", ALIASES)
    d = canonical_key("Land Rover", "Range Rover Sport", "L320", "TDV6", "ICE", ALIASES)
    assert c == d


def test_canonical_key_without_aliases_is_still_normalized():
    assert canonical_key(" Hyundai ", "i30  N", None, "2.0 T-GDi", "ICE") == "hyundai|i30 n|-|2.0 t-gdi|ice"


@pytest.mark.parametrize(
    ("year", "lo", "hi", "ok"),
    [
        (2015, 2009, 2023, True),
        (2015, 2024, None, False),
        (2009, 2009, 2023, True),
        (2024, 2009, 2023, False),
        (2030, 2024, None, True),
        (2015, None, None, False),
    ],
)
def test_generation_year_range(year, lo, hi, ok):
    assert generation_matches(year, lo, hi) is ok


def test_generation_match_tolerates_one_year_around_age():
    # "about 10 years old" in 2026 -> 2016 ± 1
    assert generation_matches(2016, 2009, 2015, tolerance=1)
    assert not generation_matches(2016, 2009, 2014, tolerance=1)


def test_plausible_generations_for_used_car_without_age():
    gens = [("J120", 2002, 2009), ("J150", 2009, 2023), ("J250", 2024, None)]
    assert plausible_generations(gens, condition="USED", year=None, current_year=2026) == ["J120", "J150", "J250"]
    assert plausible_generations(gens, condition="USED", year=2015, current_year=2026) == ["J150"]
    assert plausible_generations(gens, condition="NEW", year=None, current_year=2026) == ["J250"]


def scorer(a: str, b: str) -> float:
    return fuzz.token_sort_ratio(a, b)


def test_fuzzy_duplicate_threshold_92_same_make_model_generation_powertrain():
    a = {
        "make": "Land Rover",
        "model": "Range Rover Sport",
        "generation": "L320",
        "powertrain": "ICE",
        "variant_name": "2.7 TDV6 HSE",
    }
    b = {**a, "variant_name": "2.7 TDV6  HSE "}
    c = {**a, "variant_name": "3.6 TDV8 HSE"}
    d = {**a, "generation": "L494"}
    assert is_duplicate(a, b, scorer)
    assert not is_duplicate(a, c, scorer)
    assert not is_duplicate(a, d, scorer)  # another generation is never a duplicate


def test_model_line_split():
    from automind.chat.application.services.identification.resolve import model_line

    known = {"Golf", "i30 N", "i30", "3 Series"}
    assert model_line("Golf GTI", known) == ("Golf", "GTI")
    assert model_line("golf", known) == ("Golf", "")
    assert model_line("i30 N", known) == ("i30 N", "")
    assert model_line("Model Y", known) == ("Model Y", "")
