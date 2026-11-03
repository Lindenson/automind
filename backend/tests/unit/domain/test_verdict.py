"""The verdict built by code (spec 004 FR-001, FR-011; US1)."""

from __future__ import annotations

from automind.domain import insights as ins
from automind.domain import verdict as vd
from automind.domain.criteria import CarScore, CriteriaScore
from automind.infrastructure.config import load_yaml

RULES = ins.rules_from_config(load_yaml("insights.yaml"))
PROFILE = ins.Profile(weights={"efficiency": 3, "purchase_price": 2, "practicality": 1})


def _car(cid, **v):
    return ins.CarValues(cid, cid, v, confidence={k: "HIGH" for k in v}, energy_eur_per_unit=1.6)


def _score(totals: dict[str, float], common=("efficiency", "purchase_price", "practicality"), tie=False):
    cars = [CarScore(k, k, t, 1.0, True, {}) for k, t in totals.items()]
    best = max(totals, key=lambda k: totals[k])
    return CriteriaScore(1, cars, None if tie else best, {"efficiency": 50, "purchase_price": 30, "practicality": 20},
                         list(common), tie)  # fmt: skip


A = _car("rav4", consumption=5.6, official_price_es=45_900, boot_volume=580)
B = _car("cx5", consumption=6.4, official_price_es=35_500, boot_volume=583)
S = ins.build([A, B], PROFILE, RULES)


def test_pick_with_reasons_trade_off_and_would_change() -> None:
    v = vd.build(_score({"rav4": 70, "cx5": 60}), S)
    assert v.pick_car_id == "rav4" and not v.tie
    assert v.reasons and v.reasons[0] == "consumption" and "boot_volume" not in v.reasons
    assert v.trade_off is not None and v.trade_off.break_even_years
    assert v.would_change is not None and v.would_change.kind == "BREAK_EVEN" and v.would_change.car_id == "cx5"
    assert v.confidence == "HIGH" and v.confidence_reason == "COVERAGE_HIGH"


def test_close_totals_are_a_tie_with_what_would_tip_it() -> None:
    v = vd.build(_score({"rav4": 61, "cx5": 60}, tie=True), S)
    assert v.tie and v.pick_car_id is None and set(v.tied_cars) == {"rav4", "cx5"}
    assert v.would_change is not None and v.would_change.kind == "PRIORITY"


def test_missing_key_data_lowers_confidence_and_names_the_gap() -> None:
    v = vd.build(_score({"rav4": 70, "cx5": 60}), S, gaps=["CX-5: maintenance"])
    assert v.confidence == "MEDIUM" and v.confidence_reason == "GAPS" and v.gaps == ("CX-5: maintenance",)


def test_low_coverage_is_medium_or_low() -> None:
    v = vd.build(_score({"rav4": 70, "cx5": 60}, common=("efficiency",)), S)
    assert v.confidence == "LOW"  # 50% of the weights
    v2 = vd.build(_score({"rav4": 70, "cx5": 60}, common=("efficiency", "practicality")), S)
    assert v2.confidence == "MEDIUM"


def test_no_ranking_basis_is_not_enough_data() -> None:
    v = vd.build(_score({"rav4": 70, "cx5": 60}, common=()), S, gaps=["RAV4: specs"])
    assert v.not_enough_data and v.pick_car_id is None and v.confidence == "LOW"
    assert v.would_change is not None and v.would_change.kind == "DATA"
    assert vd.build(None, S).not_enough_data


def test_single_car_has_no_pick_and_different_classes_are_flagged() -> None:
    v = vd.build(None, ins.build([A], PROFILE, RULES))
    assert v.pick_car_id is None and v.confidence_reason == "SINGLE"
    assert vd.very_different(["small", "premium_suv_4x4"]) and not vd.very_different(["compact", "mid_large"])
