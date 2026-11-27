"""Spec 015 T204: every branch of every rule, fired with its action and skipped with its reason — each rule asked
directly, without the chain."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from automind.chat.dialog.policy import RULES, Situation
from automind.chat.dialog.policy.rules import answer, confirm, general, intake, limits, research
from automind.chat.domain.case import CaseCar, CaseFile, IdentifyOutcome
from automind.chat.domain.decision import CarState
from automind.chat.domain.fingerprint import fingerprint

from .builder import MAX_PASSES, config, situation
from .test_policy import NEW_GOLF, NEW_I30, USED_PRADO, case, ready


def settled(*cars: dict, **kw) -> Situation:
    """A case whose cars are confirmed, in the catalogue and fresh (unless `states` overrides them)."""
    c = case(*cars, persona="BUYER")
    states = kw.pop("states", None) or ready(c)
    return situation(c, kw.pop("request", "compare"), states, **kw)


def identified(*cars: dict, outcome: str = "IDENTIFIED", need: str | None = None, **kw) -> Situation:
    """Cars that went through identification with `outcome` (versions set unless the outcome needs more)."""
    c = case(*cars, persona="BUYER")
    states = ready(c) if outcome == "IDENTIFIED" else {}
    for car in c.cars:
        car.identify = IdentifyOutcome(outcome=outcome, need=need)
    return situation(c, kw.pop("request", "compare"), states, **kw)


def fp_changed(part: str) -> Situation:
    s = settled(NEW_GOLF, request="rescore")
    data, params = fingerprint(s.case).split(":")
    old = f"{data}:old" if part == "params" else f"old:{params}"
    return s.model_copy(update={"last_fingerprint": old})


def with_case(s: Situation, **update) -> Situation:
    return s.model_copy(update={"case": s.case.model_copy(update=update)})


def unchanged(s: Situation) -> Situation:
    return s.model_copy(update={"last_fingerprint": fingerprint(s.case)})


def card(s: Situation, **intake_update) -> Situation:
    return with_case(s, intake=s.case.intake.model_copy(update=intake_update))


def stale(s: Situation) -> Situation:
    return s.model_copy(update={"cars": tuple(f.model_copy(update={"data_fresh": False}) for f in s.cars)})


def _proposed(c: CaseFile) -> CaseFile:
    c.cars[0].resolution = "PROPOSED"
    return c


FOUR_CARS = (NEW_GOLF, NEW_I30, USED_PRADO, {"request_text": "X5", "make": "BMW", "model": "X5"})
KIA_FAMILY = CaseFile(wanted_make="Kia")

# (rule, label, situation, fired, action kind or None, a word of `why`)
TABLE: list[tuple[type, str, Callable[[], Situation], bool, str | None, str]] = [
    (limits.PassLimit, "passes left", lambda: settled(NEW_GOLF, pass_no=MAX_PASSES), False, None, "passes left"),
    (limits.PassLimit, "limit with a version", lambda: settled(NEW_GOLF, pass_no=MAX_PASSES + 1), True, "REPORT",
     "hop"),
    (limits.PassLimit, "limit without a version", lambda: situation(case(NEW_GOLF), pass_no=MAX_PASSES + 1), True,
     "ANSWER_GENERAL", "hop"),
    (limits.ReportAfterTimeout, "other request", lambda: settled(NEW_GOLF), False, None, "not a report"),
    (limits.ReportAfterTimeout, "no version", lambda: situation(case(NEW_GOLF), "report_saved"), False, None,
     "no car has a version"),
    (limits.ReportAfterTimeout, "saved data", lambda: settled(NEW_GOLF, request="report_saved"), True, "REPORT",
     "timeout"),
    (limits.PanelEdit, "other request", lambda: settled(NEW_GOLF), False, None, "not a panel edit"),
    (limits.PanelEdit, "no cars", lambda: situation(CaseFile(), "rescore"), False, None, "no cars"),
    (limits.PanelEdit, "no report yet", lambda: settled(NEW_GOLF, request="rescore"), True, "REPORT", "no report"),
    (limits.PanelEdit, "nothing new", lambda: unchanged(settled(NEW_GOLF, request="rescore")), True,
     "ANSWER_FROM_CONTEXT", "nothing_new"),
    (limits.PanelEdit, "data changed", lambda: fp_changed("data"), True, "REPORT", "data_changed"),
    (limits.PanelEdit, "params changed", lambda: fp_changed("params"), True, "RESCORE", "params_changed"),
    (general.Candidates, "general question", lambda: situation(KIA_FAMILY, "general_question"), False, None,
     "general"),
    (general.Candidates, "a car named", lambda: settled(NEW_GOLF), False, None, "a car named"),
    (general.Candidates, "a make to choose from", lambda: situation(KIA_FAMILY), True, "SELECT_CANDIDATES", "need"),
    (general.GeneralAnswer, "cars to compare", lambda: settled(NEW_GOLF), False, None, "cars to compare"),
    (general.GeneralAnswer, "chitchat", lambda: settled(NEW_GOLF, request="chitchat"), True, "ANSWER_GENERAL",
     "general"),
    (general.GeneralAnswer, "no cars", lambda: situation(CaseFile()), True, "ANSWER_GENERAL", "no cars"),
    (intake.IntakeStep, "too many cars", lambda: identified(*FOUR_CARS), False, None, "too many cars"),
    (intake.IntakeStep, "no identification", lambda: settled(NEW_GOLF), False, None, "no car went through"),
    (intake.IntakeStep, "identified: the card", lambda: identified(NEW_GOLF), False, None, "CARD"),
    (intake.IntakeStep, "model not found", lambda: identified({"request_text": "Kia", "make": "Kia"},
     outcome="NOT_FOUND", need="MODEL"), True, "ASK", "identity not settled"),
    (intake.IntakeStep, "attempts on an item ran out",
     lambda: card(identified(NEW_GOLF, outcome="CHOICES", need="ENGINE"), attempts={"car#1": {"ENGINE": 2}}),
     True, "ASK", "PROPOSE"),
    (intake.IntakeStep, "attempts on a car ran out",
     lambda: card(identified(NEW_GOLF, outcome="CHOICES", need="ENGINE"), attempts={"car#1": {"ENGINE": 1, "FUEL": 3}}),
     True, "ASK", "REMOVE_OR_CHOOSE"),
    (intake.MissingEssentials, "nothing missing", lambda: settled(NEW_GOLF), False, None, "nothing essential"),
    (intake.MissingEssentials, "used car age", lambda: settled(USED_PRADO, states={"car#1": CarState(
     in_catalog=True, plausible_generations=3)}), True, "ASK", "missing"),
    (confirm.IntakeCard, "card confirmed", lambda: card(identified(NEW_GOLF), card_confirmed=True), False, None,
     "confirmed"),
    (confirm.IntakeCard, "no identification", lambda: settled(NEW_GOLF), False, None, "no car went through"),
    (confirm.IntakeCard, "no version", lambda: identified(NEW_GOLF, outcome="NEED", need="ENGINE"), False, None,
     "no version"),
    (confirm.IntakeCard, "nothing to confirm", lambda: identified(NEW_GOLF), False, None, "nothing to confirm"),
    (confirm.IntakeCard, "candidates chosen by us",
     lambda: with_case(identified(NEW_GOLF), candidates=[{"make": "Volkswagen"}]), True, "CONFIRM_INTAKE", "confirm"),
    (confirm.IntakeCard, "a proposed version", lambda: identified({**NEW_GOLF, "request_text": "Golf"}).model_copy(
     update={"case": _proposed(identified(NEW_GOLF).case)}), True, "CONFIRM_INTAKE", "confirm"),
    (confirm.IntakeCard, "research after questions", lambda: card(stale(identified(NEW_GOLF)), last_questions=["h"]),
     True, "CONFIRM_INTAKE", "confirm"),
    (confirm.IntakeCard, "research above the threshold",
     lambda: stale(identified(NEW_GOLF, cost_estimate_eur=0.5)), True, "CONFIRM_INTAKE", "confirm"),
    (confirm.IntakeCard, "research declined", lambda: stale(identified(NEW_GOLF, cost_estimate_eur=0.5,
     research_declined=True)), False, None, "nothing to confirm"),
    (confirm.Variants, "every version settled", lambda: settled(NEW_GOLF), False, None, "settled"),
    (confirm.Variants, "used car", lambda: situation(case(USED_PRADO), "compare", {"car#1": CarState(in_catalog=True)}),
     True, "CONFIRM_VARIANTS", "used"),
    (research.StaleData, "fresh", lambda: settled(NEW_GOLF), False, None, "fresh"),
    (research.StaleData, "declined", lambda: stale(settled(NEW_GOLF, research_declined=True)), False, None,
     "declined"),
    (research.StaleData, "cost to confirm", lambda: stale(settled(NEW_GOLF, cost_estimate_eur=0.30)), True,
     "CONFIRM_COST", "estimated"),
    (research.StaleData, "cost approved", lambda: stale(settled(NEW_GOLF, cost_estimate_eur=0.5, cost_approved=True)),
     True, "RESEARCH", "stale"),
    (research.StaleData, "below the threshold", lambda: stale(settled(NEW_GOLF, cost_estimate_eur=0.29)), True,
     "RESEARCH", "stale"),
    (answer.AnswerOrReport, "find more", lambda: settled(NEW_GOLF, request="research_more"), True, "REPORT",
     "research more"),
    (answer.AnswerOrReport, "critique", lambda: settled(NEW_GOLF, request="critique"), True, "REPORT", "critique"),
    (answer.AnswerOrReport, "correction, nothing changed", lambda: settled(NEW_GOLF, request="correction",
     case_changed=False), True, "ANSWER_FROM_CONTEXT", "correction"),
    (answer.AnswerOrReport, "constraint not met", lambda: settled(NEW_GOLF, feasibility_pending=True), True,
     "FEASIBILITY", "constraint"),
    (answer.AnswerOrReport, "weights change past a constraint", lambda: settled(NEW_GOLF, request="weights_change",
     feasibility_pending=True), True, "ANSWER_FROM_CONTEXT", "follow-up"),
    (answer.AnswerOrReport, "follow-up", lambda: settled(NEW_GOLF, request="follow_up_question"), True,
     "ANSWER_FROM_CONTEXT", "follow-up"),
    (answer.AnswerOrReport, "unchanged since the report", lambda: unchanged(settled(NEW_GOLF)), True,
     "ANSWER_FROM_CONTEXT", "unchanged"),
    (answer.AnswerOrReport, "case changed", lambda: settled(NEW_GOLF), True, "REPORT", "case changed"),
]  # fmt: skip


@pytest.mark.parametrize(("rule", "label", "build", "fired", "kind", "why"), TABLE,
                         ids=[f"{r.name}: {label}" for r, label, *_ in TABLE])  # fmt: skip
def test_rule_branch(rule, label, build, fired, kind, why):
    out = rule().check(build(), config())
    assert out.rule == rule.name and out.fired is fired
    assert (out.action.kind if out.action else None) == kind
    assert why in out.why


def test_every_rule_has_a_fired_and_a_skipped_row():
    rows = {(r, fired) for r, _, _, fired, _, _ in TABLE}
    for rule in RULES:
        assert (type(rule), True) in rows, rule.name
        assert (type(rule), False) in rows or isinstance(rule, answer.AnswerOrReport), rule.name


def test_rule_names_are_unique_and_stable():
    assert [r.name for r in RULES] == [
        "pass_limit", "report_after_timeout", "panel_edit", "candidates", "general_answer", "intake_step",
        "missing_essentials", "intake_card", "variants", "stale_data", "answer_or_report",
    ]  # fmt: skip


def test_a_car_without_facts_is_an_input_error():
    from automind.chat.dialog.policy import PolicyInputError

    s = settled(NEW_GOLF).model_copy(update={"cars": ()})
    with pytest.raises(PolicyInputError) as e:
        research.StaleData().check(s, config())
    assert e.value.field == "cars"


def test_a_settled_car_without_identification_is_kept_for_the_old_rules():
    car = CaseCar(key="car#1", request_text="Golf", make="VW", model="Golf")
    s = situation(CaseFile(cars=[car]), "compare", {})
    assert intake.IntakeStep().check(s, config()).fired is False
