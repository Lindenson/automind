"""Deterministic action policy (research R5). One rule per requirement; the LLM never chooses the action.

Rules, in order:
1. general question / chitchat → ANSWER_GENERAL
2. missing essentials → ASK (≤3 questions, one round; persona only alongside another question)
3. ambiguous, used or uncatalogued variants not yet confirmed → CONFIRM_VARIANTS
4. data stale or missing → CONFIRM_COST if the estimate ≥ threshold, else RESEARCH
5. weights change / follow-up with data present → ANSWER_FROM_CONTEXT
6. otherwise REPORT, unless the fingerprint equals the last report → ANSWER_FROM_CONTEXT "nothing new"
"""

from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, Field

from automind.chat.domain.case import MAX_CARS, CaseFile, QuestionKind
from automind.chat.domain.identification.identification import REASK
from automind.chat.domain.intake import intake

ActionKind = Literal[
    "RESCORE",  # spec 007: recompute scores, cost and verdict from the data already validated
    "ANSWER_GENERAL",
    "ASK",
    "CONFIRM_VARIANTS",
    "CONFIRM_COST",
    "RESEARCH",
    "ANSWER_FROM_CONTEXT",
    "REPORT",
    "FEASIBILITY",
    "CONFIRM_INTAKE",
    "SELECT_CANDIDATES",  # spec 007 US7: no car named, but a need and a budget: propose 2–3 cars
]
RequestKind = Literal[
    "compare",
    "single",
    "follow_up_question",
    "weights_change",
    "correction",
    "research_more",
    "general_question",
    "confirm_yes",
    "confirm_no",
    "choose_for_me",
    "critique",
    "chitchat",
    "rescore",  # spec 007 FR-013: an edit in the case panel; set by code (preset), never by the interpreter
    "report_saved",  # spec 007 FR-029: after a turn timeout, the report from the data already saved (code only)
]
QUESTION_ORDER: tuple[QuestionKind, ...] = (
    "TOO_MANY_CARS", "CAR_IDENTITY", "MAKE_LINEUP", "UNKNOWN_MODEL", "FUEL", "ENGINE", "POWER", "CONDITION",
    "USED_AGE", "TRIM", "GEARBOX", "DRIVE", "BUDGET_INTENT", "PERSONA",
)  # fmt: skip
# spec 005: intake item -> question kind (the outcome of the identify step decides between two kinds for MODEL)
_ITEM_KIND: dict[str, QuestionKind] = {"MAKE": "CAR_IDENTITY", "ENGINE": "ENGINE", "YEAR": "USED_AGE",
                                       "MILEAGE": "USED_AGE", "CONDITION": "CONDITION", "CHOICE": "TRIM",
                                       "TRIM": "TRIM", "GEARBOX": "GEARBOX", "FUEL": "FUEL", "POWER": "POWER",
                                       "DRIVE": "DRIVE"}  # fmt: skip
MAX_QUESTIONS = 3
MAX_HOPS = 8  # spec 007 FR-027: policy passes in one turn before the turn ends with what it has
DEFAULT_CONFIRM_THRESHOLD_EUR = 0.30
DEFAULT_HARD_CAP_EUR = 1.00


class CarState(BaseModel):
    """What code knows about a case car before deciding (catalog lookup + cache freshness)."""

    identity_known: bool = True  # make and model are known
    in_catalog: bool = False
    ambiguous: bool = False  # more than one catalog variant fits
    plausible_generations: int = 0  # generations that fit condition/year (0 = unknown)
    data_fresh: bool = False  # all areas needed by the current criteria are cached and fresh
    gearbox_mixed: bool = False  # accepted values of several gearboxes for one variant (spec 004 FR-028)


class Action(BaseModel):
    kind: ActionKind
    questions: list[QuestionKind] = Field(default_factory=list)
    cars: list[str] = Field(default_factory=list)  # car keys the action concerns
    nothing_new: bool = False
    profile: bool = False  # single-car profile report (FR-012)
    over_cap: bool = False  # estimate exceeds the hard cap: research will stop at the cap
    reason: str = ""


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
    early = _early(case, request, last_fingerprint, hops, max_hops)
    if early is not None:
        return early
    # 1. general; spec 007 US7: no car but a need and a budget → candidates, not a general text
    if request not in ("general_question", "chitchat") and wants_candidates(case):
        return Action(kind="SELECT_CANDIDATES", reason="no car named: a need and a budget")
    if request in ("general_question", "chitchat") or not case.cars:
        return Action(kind="ANSWER_GENERAL", reason="general question or no cars in the case")
    state = {c.key: cars.get(c.key, CarState()) for c in case.cars}
    # 2. essentials: the intake step first (spec 005), then the other questions
    step = _intake_step(case, intake_limits or intake.Limits(full_intake=False))
    if step is not None:
        return step
    questions, concerned = _questions(case, state)
    if questions:
        return Action(
            kind="ASK", questions=questions, cars=concerned, reason="information that changes the result is missing"
        )
    # 3a. spec 005: one card confirms the cars, the profile and the cost
    card = _card(case, state, cost_estimate_eur, research_declined, confirm_threshold_eur, hard_cap_eur)
    if card is not None:
        return card
    # 3. variants to confirm
    to_confirm = [c.key for c in case.cars if _needs_confirmation(case, c.key, state[c.key])]
    if to_confirm:
        return Action(kind="CONFIRM_VARIANTS", cars=to_confirm, reason="ambiguous, used or new-to-catalog variant")
    # 4. research
    stale = [c.key for c in case.cars if not state[c.key].data_fresh]
    if stale and not research_declined:
        est = cost_estimate_eur or 0.0
        if est >= confirm_threshold_eur and not cost_approved:
            return Action(kind="CONFIRM_COST", cars=stale, over_cap=est > hard_cap_eur, reason=f"estimated €{est:.2f}")
        return Action(kind="RESEARCH", cars=stale, reason="data stale or missing for the current criteria")
    return _answer_or_report(case, request, last_fingerprint, case_changed, feasibility_pending)


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


def _early(
    case: CaseFile, request: RequestKind, last_fingerprint: str | None, hops: int, max_hops: int
) -> Action | None:
    """Rules before everything else (spec 007)."""
    # FR-027: a turn that went round too often ends with a partial answer from what it has
    if hops >= max_hops:
        if any(c.variant_id for c in case.cars):
            return Action(kind="REPORT", reason="hop limit: a report from the data at hand")
        return Action(kind="ANSWER_GENERAL", reason="hop limit: a plain answer")
    # FR-029: after a timeout, the report from the saved data (never research or questions again)
    if request == "report_saved" and any(c.variant_id for c in case.cars):
        return Action(kind="REPORT", reason="turn timeout: report from the saved data")
    # FR-012, FR-013: a panel edit recomputes from the validated data. It never researches, asks or confirms: when
    # it needs new data, the next message decides.
    if request == "rescore" and case.cars:
        return _rescore(case, last_fingerprint)
    return None


def _rescore(case: CaseFile, last_fingerprint: str | None) -> Action:
    if last_fingerprint is None:
        return Action(kind="REPORT", reason="no report yet: a full report")
    now = fingerprint(case)
    if now == last_fingerprint:
        return Action(kind="ANSWER_FROM_CONTEXT", nothing_new=True, reason="nothing_new")
    if ":" in last_fingerprint and now.split(":")[0] != last_fingerprint.split(":")[0]:
        return Action(kind="REPORT", reason="data_changed")  # other cars: a full report on what is cached
    return Action(kind="RESCORE", reason="params_changed")


def _answer_or_report(
    case: CaseFile, request: RequestKind, last_fingerprint: str | None, case_changed: bool, feasibility_pending: bool
) -> Action:
    """Data is in place: answer from context, say the request does not fit, or write the report."""
    single = len(case.cars) == 1
    # 4b. "find the missing data and update the report": after the research, always a fresh report
    if request == "research_more":
        return Action(kind="REPORT", profile=single, reason="the user asked to research more and update the report")
    # 4c. critique never gets only an apology (spec 004 FR-021): the gaps were researched above, or the report
    # is reworked with what the user disliked
    if request == "critique":
        return Action(kind="REPORT", profile=single, reason="critique: rework the report")
    # 5. answer from context (a correction that changes nothing is answered, not re-reported)
    if request == "correction" and not case_changed:
        return Action(
            kind="ANSWER_FROM_CONTEXT", nothing_new=True, profile=single, reason="correction matches the case"
        )
    # 5b. the request does not fit the user's budget or needs: say so before any report (spec 003 FR-020)
    if feasibility_pending and request not in ("weights_change",):
        return Action(kind="FEASIBILITY", reason="a constraint is not met or could not be checked")
    if request in ("weights_change", "follow_up_question"):
        return Action(kind="ANSWER_FROM_CONTEXT", profile=single, reason="follow-up answered from validated data")
    # 6. report, never repeated unchanged
    if last_fingerprint is not None and fingerprint(case) == last_fingerprint:
        return Action(
            kind="ANSWER_FROM_CONTEXT", nothing_new=True, profile=single, reason="case unchanged since last report"
        )
    return Action(kind="REPORT", profile=single, reason="case changed")


def _card(case: CaseFile, state: dict[str, CarState], est: float | None, declined: bool, threshold: float,
          hard_cap: float) -> Action | None:  # fmt: skip
    """The confirmation card (spec 005 R7): when a proposed version waits for the user, or research is about to start
    after an intake with questions or above the cost threshold. Simple unambiguous cached comparisons skip it."""
    if case.intake.card_confirmed or not case.cars or not any(c.identify is not None for c in case.cars):
        return None
    if not all(c.variant_id for c in case.cars):
        return None
    proposed = any(c.resolution == "PROPOSED" for c in case.cars)
    stale = any(not state[c.key].data_fresh for c in case.cars)
    asked = bool(case.intake.last_questions)
    chosen_by_us = bool(case.candidates)  # spec 007 US7: candidates the user did not name are always confirmed
    if proposed or chosen_by_us or (stale and not declined and (asked or (est or 0.0) >= threshold)):
        return Action(kind="CONFIRM_INTAKE", cars=[c.key for c in case.cars], over_cap=(est or 0.0) > hard_cap,
                      reason="confirm the cars, the profile and the research")  # fmt: skip
    return None


def _intake_step(case: CaseFile, limits: intake.Limits) -> Action | None:
    """Questions about the identity of the cars (spec 005 R6): bounded attempts, then a proposal, then
    "remove or choose for me". Cars without an identify outcome (cases before 005) use the rules below."""
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
            kind = _ITEM_KIND.get(it.item, "CAR_IDENTITY")
        kinds.setdefault(kind, []).extend([it.car_key] if it.car_key else [c.key for c in case.cars])
    ordered = [q for q in QUESTION_ORDER if q in kinds][:MAX_QUESTIONS]
    cars = sorted({k for q in ordered for k in kinds[q]})
    return Action(kind="ASK", questions=ordered, cars=cars, reason="intake: identity not settled")


def _questions(case: CaseFile, state: dict[str, CarState]) -> tuple[list[QuestionKind], list[str]]:
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


def _needs_confirmation(case: CaseFile, key: str, st: CarState) -> bool:
    car = case.car(key)
    if car.resolution in ("CONFIRMED", "AUTO_OK"):
        return False
    if car.resolution == "UNKNOWN_MODEL":
        return False  # asked as a question, never proposed
    if car.resolution == "PROPOSED":
        return True  # a proposed variant (catalog or resolver) is confirmed by the user, never silently (spec 005)
    return st.ambiguous or car.condition == "USED" or not st.in_catalog


def _hash(payload: object) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()[:16]


def fingerprint_data(case: CaseFile) -> str:
    """What the data of a report depends on: the cars (spec 007 FR-012)."""
    return _hash({
        "cars": [[c.variant_id, c.condition, c.year, c.mileage_km] for c in case.cars],
        "race": case.race_settings.model_dump() if case.race_settings else None,
        "prediction": case.prediction.winner_key if case.prediction else None,
        "level": case.compare_level,
    })  # fmt: skip


def fingerprint_params(case: CaseFile) -> str:
    """What the assessment depends on: who the user is and what matters (spec 007 FR-012; before, family, style,
    region and the ownership period were missing, so a profile change looked like "nothing new")."""
    p = case.profile
    return _hash({
        "persona": case.persona,
        "profile": [p.age, p.family, p.age_band, p.driving_style, p.region, p.climate, p.annual_km_min,
                    p.annual_km_max] + ([p.home_charging] if p.home_charging != "UNKNOWN" else []),
        "ownership_years": case.ownership_years,
        "priorities": sorted((x.criterion, x.strength) for x in case.priorities),
        "weights": sorted((k, round(v, 2)) for k, v in case.weights.items()),
        "adjustments": sorted((k, round(v, 2)) for k, v in case.weight_adjustments.items()),
        "excluded": sorted(case.weights_excluded),
        "usage": sorted(case.usage),
        "budget": [case.budget.max_eur, case.budget.intent, case.budget.currency, case.budget.kind],
        "running": case.running_cost_limit.model_dump() if case.running_cost_limit else None,
        "needs": case.needs.model_dump(),
        "annual_km": case.annual_km,
        "rates": case.rates_override.model_dump(exclude_none=True),
    })  # fmt: skip


def fingerprint(case: CaseFile) -> str:
    """Hash of everything a report depends on (FR-004), in two parts "data:params" (spec 007 FR-012). A stored
    fingerprint from before spec 007 has no ":" and counts as different in both parts."""
    return f"{fingerprint_data(case)}:{fingerprint_params(case)}"
