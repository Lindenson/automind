"""Report sentences for electrified cars (spec 006 T050): share, cost per 100 km, break-even, in en/ru/es."""

import pytest

from automind.chat.dialog.report_text import electric_lines

BLOCK = {
    "cars": [
        {"car_id": "byd", "label": "BYD Seal U DM-i", "powertrain": "PHEV",
         "values": {"electric_share": {"share": 0.72}, "range": {"real_km": 58},
                    "cost_per_100km": {"used_eur": 4.1, "home_eur": 4.1, "public_eur": 9.35}}},
    ]
}  # fmt: skip
NAMES = {"byd": "BYD Seal U", "seat": "SEAT Ateca"}


def be(verdict: str, years: float | None = None, beyond: bool = False) -> dict:
    return {"verdict": verdict, "years": years, "electrified_car_id": "byd", "against_car_id": "seat",
            "beyond_ownership": beyond, "ownership_years": 5}  # fmt: skip


def test_share_cost_and_break_even_in_english():
    lines = electric_lines(BLOCK, be("YEARS", 3.5), NAMES, "en")
    assert lines[0] == "BYD Seal U: about 72% of your km on electricity (real electric range ≈58 km)"
    assert lines[1] == "BYD Seal U: €4.1 per 100 km charging at home, €9.35 at public chargers"
    assert "pays back" in lines[2] and "3.5 years" in lines[2]


def test_russian_and_spanish_use_decimal_commas():
    ru = electric_lines(BLOCK, be("YEARS", 7.5, beyond=True), NAMES, "ru")
    assert "72% вашего пробега" in ru[0] and "4,1 €" in ru[1] and "7,5 лет" in ru[2] and "владеть (5 лет)" in ru[2]
    es = electric_lines(BLOCK, be("NEVER"), NAMES, "es")
    assert "9,35 €" in es[1] and "no se amortiza" in es[2]


@pytest.mark.parametrize(("verdict", "word"), [("ALREADY_CHEAPER", "both to buy and to run"),
                                               ("CHEAPER_TO_BUY", "dearer to run")])  # fmt: skip
def test_other_verdicts(verdict, word):
    assert word in electric_lines(None, be(verdict), NAMES, "en")[0]


def test_nothing_when_unknown_or_already_said():
    assert electric_lines(None, be("UNKNOWN"), NAMES, "en") == []
    assert electric_lines(None, be("YEARS", 4), NAMES, "en", years_said=True) == []
    assert electric_lines(None, None, NAMES, "en") == []


def test_bev_has_no_share_sentence():
    bev = {"cars": [{**BLOCK["cars"][0], "powertrain": "BEV"}]}
    lines = electric_lines(bev, None, NAMES, "en")
    assert len(lines) == 1 and "per 100 km" in lines[0]


def test_an_active_subsidy_is_named():
    b = {**be("ALREADY_CHEAPER"), "subsidy_eur": 4500}
    assert electric_lines(None, b, NAMES, "en", years_said=True) == [
        "With the active subsidy (€4,500), the BYD Seal U is cheaper than the SEAT Ateca both to buy and to run"
    ]
    ru = electric_lines(None, b, NAMES, "ru")[0]
    assert ru.startswith("С действующей субсидией (4.500 €) BYD Seal U дешевле SEAT Ateca")
