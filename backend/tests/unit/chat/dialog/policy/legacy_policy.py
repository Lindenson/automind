"""Spec 015 T205: the action policy as it was before PL1 (main 422c89a: policy/contracts.py, rules/*.py, chain.py),
frozen as one module so the regression test can compare it with the new `decide` on random situations. Removed at
PL5, the first step that changes what the policy decides. Never edit the logic below."""

# ruff: noqa
# fmt: off
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from automind.chat.domain import intake
from automind.chat.domain.case import MAX_CARS, CaseFile, QuestionKind
from automind.chat.domain.decision import Action, CarState, RequestKind
from automind.chat.domain.fingerprint import fingerprint
from automind.chat.domain.identification.identification import REASK


# --- contracts.py ---




MAX_QUESTIONS = 3
MAX_HOPS = 8  # spec 007 FR-027: policy passes in one turn before the turn ends with what it has
DEFAULT_CONFIRM_THRESHOLD_EUR = 0.30
DEFAULT_HARD_CAP_EUR = 1.00


@dataclass(frozen=True)
class Situation:
    """Everything the policy may look at in one pass of a turn."""

    case: CaseFile
    request: RequestKind
    cars: dict[str, CarState]
    cost_estimate_eur: float | None
    last_fingerprint: str | None
    cost_approved: bool = False
    research_declined: bool = False
    case_changed: bool = True
    feasibility_pending: bool = False
    confirm_threshold_eur: float = DEFAULT_CONFIRM_THRESHOLD_EUR
    hard_cap_eur: float = DEFAULT_HARD_CAP_EUR
    intake_limits: intake.Limits | None = None
    hops: int = 0
    max_hops: int = MAX_HOPS
    state: dict[str, CarState] = field(init=False)

    def __post_init__(self) -> None:
        # every car of the case has a state (an unknown car: nothing known yet)
        object.__setattr__(self, "state", {c.key: self.cars.get(c.key, CarState()) for c in self.case.cars})


class Rule(Protocol):
    def __call__(self, s: Situation) -> Action | None: ...


class Policy(Protocol):
    def decide(self, s: Situation) -> Action: ...


# --- rules/limits.py ---




def hop_limit(s: Situation) -> Action | None:
    """FR-027: a turn that went round too often ends with a partial answer from what it has."""
    if s.hops < s.max_hops:
        return None
    if any(c.variant_id for c in s.case.cars):
        return Action(kind="REPORT", reason="hop limit: a report from the data at hand")
    return Action(kind="ANSWER_GENERAL", reason="hop limit: a plain answer")


def report_after_timeout(s: Situation) -> Action | None:
    """FR-029: after a timeout, the report from the saved data (never research or questions again)."""
    if s.request == "report_saved" and any(c.variant_id for c in s.case.cars):
        return Action(kind="REPORT", reason="turn timeout: report from the saved data")
    return None


def panel_edit(s: Situation) -> Action | None:
    """FR-012, FR-013: a panel edit recomputes from the validated data. It never researches, asks or confirms: when
    it needs new data, the next message decides."""
    if not (s.request == "rescore" and s.case.cars):
        return None
    if s.last_fingerprint is None:
        return Action(kind="REPORT", reason="no report yet: a full report")
    now = fingerprint(s.case)
    if now == s.last_fingerprint:
        return Action(kind="ANSWER_FROM_CONTEXT", nothing_new=True, reason="nothing_new")
    if ":" in s.last_fingerprint and now.split(":")[0] != s.last_fingerprint.split(":")[0]:
        return Action(kind="REPORT", reason="data_changed")  # other cars: a full report on what is cached
    return Action(kind="RESCORE", reason="params_changed")


# --- rules/py ---




def candidates(s: Situation) -> Action | None:
    """1. spec 007 US7: no car but a need and a budget → candidates, not a general text."""
    if s.request not in ("general_question", "chitchat") and wants_candidates(s.case):
        return Action(kind="SELECT_CANDIDATES", reason="no car named: a need and a budget")
    return None


def general_answer(s: Situation) -> Action | None:
    """1. A general question, chitchat, or a case without cars."""
    if s.request in ("general_question", "chitchat") or not s.case.cars:
        return Action(kind="ANSWER_GENERAL", reason="general question or no cars in the case")
    return None


def wants_candidates(case: CaseFile) -> bool:
    """No car named, a budget, and a class or a need (a body, a family, passengers, a usage); or a make to choose
    from with no candidate of it proposed yet (009 FR-022: "find me a Kia to replace my Prado")."""
    if case.wanted_make:
        make = case.wanted_make.lower()
        proposed = any(str(x.get("make") or "").lower() == make for x in case.candidates)
        named = any((c.make or "").lower() == make and not c.replaced for c in case.cars)
        if not (proposed or named):
            return True
    if any(not c.replaced for c in case.cars) or not case.budget.max_eur:
        return False
    need = (case.wanted_body is not None or case.profile.family == "FAMILY" or "FAMILY" in case.usage
            or (case.needs.passengers or 0) >= 4)  # fmt: skip
    return need


# --- rules/intake.py ---



QUESTION_ORDER: tuple[QuestionKind, ...] = (
    "TOO_MANY_CARS", "CAR_IDENTITY", "MAKE_LINEUP", "UNKNOWN_MODEL", "FUEL", "ENGINE", "POWER", "CONDITION",
    "USED_AGE", "TRIM", "GEARBOX", "DRIVE", "BUDGET_INTENT", "PERSONA",
)  # fmt: skip
# spec 005: intake item -> question kind (the outcome of the identify step decides between two kinds for MODEL)
ITEM_KIND: dict[str, QuestionKind] = {"MAKE": "CAR_IDENTITY", "ENGINE": "ENGINE", "YEAR": "USED_AGE",
                                      "MILEAGE": "USED_AGE", "CONDITION": "CONDITION", "CHOICE": "TRIM",
                                      "TRIM": "TRIM", "GEARBOX": "GEARBOX", "FUEL": "FUEL", "POWER": "POWER",
                                      "DRIVE": "DRIVE"}  # fmt: skip


def intake_step(s: Situation) -> Action | None:
    """Questions about the identity of the cars (spec 005 R6): bounded attempts, then a proposal, then
    "remove or choose for me". Cars without an identify outcome (cases before 005) use the rules below."""
    case = s.case
    limits = s.intake_limits or intake.Limits(full_intake=False)
    if len(case.cars) > MAX_CARS or not any(c.identify is not None for c in case.cars):
        return None  # which 3 to compare is asked first; cases before 005 use the rules below
    step = intake.next_step(case, limits)
    if step.kind in ("PROPOSE", "REMOVE_OR_CHOOSE"):
        return Action(kind="ASK", questions=[step.kind], cars=[step.car_key or ""], reason="intake: " + step.kind)
    if step.kind != "ASK":
        return None
    kinds: dict[QuestionKind, list[str]] = {}
    for it in step.items:
        car = case.car(it.car_key) if it.car_key else None
        if it.item == "MODEL":
            kind: QuestionKind = (
                "UNKNOWN_MODEL" if car and car.identify and car.identify.outcome == "NOT_FOUND" else "MAKE_LINEUP"
            )
        else:
            kind = ITEM_KIND.get(it.item, "CAR_IDENTITY")
        kinds.setdefault(kind, []).extend([it.car_key] if it.car_key else [c.key for c in case.cars])
    ordered = [q for q in QUESTION_ORDER if q in kinds][:MAX_QUESTIONS]
    cars = sorted({k for q in ordered for k in kinds[q]})
    return Action(kind="ASK", questions=ordered, cars=cars, reason="intake: identity not settled")


def missing_essentials(s: Situation) -> Action | None:
    """Information that changes the result is missing: ask (≤ 3 questions)."""
    questions, concerned = questions_for(s.case, s.state)
    if questions:
        return Action(
            kind="ASK", questions=questions, cars=concerned, reason="information that changes the result is missing"
        )
    return None


def questions_for(case: CaseFile, state: dict[str, CarState]) -> tuple[list[QuestionKind], list[str]]:
    needed: dict[QuestionKind, list[str]] = {}
    if len(case.cars) > MAX_CARS:
        needed["TOO_MANY_CARS"] = [c.key for c in case.cars]
    for c in case.cars:
        st = state[c.key]
        if not st.identity_known:
            needed.setdefault("CAR_IDENTITY", []).append(c.key)
        elif c.resolution == "UNKNOWN_MODEL":
            needed.setdefault("UNKNOWN_MODEL", []).append(c.key)
        elif st.gearbox_mixed and not c.constraints.gearbox_hint:
            needed.setdefault("GEARBOX", []).append(c.key)
        elif c.condition == "USED" and c.year is None and st.plausible_generations != 1:
            needed.setdefault("USED_AGE", []).append(c.key)
        if case.budget.max_eur and case.budget.intent == "UNKNOWN" and c.condition == "UNKNOWN":
            needed.setdefault("BUDGET_INTENT", []).append(c.key)  # new or used changes the answer (FR-021)
    # a car question is asked again until the car is settled (spec 004 FR-031); the others only once
    blocking = [q for q in QUESTION_ORDER if q in needed and (q in REASK or q not in case.asked)]
    if blocking and case.persona == "UNKNOWN" and "PERSONA" not in case.asked:
        blocking.append("PERSONA")  # FR-005a: only alongside another question, never a questionnaire
    blocking = blocking[:MAX_QUESTIONS]
    concerned = sorted({k for q in blocking for k in needed.get(q, [])})
    return blocking, concerned


# --- rules/py ---




def intake_card(s: Situation) -> Action | None:
    """The confirmation card (spec 005 R7): when a proposed version waits for the user, or research is about to start
    after an intake with questions or above the cost threshold. Simple unambiguous cached comparisons skip it."""
    case, est = s.case, s.cost_estimate_eur
    if case.intake.card_confirmed or not case.cars or not any(c.identify is not None for c in case.cars):
        return None
    if not all(c.variant_id for c in case.cars):
        return None
    proposed = any(c.resolution == "PROPOSED" for c in case.cars)
    stale = any(not s.state[c.key].data_fresh for c in case.cars)
    asked = bool(case.intake.last_questions)
    chosen_by_us = bool(case.candidates)  # spec 007 US7: candidates the user did not name are always confirmed
    if (
        proposed
        or chosen_by_us
        or (stale and not s.research_declined and (asked or (est or 0.0) >= s.confirm_threshold_eur))
    ):
        return Action(kind="CONFIRM_INTAKE", cars=[c.key for c in case.cars], over_cap=(est or 0.0) > s.hard_cap_eur,
                      reason="confirm the cars, the profile and the research")  # fmt: skip
    return None


def variants(s: Situation) -> Action | None:
    """Variants to confirm: ambiguous, used or new to the catalogue."""
    to_confirm = [c.key for c in s.case.cars if needs_confirmation(s.case, c.key, s.state[c.key])]
    if to_confirm:
        return Action(kind="CONFIRM_VARIANTS", cars=to_confirm, reason="ambiguous, used or new-to-catalog variant")
    return None


def needs_confirmation(case: CaseFile, key: str, st: CarState) -> bool:
    car = case.car(key)
    if car.resolution in ("CONFIRMED", "AUTO_OK"):
        return False
    if car.resolution == "UNKNOWN_MODEL":
        return False  # asked as a question, never proposed
    if car.resolution == "PROPOSED":
        return True  # a proposed variant (catalog or resolver) is confirmed by the user, never silently (spec 005)
    return st.ambiguous or car.condition == "USED" or not st.in_catalog


# --- rules/py ---




def stale_data(s: Situation) -> Action | None:
    stale = [c.key for c in s.case.cars if not s.state[c.key].data_fresh]
    if not stale or s.research_declined:
        return None
    est = s.cost_estimate_eur or 0.0
    if est >= s.confirm_threshold_eur and not s.cost_approved:
        return Action(kind="CONFIRM_COST", cars=stale, over_cap=est > s.hard_cap_eur, reason=f"estimated €{est:.2f}")
    return Action(kind="RESEARCH", cars=stale, reason="data stale or missing for the current criteria")


# --- rules/py ---




def answer_or_report(s: Situation) -> Action:
    case, request = s.case, s.request
    single = len(case.cars) == 1
    # 4b. "find the missing data and update the report": after the research, always a fresh report
    if request == "research_more":
        return Action(kind="REPORT", profile=single, reason="the user asked to research more and update the report")
    # 4c. critique never gets only an apology (spec 004 FR-021): the gaps were researched above, or the report
    # is reworked with what the user disliked
    if request == "critique":
        return Action(kind="REPORT", profile=single, reason="critique: rework the report")
    # 5. answer from context (a correction that changes nothing is answered, not re-reported)
    if request == "correction" and not s.case_changed:
        return Action(
            kind="ANSWER_FROM_CONTEXT", nothing_new=True, profile=single, reason="correction matches the case"
        )
    # 5b. the request does not fit the user's budget or needs: say so before any report (spec 003 FR-020)
    if s.feasibility_pending and request not in ("weights_change",):
        return Action(kind="FEASIBILITY", reason="a constraint is not met or could not be checked")
    if request in ("weights_change", "follow_up_question"):
        return Action(kind="ANSWER_FROM_CONTEXT", profile=single, reason="follow-up answered from validated data")
    # 6. report, never repeated unchanged
    if s.last_fingerprint is not None and fingerprint(case) == s.last_fingerprint:
        return Action(
            kind="ANSWER_FROM_CONTEXT", nothing_new=True, profile=single, reason="case unchanged since last report"
        )
    return Action(kind="REPORT", profile=single, reason="case changed")


# --- chain.py ---



RULES: tuple[Rule, ...] = (
    hop_limit,
    report_after_timeout,
    panel_edit,
    candidates,
    general_answer,
    intake_step,
    missing_essentials,
    intake_card,
    variants,
    stale_data,
)


class RulesInOrder:
    """The policy: the first rule that applies decides; otherwise answer or report."""

    def decide(self, s: Situation) -> Action:
        for rule in RULES:
            if (action := rule(s)) is not None:
                return action
        return answer_or_report(s)


def decide(
    case: CaseFile,
    request: RequestKind,
    cars: dict[str, CarState],
    *,
    cost_estimate_eur: float | None,
    last_fingerprint: str | None,
    cost_approved: bool = False,
    research_declined: bool = False,
    case_changed: bool = True,
    feasibility_pending: bool = False,
    confirm_threshold_eur: float = DEFAULT_CONFIRM_THRESHOLD_EUR,
    hard_cap_eur: float = DEFAULT_HARD_CAP_EUR,
    intake_limits: intake.Limits | None = None,
    hops: int = 0,
    max_hops: int = MAX_HOPS,
) -> Action:
    """The decision of one pass, for callers that hold the facts as arguments."""
    return RulesInOrder().decide(Situation(
        case=case, request=request, cars=cars, cost_estimate_eur=cost_estimate_eur, last_fingerprint=last_fingerprint,
        cost_approved=cost_approved, research_declined=research_declined, case_changed=case_changed,
        feasibility_pending=feasibility_pending, confirm_threshold_eur=confirm_threshold_eur, hard_cap_eur=hard_cap_eur,
        intake_limits=intake_limits, hops=hops, max_hops=max_hops,
    ))  # fmt: skip
