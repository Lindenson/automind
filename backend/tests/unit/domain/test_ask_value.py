"""Questions by value (spec 007 FR-006): asked only when the answer changes the winner or the tie."""

from automind.domain import ask_value
from automind.domain.casefile import CaseFile

PROBES = {"annual_km": [8000, 15000, 30000], "ownership_years": [3, 6, 10], "persona": ["PERFORMANCE", "BUYER"]}


def km_flips(case):  # the diesel wins only for long distances
    return ("diesel", False) if case.annual_km >= 25000 else ("petrol", False)


def nothing_flips(case):
    return ("petrol", False)


def test_no_question_when_no_probe_value_changes_the_outcome():
    assert ask_value.questions(CaseFile(), nothing_flips, PROBES) == []


def test_km_asked_when_mileage_flips_the_winner():
    assert ask_value.questions(CaseFile(), km_flips, PROBES) == ["KM_PER_YEAR"]


def test_never_asks_a_stated_or_already_asked_field():
    stated = CaseFile(annual_km=15000, basis={"annual_km": "STATED"})
    assert ask_value.questions(stated, km_flips, PROBES) == []
    assert ask_value.questions(CaseFile(asked=["KM_PER_YEAR"]), km_flips, PROBES) == []


def test_at_most_one_question_the_most_decisive():
    def both(case):
        return (case.persona if case.persona != "UNKNOWN" else "x", case.annual_km >= 25000)

    assert ask_value.questions(CaseFile(), both, PROBES) == ["PERSONA"]  # 2 changes vs 1


def test_a_tie_change_counts():
    assert ask_value.questions(CaseFile(), lambda c: (None, c.annual_km < 10000), PROBES) == ["KM_PER_YEAR"]
