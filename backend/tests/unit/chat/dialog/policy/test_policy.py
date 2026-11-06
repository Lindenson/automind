"""Deterministic action policy, one test per rule of research.md R5 in order (FR-004..FR-006, FR-029, FR-041)."""

import pytest

from automind.chat.dialog.policy import decide
from automind.chat.domain.case import CarRef, CaseDelta, CaseFile, PersonaChange, apply
from automind.chat.domain.decision import CarState
from automind.chat.domain.fingerprint import fingerprint

YEAR = 2026


def case(*cars: dict, persona: str = "UNKNOWN", asked: tuple[str, ...] = ()) -> CaseFile:
    c, _ = apply(CaseFile(), CaseDelta(add_cars=[CarRef(**x) for x in cars]), current_year=YEAR)
    if persona != "UNKNOWN":
        c, _ = apply(c, CaseDelta(set_persona=PersonaChange(persona=persona, source="INFERRED")), current_year=YEAR)
    c.asked = list(asked)
    return c


NEW_GOLF = {"request_text": "Golf GTI Mk8", "make": "Volkswagen", "model": "Golf", "condition": "NEW"}
NEW_I30 = {"request_text": "i30 N", "make": "Hyundai", "model": "i30 N", "condition": "NEW"}
USED_PRADO = {"request_text": "used Prado", "make": "Toyota", "model": "Land Cruiser Prado", "condition": "USED"}


def ready(c: CaseFile, **over) -> dict[str, CarState]:
    """All cars resolved, in catalog, data fresh."""
    for car in c.cars:
        car.variant_id, car.resolution = f"v-{car.key}", "CONFIRMED"
    return {
        car.key: CarState(**{"in_catalog": True, "plausible_generations": 1, "data_fresh": True, **over})
        for car in c.cars
    }


# 1. general / chitchat
@pytest.mark.parametrize("req", ["general_question", "chitchat"])
def test_rule1_general(req):
    c = case(NEW_GOLF)
    a = decide(c, req, ready(c), cost_estimate_eur=None, last_fingerprint=None)
    assert a.kind == "ANSWER_GENERAL"


# 2. essentials missing -> ASK
def test_rule2_used_car_without_age_spanning_generations_asks_age():
    c = case(
        {"request_text": "new Bigster", "make": "Dacia", "model": "Bigster", "condition": "NEW"},
        USED_PRADO,
        persona="BUYER",
    )
    st = {
        "car#1": CarState(in_catalog=True, plausible_generations=1),
        "car#2": CarState(in_catalog=True, plausible_generations=3),
    }
    a = decide(c, "compare", st, cost_estimate_eur=None, last_fingerprint=None)
    assert a.kind == "ASK" and a.questions == ["USED_AGE"] and a.cars == ["car#2"]


def test_rule2_used_car_with_single_plausible_generation_does_not_ask():
    c = case(USED_PRADO, persona="BUYER")
    a = decide(
        c,
        "single",
        {"car#1": CarState(in_catalog=True, plausible_generations=1)},
        cost_estimate_eur=None,
        last_fingerprint=None,
    )
    assert a.kind == "CONFIRM_VARIANTS"  # used -> confirm, but no question


def test_rule2_unknown_identity_and_too_many_cars():
    c = case({"request_text": "that red car"}, NEW_GOLF, NEW_I30, {"request_text": "X5", "make": "BMW", "model": "X5"})
    st = {
        k: CarState(in_catalog=k != "car#1", identity_known=k != "car#1") for k in ("car#1", "car#2", "car#3", "car#4")
    }
    a = decide(c, "compare", st, cost_estimate_eur=None, last_fingerprint=None)
    assert a.kind == "ASK"
    assert a.questions[:2] == ["TOO_MANY_CARS", "CAR_IDENTITY"]
    assert len(a.questions) <= 3


def test_rule2_persona_question_only_piggybacks_on_another_question():
    c = case(USED_PRADO)  # persona UNKNOWN
    a = decide(
        c,
        "compare",
        {"car#1": CarState(in_catalog=True, plausible_generations=2)},
        cost_estimate_eur=None,
        last_fingerprint=None,
    )
    assert a.kind == "ASK" and a.questions == ["USED_AGE", "PERSONA"]
    c2 = case(NEW_GOLF, NEW_I30)  # nothing else missing -> no persona questionnaire (FR-005a)
    a2 = decide(c2, "compare", ready(c2), cost_estimate_eur=None, last_fingerprint=None)
    assert a2.kind == "REPORT"


def test_rule2_one_round_only_already_asked_kinds_are_not_repeated():
    c = case(USED_PRADO, asked=("USED_AGE", "PERSONA"))
    a = decide(
        c,
        "compare",
        {"car#1": CarState(in_catalog=True, plausible_generations=2)},
        cost_estimate_eur=None,
        last_fingerprint=None,
    )
    assert a.kind == "CONFIRM_VARIANTS"  # offer generations as options instead of asking again


# 3. ambiguous, used or uncatalogued -> CONFIRM_VARIANTS
@pytest.mark.parametrize(
    ("car", "state"),
    [
        (NEW_GOLF, CarState(in_catalog=True, ambiguous=True)),
        (NEW_GOLF, CarState(in_catalog=False)),
        ({**USED_PRADO, "year": 2015}, CarState(in_catalog=True, plausible_generations=1)),
    ],
)
def test_rule3_confirm_variants(car, state):
    c = case(car, persona="BUYER")
    a = decide(c, "single", {"car#1": state}, cost_estimate_eur=None, last_fingerprint=None)
    assert a.kind == "CONFIRM_VARIANTS" and a.cars == ["car#1"]


def test_rule3_unambiguous_cached_new_car_does_not_confirm():
    c = case(NEW_GOLF, persona="BUYER")
    c.cars[0].variant_id, c.cars[0].resolution = "v1", "AUTO_OK"
    a = decide(
        c,
        "single",
        {"car#1": CarState(in_catalog=True, data_fresh=True)},
        cost_estimate_eur=None,
        last_fingerprint=None,
    )
    assert a.kind == "REPORT"


def test_rule3_confirmed_used_car_is_not_reconfirmed():
    c = case({**USED_PRADO, "year": 2015}, persona="BUYER")
    a = decide(c, "single", ready(c), cost_estimate_eur=None, last_fingerprint=None)
    assert a.kind == "REPORT"


# 4. research needed: estimate >= threshold -> CONFIRM_COST else RESEARCH
@pytest.mark.parametrize(("eur", "kind"), [(0.12, "RESEARCH"), (0.30, "CONFIRM_COST"), (0.85, "CONFIRM_COST")])
def test_rule4_cost(eur, kind):
    c = case(NEW_GOLF, NEW_I30, persona="PERFORMANCE")
    a = decide(c, "compare", ready(c, data_fresh=False), cost_estimate_eur=eur, last_fingerprint=None)
    assert a.kind == kind and a.cars == ["car#1", "car#2"]


def test_rule4_cost_approved_or_declined():
    c = case(NEW_GOLF, persona="PERFORMANCE")
    st = ready(c, data_fresh=False)
    assert decide(c, "compare", st, cost_estimate_eur=0.8, last_fingerprint=None, cost_approved=True).kind == "RESEARCH"
    a = decide(c, "compare", st, cost_estimate_eur=0.8, last_fingerprint=None, research_declined=True)
    assert a.kind == "REPORT"  # answer with what exists


def test_rule4_estimate_above_hard_cap_still_needs_confirmation():
    c = case(NEW_GOLF, persona="PERFORMANCE")
    a = decide(
        c, "compare", ready(c, data_fresh=False), cost_estimate_eur=1.4, last_fingerprint=None, cost_approved=False
    )
    assert a.kind == "CONFIRM_COST" and a.over_cap


# 5. weights_change / follow-up with data -> ANSWER_FROM_CONTEXT
@pytest.mark.parametrize("req", ["weights_change", "follow_up_question"])
def test_rule5_answer_from_context(req):
    c = case(NEW_GOLF, NEW_I30, persona="BUYER")
    a = decide(c, req, ready(c), cost_estimate_eur=None, last_fingerprint="old")
    assert a.kind == "ANSWER_FROM_CONTEXT" and not a.nothing_new


def test_rule5_follow_up_without_cars_is_general():
    a = decide(CaseFile(), "follow_up_question", {}, cost_estimate_eur=None, last_fingerprint=None)
    assert a.kind == "ANSWER_GENERAL"


# 6. otherwise REPORT; unchanged fingerprint -> ANSWER_FROM_CONTEXT "nothing new"
def test_rule6_report_then_no_repeat():
    c = case(NEW_GOLF, NEW_I30, persona="PERFORMANCE")
    st = ready(c)
    assert decide(c, "compare", st, cost_estimate_eur=None, last_fingerprint=None).kind == "REPORT"
    a = decide(c, "compare", st, cost_estimate_eur=None, last_fingerprint=fingerprint(c))
    assert a.kind == "ANSWER_FROM_CONTEXT" and a.nothing_new


def test_rule6_correction_that_changes_nothing_is_not_a_repeat():
    c = case({**USED_PRADO, "year": 2015}, NEW_GOLF, persona="BUYER")
    st = ready(c)
    a = decide(c, "correction", st, cost_estimate_eur=None, last_fingerprint=fingerprint(c))
    assert a.kind == "ANSWER_FROM_CONTEXT" and a.nothing_new


def test_single_car_is_a_profile_report():
    c = case(NEW_GOLF, persona="BUYER")
    a = decide(c, "single", ready(c), cost_estimate_eur=None, last_fingerprint=None)
    assert a.kind == "REPORT" and a.profile


def test_fingerprint_changes_with_what_the_report_depends_on():
    c = case(NEW_GOLF, NEW_I30, persona="BUYER")
    ready(c)
    f = fingerprint(c)
    assert fingerprint(c) == f
    c2 = c.model_copy(deep=True)
    c2.weights = {"reliability": 100.0}
    c3 = c.model_copy(deep=True)
    c3.persona = "EXPERT"
    c4 = c.model_copy(deep=True)
    c4.cars[1].variant_id = "other"
    c5 = c.model_copy(deep=True)
    c5.budget.max_eur = 1  # the budget frames the verdict, so a new budget allows a new report
    assert len({f, fingerprint(c2), fingerprint(c3), fingerprint(c4)}) == 4
    assert fingerprint(c5) != f


def test_rule5_correction_that_matches_the_case_after_other_changes():
    """G1: after "status" was added, "I meant the used 150" (already the 150) must not re-report."""
    c = case({**USED_PRADO, "year": 2016}, NEW_GOLF, persona="BUYER")
    st = ready(c)
    a = decide(c, "correction", st, cost_estimate_eur=None, last_fingerprint="older-report", case_changed=False)
    assert a.kind == "ANSWER_FROM_CONTEXT" and a.nothing_new
    b = decide(c, "correction", st, cost_estimate_eur=None, last_fingerprint="older-report", case_changed=True)
    assert b.kind == "REPORT"


# --- spec 007 FR-012, FR-013: split fingerprint and RESCORE -------------------------------------------------------


def _decide_rescore(c, last):
    return decide(c, "rescore", ready(c), cost_estimate_eur=0.0, last_fingerprint=last)


def test_profile_change_changes_only_the_params_part():
    from automind.chat.domain.fingerprint import fingerprint_data, fingerprint_params

    c = case(NEW_GOLF, NEW_I30)
    ready(c)
    before = fingerprint(c)
    c2 = c.model_copy(deep=True)
    c2.profile.family, c2.ownership_years = "FAMILY", 8  # missing from the old fingerprint
    assert fingerprint_data(c2) == before.split(":")[0] and fingerprint_params(c2) != before.split(":")[1]


def test_rescore_after_a_params_change_and_never_research_even_when_stale():
    c = case(NEW_GOLF, NEW_I30)
    st = ready(c, data_fresh=False)
    last = fingerprint(c)
    c.annual_km = 30000
    a = decide(c, "rescore", st, cost_estimate_eur=0.5, last_fingerprint=last)
    assert a.kind == "RESCORE" and a.reason == "params_changed"


def test_rescore_with_nothing_changed_or_no_report_yet():
    c = case(NEW_GOLF, NEW_I30)
    ready(c)
    assert _decide_rescore(c, fingerprint(c)).nothing_new
    assert _decide_rescore(c, None).kind == "REPORT"


def test_rescore_after_a_car_change_is_a_full_report_and_old_fingerprints_differ():
    c = case(NEW_GOLF, NEW_I30)
    st = ready(c)
    last = fingerprint(c)
    c.cars[1].variant_id = "v-other"
    assert decide(c, "rescore", st, cost_estimate_eur=0.0, last_fingerprint=last).kind == "REPORT"
    assert _decide_rescore(c, "0123456789abcdef0123456789abcdef").kind == "RESCORE"  # pre-007 single hash
