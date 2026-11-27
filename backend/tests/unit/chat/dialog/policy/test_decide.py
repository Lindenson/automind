"""Spec 015 T203, T204: `decide` — rule order, errors, properties on random situations, the routes table, and a
termination simulator that plays the policy's passes of one turn."""

from __future__ import annotations

import sys
from typing import Any, get_args

import pytest
from hypothesis import HealthCheck, given, settings

from automind.chat.dialog import graph
from automind.chat.dialog.policy import (
    ROUTES,
    RULES,
    Continuation,
    PolicyBug,
    Situation,
    decide,
    policy_targets,
)
from automind.chat.dialog.policy.contracts import RuleOutcome, skip
from automind.chat.domain.case import CaseFile
from automind.chat.domain.decision import ActionKind, PolicyConfig

from .builder import MAX_PASSES, config, situation
from .strategies import old_arguments
from .test_policy import NEW_GOLF, NEW_I30, case, ready

decide_module = sys.modules["automind.chat.dialog.policy.decide"]  # the package re-exports the function by its name
PROPERTY = settings(max_examples=300, derandomize=True, deadline=None, database=None,
                    suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large])  # fmt: skip


def _situation(args: dict[str, Any]) -> Situation:
    return situation(args["case"], args["request"], args["cars"], cost_estimate_eur=args["cost_estimate_eur"],
                     last_fingerprint=args["last_fingerprint"], cost_approved=args["cost_approved"],
                     research_declined=args["research_declined"], case_changed=args["case_changed"],
                     feasibility_pending=args["feasibility_pending"], pass_no=args["hops"] + 1)  # fmt: skip


def _config(args: dict[str, Any]) -> PolicyConfig:
    return config(limits=args["intake_limits"])


# --- order and errors ----------------------------------------------------------------------------------------------


def test_the_earlier_rule_wins_when_two_apply():
    c = case(NEW_GOLF)  # a general question (general_answer) on the limit pass (pass_limit): the limit wins
    d = decide(situation(c, "general_question", ready(c), pass_no=MAX_PASSES + 1), config())
    assert d.decided_by == "pass_limit"
    d = decide(situation(c, "general_question", ready(c)), config())
    assert d.decided_by == "general_answer" and [o.rule for o in d.trail][:3] == [
        "pass_limit", "report_after_timeout", "panel_edit"]  # fmt: skip


def test_the_trail_holds_every_rule_asked_up_to_the_decision():
    c = case(NEW_GOLF, NEW_I30, persona="BUYER")
    d = decide(situation(c, "compare", ready(c)), config())
    assert d.decided_by == "answer_or_report"
    assert [o.rule for o in d.trail] == [r.name for r in RULES]
    assert all(not o.fired for o in d.trail[:-1]) and d.trail[-1].fired


def test_a_pass_beyond_the_limit_pass_is_a_bug():
    with pytest.raises(PolicyBug):
        decide(situation(case(NEW_GOLF), pass_no=MAX_PASSES + 2), config())


def test_no_rule_firing_is_a_bug(monkeypatch):
    class Never:
        name, stage, requirement = "never", None, None

        def check(self, s: Situation, cfg: PolicyConfig) -> RuleOutcome:
            return skip(self, "never")  # type: ignore[arg-type]

    monkeypatch.setattr(decide_module, "RULES", (Never(),))
    with pytest.raises(PolicyBug):
        decide(situation(case(NEW_GOLF)), config())


def test_an_exception_inside_a_rule_propagates(monkeypatch):
    class Broken:
        name, stage, requirement = "broken", None, None

        def check(self, s: Situation, cfg: PolicyConfig) -> RuleOutcome:
            raise ZeroDivisionError("a bug in a rule")

    monkeypatch.setattr(decide_module, "RULES", (Broken(), *RULES))
    with pytest.raises(ZeroDivisionError):
        decide(situation(case(NEW_GOLF)), config())


def test_the_config_refuses_a_cap_below_the_threshold():
    with pytest.raises(ValueError, match="below the confirmation threshold"):
        config(threshold=1.0, cap=0.5)


# --- properties ----------------------------------------------------------------------------------------------------


@PROPERTY
@given(old_arguments())
def test_decide_always_decides_and_explains(args):
    d = decide(_situation(args), _config(args))
    assert d.trail and d.trail[-1].rule == d.decided_by and d.trail[-1].fired
    assert d.trail[-1].action == d.action


@PROPERTY
@given(old_arguments())
def test_the_limit_pass_ends_the_turn(args):
    args["hops"] = MAX_PASSES
    d = decide(_situation(args), _config(args))
    assert ROUTES[d.action.kind].continuation is Continuation.END


# --- routes --------------------------------------------------------------------------------------------------------


def test_every_action_kind_has_a_route():
    assert set(ROUTES) == set(get_args(ActionKind))


def test_every_route_leads_to_a_node_of_the_graph():
    nodes = set(graph.build_graph().get_graph().nodes)
    assert {r.node for r in ROUTES.values()} <= nodes
    assert set(policy_targets()) == {r.node for r in ROUTES.values()}


# --- termination ---------------------------------------------------------------------------------------------------


def _after(s: Situation, kind: ActionKind) -> Situation:
    """The effect of a LOOP action before the next pass: research makes the data fresh (and is done this turn);
    candidates become the case's cars, settled and to confirm."""
    if kind == "RESEARCH":
        cars = tuple(f.model_copy(update={"data_fresh": True}) for f in s.cars)
        return s.model_copy(update={"cars": cars, "research_declined": True, "pass_no": s.pass_no + 1})
    c = case(NEW_GOLF, persona="BUYER")
    c.candidates = [{"make": "Volkswagen", "model": "Golf"}]
    return situation(c, s.request, ready(c), pass_no=s.pass_no + 1)


def _passes(s: Situation, cfg: PolicyConfig) -> int:
    """Policy passes until an action ends the turn (END) or waits for the person (SUSPEND)."""
    while True:
        kind = decide(s, cfg).action.kind
        if ROUTES[kind].continuation is not Continuation.LOOP:
            return s.pass_no
        s = _after(s, kind)


@PROPERTY
@given(old_arguments())
def test_every_turn_ends_within_the_limit_pass(args):
    assert _passes(_situation(args), _config(args)) <= MAX_PASSES + 1


def _stale(c: CaseFile) -> Situation:
    states = {k: v.model_copy(update={"data_fresh": False}) for k, v in ready(c).items()}
    return situation(c, "compare", states)


CATALOGUE = {
    "stale data, cheap": lambda: _stale(case(NEW_GOLF, persona="BUYER")),
    "fresh data": lambda: situation(c := case(NEW_GOLF, persona="BUYER"), "compare", ready(c)),
    "a need and a budget": lambda: situation(CaseFile(wanted_make="Kia")),
    "a general question": lambda: situation(CaseFile(), "general_question"),
}


@pytest.mark.parametrize("name", list(CATALOGUE))
def test_typical_turns_end_within_four_passes(name):
    assert _passes(CATALOGUE[name](), config()) <= 4
