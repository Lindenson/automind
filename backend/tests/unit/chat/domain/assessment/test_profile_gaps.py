"""Questions only when they change the answer (spec 004 FR-018, SC-006)."""

from automind.chat.domain.assessment import profile_gaps as pg
from automind.chat.domain.case.casefile import CaseFile, Needs


def test_km_asked_for_hybrid_vs_petrol_when_unknown() -> None:
    assert pg.questions(CaseFile(), ["HEV", "ICE"], ["compact", "compact"]) == ["KM_PER_YEAR"]
    assert pg.questions(CaseFile(annual_km=25000, annual_km_stated=True), ["HEV", "ICE"], []) == []
    assert pg.questions(CaseFile(), ["HEV", "HEV"], ["compact"]) == []  # same technology: km does not decide
    assert pg.questions(CaseFile(asked=["KM_PER_YEAR"]), ["HEV", "ICE"], []) == []  # asked once only


def test_family_asked_when_sizes_differ_and_nothing_is_known() -> None:
    assert pg.questions(CaseFile(persona="BUYER"), ["ICE", "ICE"], ["small", "mid_large"]) == ["FAMILY_SIZE"]
    assert pg.questions(CaseFile(persona="BUYER", needs=Needs(passengers=4)), ["ICE"], ["small", "mid_large"]) == []
    assert pg.questions(CaseFile(persona="EXPERT"), ["ICE"], ["small", "mid_large"]) == []


def test_at_most_two_profile_questions() -> None:
    assert len(pg.questions(CaseFile(persona="BUYER"), ["HEV", "ICE"], ["small", "mid_large"])) == 2
