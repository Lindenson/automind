"""Chat 5821ac77: ownership cost is compared on the total over the period INCLUDING depreciation.

Toyota Land Cruiser Prado J150 2016 (used) vs Kia Sorento MQ4 PHEV (new), 5 years, 15,000 km a year assumed. The
report said "Sorento costs €1,281 a year vs €4,907 for the Prado (saving €3,625 a year), pays back in about 3.5
years", while the 5-year totals with depreciation were Sorento €31,738 vs Prado €29,406.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from automind.domain import insights as ins
from automind.domain import tco
from automind.domain import verdict as vd
from automind.domain.casefile import CaseFile
from automind.domain.criteria import CarScore, CriteriaModel, CriteriaScore, score
from automind.domain.metrics import CarFacts
from automind.infrastructure.config import load_yaml
from automind.orchestration import report_text
from automind.orchestration.guard import CheckInput, report_violations, saving_for_costlier, violations_prompt
from automind.orchestration.nodes.compute import assumption_lines, costlier_names, ownership_facts

CONFIG = Path(__file__).parents[2] / "config"
RULES = ins.rules_from_config(load_yaml("insights.yaml"))
RATES = tco.TcoRates.from_config(yaml.safe_load((CONFIG / "rates.yaml").read_text()))
NAMES = {"prado": "Toyota Land Cruiser Prado", "sorento": "Kia Sorento"}

# running costs per year and the value lost per year, as in the live report (5-year totals 29,406 / 31,738)
PRADO = ins.CarValues("prado", NAMES["prado"], {"official_price_es": 30_000, "tco_per_year": 4_907,
                                                "tco_period": 29_406},
                      cost_curve=tuple((4_907 + 974.2) * t for t in range(1, 16)))  # fmt: skip
SORENTO = ins.CarValues("sorento", NAMES["sorento"], {"official_price_es": 52_000, "tco_per_year": 1_281,
                                                      "tco_period": 31_738},
                        cost_curve=tuple((1_281 + 5_066.6) * t for t in range(1, 16)))  # fmt: skip
OWNER = ins.Profile(weights={"ownership_cost": 5, "reliability": 3}, annual_km=15000, years=5)
ISET = ins.build([PRADO, SORENTO], OWNER, RULES)
CHECK = CheckInput(frozenset({"tco"}), frozenset(), False, tuple(NAMES.values()), costlier=("Kia Sorento",))


def _score(pick: str) -> CriteriaScore:
    totals = {"prado": 60.0, "sorento": 60.0, pick: 75.0}
    cars = [CarScore(k, NAMES[k], t, 1.0, True, {}) for k, t in totals.items()]
    return CriteriaScore(1, cars, pick, {"ownership_cost": 60, "reliability": 40},
                         ["ownership_cost", "reliability"], False)  # fmt: skip


def _sentences(block: dict) -> list[str]:
    out = [block["headline"], *(r["text"] for r in block["reasons"]), *block["profile_notes"]]
    if block["trade_off"]:
        out.append(block["trade_off"]["text"])
    if block["would_change"]:
        out.append(block["would_change"])
    return out


# --- verdict and insights on period totals ----------------------------------------------------------------------


def test_the_costlier_car_over_the_period_is_named_from_the_totals():
    assert costlier_names(ISET, NAMES) == ("Kia Sorento",)


@pytest.mark.parametrize("pick", ["prado", "sorento"])
@pytest.mark.parametrize("lang", ["en", "ru", "es"])
def test_no_saving_claim_for_the_sorento(pick, lang):
    """Whatever the criteria pick, the code-built verdict never calls the Sorento a saving or a payback."""
    v = vd.build(_score(pick), ISET)
    block = report_text.verdict_block(v, ISET, NAMES, lang, years=5)
    for s in _sentences(block):
        assert not saving_for_costlier(s, CHECK), s
    trade = block["trade_off"]["text"]
    total_s, total_p = report_text.fmt(31_738, "EUR", lang), report_text.fmt(29_406, "EUR", lang)
    assert total_s in trade and total_p in trade  # both totals including depreciation are stated


def test_english_trade_off_says_running_costs_without_depreciation_and_no_payback():
    v = vd.build(_score("prado"), ISET)
    trade = report_text.verdict_block(v, ISET, NAMES, "en", years=5)["trade_off"]["text"]
    assert "without depreciation" in trade and "costs more" in trade and "does not pay back within 15 years" in trade
    assert "€31,738" in trade and "€29,406" in trade
    notes = report_text.profile_lines(v, NAMES, "en", 5)
    assert any("Counting depreciation" in n and "do not pay that back" in n for n in notes)
    assert v.would_change is None or v.would_change.kind != "BREAK_EVEN"


def test_the_period_total_is_a_reason_and_running_costs_are_labelled():
    v = vd.build(_score("prado"), ISET)
    block = report_text.verdict_block(v, ISET, NAMES, "en", years=5)
    reasons = [r["text"] for r in block["reasons"]]
    assert any(r.startswith("Total cost over the period (incl. depreciation)") for r in reasons)
    assert report_text.LABELS["tco_per_year"]["en"] == "Running costs per year (without depreciation)"


def test_a_payback_within_the_period_counts_depreciation():
    """The dearer car that is cheaper over the period: the payback year comes from the total cost curves."""
    cheap = ins.CarValues("a", "A", {"official_price_es": 30_000, "tco_per_year": 4_000, "tco_period": 28_000},
                          cost_curve=tuple(5_600 * t for t in range(1, 16)))  # fmt: skip
    dear = ins.CarValues("b", "B", {"official_price_es": 40_000, "tco_per_year": 1_500, "tco_period": 26_000},
                         cost_curve=tuple(6_000 + 4_000 * t for t in range(1, 16)))  # fmt: skip
    s = ins.build([cheap, dear], OWNER, RULES)
    t = s.trade_offs[0]
    assert (t.gain, t.cost, t.gain_car) == ("tco_period", "official_price_es", "b")
    assert t.break_even_years == 4.0  # 6,000 / (5,600 − 4,000)
    v = vd.build(CriteriaScore(1, [CarScore("a", "A", 60, 1.0, True, {}), CarScore("b", "B", 75, 1.0, True, {})],
                               "b", {"ownership_cost": 100}, ["ownership_cost"], False), s)  # fmt: skip
    text = report_text.verdict_block(v, s, {"a": "A", "b": "B"}, "en", 5)
    assert "less to own over your 5 years including depreciation" in text["trade_off"]["text"]
    wc = "If you keep the car less than 4 years, the A comes out ahead (counting depreciation)"
    assert text["would_change"] == wc


# --- the report check: a saving claim for the costlier car is a contradiction ------------------------------------


@pytest.mark.parametrize("text", [
    "The Sorento costs €1,281 a year vs €4,907 for the Prado (saving €3,625 a year), and pays back in about 3.5 years.",
    "Compared with the Prado, the Kia Sorento is cheaper to own.",
    "Kia Sorento даёт экономию 3 625 € в год.",
    "Sorento выгоднее Prado в содержании.",
    "El Sorento supone un ahorro de 3.625 € al año.",
    "El Sorento sale más barato que el Prado.",
])  # fmt: skip
def test_a_saving_claim_for_the_costlier_car_is_rejected(text):
    v = report_violations(text, CHECK)
    assert [x.rule for x in v] == ["saving_costlier"]
    assert "including depreciation" in violations_prompt(v)


@pytest.mark.parametrize("text", [
    "Over 5 years including depreciation the Prado is cheaper: €29,406 vs €31,738.",
    "Compared with the Sorento, the Prado saves €2,332 over 5 years.",
    "The Sorento has lower running costs (without depreciation): €1,281 a year.",
    "У Sorento ниже расходы на содержание без учёта потери стоимости.",
    "El Sorento tiene menor coste de uso sin depreciación.",
    "The Sorento does not pay back its higher price within 15 years.",
    "Prado дешевле, чем Sorento, за 5 лет.",
])  # fmt: skip
def test_true_cost_statements_pass(text):
    assert report_violations(text, CHECK) == []


def test_no_check_when_the_totals_are_about_the_same():
    calm = CheckInput(frozenset(), frozenset(), False, tuple(NAMES.values()))
    assert report_violations("The Sorento saves €3,625 a year.", calm) == []


# --- facts for the writer ----------------------------------------------------------------------------------------


def _est(car_id: str, annual: float, period: float, dep: float | None) -> tco.TcoEstimate:
    items = [tco.TcoItem("ENERGY", "Energy", annual, annual * 5, "ASSUMPTION", []),
             tco.TcoItem("DEPRECIATION", "Depreciation", dep / 5 if dep else None, dep, "ASSUMPTION", [])]  # fmt: skip
    return tco.TcoEstimate(car_id, NAMES[car_id], "NEW", None, 15000, items, annual, period, years=5)


def test_ownership_facts_carry_the_period_totals_and_which_car_is_cheaper():
    est = [_est("prado", 4_907, 29_406, 4_871), _est("sorento", 1_281, 31_738, 25_333)]
    f = ownership_facts(est, {"prado": 29_406, "sorento": 31_738}, 5, NAMES, ISET)
    assert f["cheaper_to_own_over_the_period"] == "Toyota Land Cruiser Prado"
    assert f["costlier_to_own_over_the_period"] == ["Kia Sorento"]
    assert f["difference_over_the_period_eur"] == 2_332
    rows = {r["car"]: r for r in f["cars"]}
    assert rows["Kia Sorento"]["total_over_the_period_including_depreciation_eur"] == 31_738
    assert rows["Kia Sorento"]["running_costs_per_year_without_depreciation_eur"] == 1_281
    none = ownership_facts(est, {}, 5, NAMES, None)
    assert "cheaper_to_own_over_the_period" not in none and "never claim" in none["rule"]


def test_cost_curve_matches_the_period_total_and_is_empty_without_value_data():
    curve_ = {0.0: 1.0, 3.0: 0.6, 5.0: 0.5, 10.0: 0.3}
    car = tco.TcoCar("c", "Car", "ICE", fuel="petrol", consumption=7.0, vehicle_class="compact", price_eur=40_000,
                     retention_curve=curve_)  # fmt: skip
    c = tco.cost_curve(car, RATES, 15000)
    assert len(c) == tco.MAX_PAYBACK_YEARS and c[4] == tco.compute(car, RATES, 15000, 5).period_total
    assert tco.cost_curve(tco.TcoCar("x", "X", "ICE", fuel="petrol", consumption=7.0), RATES) == ()
    assert tco.payback_years((10, 12, 14), (5, 11, 17)) == 2.5
    assert tco.payback_years((10, 20), (5, 10)) is None


# --- the ownership-cost score counts depreciation -----------------------------------------------------------------


def test_ownership_score_uses_the_period_total_including_depreciation():
    model = CriteriaModel.from_config(yaml.safe_load((CONFIG / "criteria.yaml").read_text()))
    base = dict(powertrain="ICE", condition="NEW")
    prado = CarFacts(car_id="prado", label="Prado", annual_cost_eur=4_907, period_cost_eur=29_406, period_years=5,
                     **base)  # fmt: skip
    sorento = CarFacts(car_id="sorento", label="Sorento", annual_cost_eur=1_281, period_cost_eur=31_738,
                       period_years=5, **base)  # fmt: skip
    sc = score([prado, sorento], {"ownership_cost": 100}, model)
    parts = {c.car_id: c.parts["ownership_cost"] for c in sc.cars}
    assert parts["prado"].score > parts["sorento"].score
    assert "including depreciation" in parts["sorento"].inputs[0]
    only_running = score([CarFacts(car_id="x", label="X", annual_cost_eur=2_000, **base)], {"ownership_cost": 100},
                         model)  # fmt: skip
    assert "without depreciation" in only_running.cars[0].parts["ownership_cost"].inputs[0]


# --- an assumed mileage or period is said, with the value ------------------------------------------------------


def test_assumed_mileage_and_period_are_said_once_with_the_value():
    case = CaseFile(annual_km=15000, basis={"annual_km": "ASSUMED", "ownership_years": "ASSUMED"}, ownership_years=5)
    assert assumption_lines(case, RATES, "en") == [
        "Assumed 15,000 km/year and 5 years of ownership — tell me your mileage and period and I will recount the "
        "costs."
    ]
    km_only = CaseFile(annual_km=15000, basis={"annual_km": "ASSUMED", "ownership_years": "STATED"}, ownership_years=5)
    assert assumption_lines(km_only, RATES, "ru") == [
        "Принято 15.000 км в год — напишите свой пробег, и я пересчитаю расходы."
    ]
    stated = CaseFile(annual_km=8000, annual_km_stated=True, basis={"annual_km": "STATED", "ownership_years": "STATED"},
                      ownership_years=7)  # fmt: skip
    assert assumption_lines(stated, RATES, "es") == []
