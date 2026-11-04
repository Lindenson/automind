"""Live chat 8c6a2a58 (2026-11-04, spec 008 run): new Octavia 2.0 diesel vs Audi A4 2.5 used 50,000 km."""

from __future__ import annotations

from types import SimpleNamespace

from automind.application import ask, compose, intake_card
from automind.domain import tco
from automind.domain.casefile import CaseCar, CaseFile, LadderMemo
from automind.infrastructure.config import questions_i18n, rates


def _sv(x: float) -> SimpleNamespace:
    return SimpleNamespace(available=True, value_num=x, confidence="HIGH", claim_ids=["c1"])


def _car() -> dict:
    v = SimpleNamespace(id="a4", make="Audi", model="A4", vehicle_class="mid_large")
    return {"variant": v, "values": {"official_price_es": _sv(38060)}}


def test_a_used_car_is_never_compared_on_its_new_price() -> None:
    assert compose.insight_values(_car(), annual_cost=None, reliability_score=None,
                                  energy_eur_per_unit=None).values["official_price_es"] == 38060  # fmt: skip
    gone = compose.insight_values(_car(), annual_cost=None, reliability_score=None, energy_eur_per_unit=None,
                                  used=True)  # fmt: skip
    assert "official_price_es" not in gone.values
    priced = compose.insight_values(_car(), annual_cost=None, reliability_score=None, energy_eur_per_unit=None,
                                    used=True, used_price_eur=27500)  # fmt: skip
    assert priced.values["official_price_es"] == 27500


def test_unpriced_jobs_cost_service_visits_not_one_full_service_each() -> None:
    """Oil, brake fluid, plugs and battery check (twice, in English and Spanish) were six full services a year."""
    r = tco.TcoRates.from_config(rates())
    jobs = [tco.MaintenanceSched(n, km, m) for n, km, m in (
        ("oil and filter", 15000, 12), ("cambio de aceite y filtros", 15000, 12), ("brake fluid", None, 24),
        ("sustitución de líquidos (frenos)", None, 24), ("spark plugs", 60000, 48),
        ("battery inspection", None, 12))]  # fmt: skip
    car = tco.TcoCar("a4", "A4", "ICE", fuel="petrol", maintenance=jobs)
    item = tco._maintenance(car, r, 15000, 5)
    one = r.service_hours["ICE"] * r.labour_eur_per_h + r.service_parts_eur["ICE"]
    assert abs((item.annual_eur or 0) - one) < 1  # one visit a year does all of them
    assert sum("visit" in x for x in item.inputs) == 1


def _audi(origin: str | None) -> CaseCar:
    memo = LadderMemo(certainty="SOURCED", generation="B9", source_url="https://www.km77.com/a4",
                      others=["40 TFSI 204 CV", "30 TDI 136 CV"],
                      origin={"POWER": origin} if origin else {})  # fmt: skip
    return CaseCar(key="car#2", request_text="Audi A4 2.5 б/у 50000 км", make="Audi", model="A4", condition="USED",
                   year=2023, mileage_km=50000, variant_id="v", ladder=memo)  # fmt: skip


def _variant() -> SimpleNamespace:
    return SimpleNamespace(id="v", make="Audi", model="A4", generation="B9", engine_cc=1984, power_kw=110,
                           variant_name="35 TFSI", fuel="mhev", transmission="dct", trim=None, trim_level=None,
                           price_eur=None, label="Audi A4 B9 35 TFSI 150 CV DSG")  # fmt: skip


def test_the_card_says_who_chose_the_engine_and_offers_this_generation_only() -> None:
    card = intake_card.build_card(CaseFile(cars=[_audi("CHOSEN")]), {"v": _variant()},
                                  {"car#2": ["Audi A4 B6 2.5 TDI V6"]}, {}, "ru")  # fmt: skip
    engine = next(i for i in card["cars"][0]["items"] if i["field"] == "engine")
    assert engine["basis"] == "ASSUMED" and "выбери сам" in engine["evidence"]
    assert engine["options"] == ["40 TFSI 204 CV", "30 TDI 136 CV"]
    assert engine["source"]["url"] == "https://www.km77.com/a4"


def test_the_year_question_does_not_ask_the_mileage_again_and_names_a_generation_once() -> None:
    car = CaseCar(key="car#1", request_text="Audi A4 2.5", make="Audi", model="A4", condition="USED",
                  mileage_km=50000)  # fmt: skip
    items = ask.intake_questions(["USED_AGE"], CaseFile(cars=[car]), questions_i18n(),
                                 {"car#1": ["B8", "B9", "B6", "B9 (8W)"]}, ["car#1"], "ru")  # fmt: skip
    text = items[0]["text"]
    assert "пробег" not in text and "Какого года" in text
    assert text.count("B9") == 1
