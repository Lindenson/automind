"""Next-step suggestions (spec 004 FR-020)."""

from automind.chat.domain.verdict import insights as ins
from automind.chat.domain.verdict import suggestions as sg
from automind.chat.domain.verdict import verdict as vd
from automind.shared.infrastructure.config.loader import load_yaml

RULES = ins.rules_from_config(load_yaml("insights.yaml"))
A = ins.CarValues("a", "A", {"consumption": 5.6, "official_price_es": 45_900}, energy_eur_per_unit=1.6)
B = ins.CarValues("b", "B", {"consumption": 6.4, "official_price_es": 35_500}, energy_eur_per_unit=1.6)
S = ins.build([A, B], ins.Profile(weights={"efficiency": 1}), RULES)


def _v(pick=None, tie=False):
    return vd.Verdict(pick, tie, (), None, "MEDIUM", "COVERAGE_MEDIUM", None, tied_cars=("a", "b") if tie else ())


def test_three_or_four_relevant_next_steps() -> None:
    out = sg.build(_v("a"), S, all_new=True, gaps_by_car={"car#2": ["price"]})
    kinds = [x.kind for x in out]
    assert 3 <= len(out) <= 4 and kinds[0] == "WHY_AHEAD" and "FIND_MISSING" in kinds
    find = next(x for x in out if x.kind == "FIND_MISSING")
    assert find.focus_cars == ("car#2",) and find.areas == ("price",)


def test_tie_and_used_cars_change_the_offer() -> None:
    out = sg.build(_v(tie=True), S, all_new=False, gaps_by_car={})
    kinds = [x.kind for x in out]
    assert kinds[0] == "TIE_BREAK" and "WHAT_IF_USED" not in kinds and "FIND_MISSING" not in kinds
    assert sg.build(_v(tie=True), S, all_new=False, gaps_by_car={}) == out  # deterministic
