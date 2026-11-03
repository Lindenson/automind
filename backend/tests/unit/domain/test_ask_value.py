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


# --- spec 007 J (T077): an inferred field that decides the winner is shown and confirmed, never silent ----------


def _guessing_outcome(case):
    counts = case.basis.get("family") != "ASSUMED" and case.profile.family == "FAMILY"
    return ("tiguan", False) if counts else ("golf", False)


def test_inferred_field_that_flips_the_winner_is_found():
    from automind.domain.ask_value import inferred_flip
    from automind.domain.casefile import CaseFile

    c = CaseFile(profile={"family": "FAMILY", "evidence": {"family": "вожу детей"}})
    c.basis["family"] = "INFERRED"
    assert inferred_flip(c, _guessing_outcome) == ("family", ("golf", False))
    c.basis["family"] = "STATED"  # confirmed: nothing to ask
    assert inferred_flip(c, _guessing_outcome) is None


def test_inferred_field_that_changes_nothing_is_not_asked():
    from automind.domain.ask_value import inferred_flip
    from automind.domain.casefile import CaseFile

    c = CaseFile(profile={"family": "FAMILY", "evidence": {"family": "x"}})
    c.basis["family"] = "INFERRED"
    assert inferred_flip(c, lambda _case: ("golf", False)) is None


def test_report_shows_the_assumption_and_asks_once():
    from types import SimpleNamespace

    from automind.domain.casefile import CaseFile
    from automind.orchestration.nodes.report import _confirm_inferred

    def car(i, name):
        return {"variant": SimpleNamespace(id=i, label=name, make="", model=name, variant_name=name,
                                           generation=None, model_year_from=None, model_year_to=None)}  # fmt: skip

    c = CaseFile(profile={"family": "FAMILY", "evidence": {"family": "вожу детей в школу"}})
    c.basis["family"] = "INFERRED"
    comp = SimpleNamespace(outcome=_guessing_outcome, cars=[car("tiguan", "Tiguan"), car("golf", "Golf")])
    blocks = [{"type": "verdict", "profile_notes": []}]
    q = _confirm_inferred(c, comp, blocks, "ru")
    assert q and q[0]["type"] == "quick_replies" and "победитель" in q[0]["question"]
    note = blocks[0]["profile_notes"][0]
    assert "вожу детей в школу" in note and "не подтверждено" in note
    again = [{"type": "verdict", "profile_notes": []}]
    assert _confirm_inferred(c, comp, again, "ru") == []  # asked once; the note stays
    assert again[0]["profile_notes"]
