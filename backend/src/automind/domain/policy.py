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

from .casefile import MAX_CARS, CaseFile, QuestionKind

ActionKind = Literal[
    "ANSWER_GENERAL",
    "ASK",
    "CONFIRM_VARIANTS",
    "CONFIRM_COST",
    "RESEARCH",
    "ANSWER_FROM_CONTEXT",
    "REPORT",
    "FEASIBILITY",
]
RequestKind = Literal[
    "compare",
    "single",
    "follow_up_question",
    "weights_change",
    "correction",
    "general_question",
    "confirm_yes",
    "confirm_no",
    "chitchat",
]
QUESTION_ORDER: tuple[QuestionKind, ...] = (
    "TOO_MANY_CARS", "CAR_IDENTITY", "USED_AGE", "TRIM", "BUDGET_INTENT", "PERSONA",
)  # fmt: skip
MAX_QUESTIONS = 3
DEFAULT_CONFIRM_THRESHOLD_EUR = 0.30
DEFAULT_HARD_CAP_EUR = 1.00


class CarState(BaseModel):
    """What code knows about a case car before deciding (catalog lookup + cache freshness)."""

    identity_known: bool = True  # make and model are known
    in_catalog: bool = False
    ambiguous: bool = False  # more than one catalog variant fits
    plausible_generations: int = 0  # generations that fit condition/year (0 = unknown)
    data_fresh: bool = False  # all areas needed by the current criteria are cached and fresh


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
) -> Action:
    # 1. general
    if request in ("general_question", "chitchat") or not case.cars:
        return Action(kind="ANSWER_GENERAL", reason="general question or no cars in the case")
    state = {c.key: cars.get(c.key, CarState()) for c in case.cars}
    # 2. essentials
    questions, concerned = _questions(case, state)
    if questions:
        return Action(
            kind="ASK", questions=questions, cars=concerned, reason="information that changes the result is missing"
        )
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
    single = len(case.cars) == 1
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


def _questions(case: CaseFile, state: dict[str, CarState]) -> tuple[list[QuestionKind], list[str]]:
    needed: dict[QuestionKind, list[str]] = {}
    if len(case.cars) > MAX_CARS:
        needed["TOO_MANY_CARS"] = [c.key for c in case.cars]
    for c in case.cars:
        st = state[c.key]
        if not st.identity_known:
            needed.setdefault("CAR_IDENTITY", []).append(c.key)
        elif c.condition == "USED" and c.year is None and st.plausible_generations != 1:
            needed.setdefault("USED_AGE", []).append(c.key)
        if case.budget.max_eur and case.budget.intent == "UNKNOWN" and c.condition == "UNKNOWN":
            needed.setdefault("BUDGET_INTENT", []).append(c.key)  # new or used changes the answer (FR-021)
    blocking = [q for q in QUESTION_ORDER if q in needed and q not in case.asked]
    if blocking and case.persona == "UNKNOWN" and "PERSONA" not in case.asked:
        blocking.append("PERSONA")  # FR-005a: only alongside another question, never a questionnaire
    blocking = blocking[:MAX_QUESTIONS]
    concerned = sorted({k for q in blocking for k in needed.get(q, [])})
    return blocking, concerned


def _needs_confirmation(case: CaseFile, key: str, st: CarState) -> bool:
    car = case.car(key)
    if car.resolution in ("CONFIRMED", "AUTO_OK"):
        return False
    return st.ambiguous or car.condition == "USED" or not st.in_catalog


def fingerprint(case: CaseFile) -> str:
    """Hash of everything a report depends on (FR-004): cars, criteria, weights, persona, settings."""
    payload = {
        "persona": case.persona,
        "cars": [[c.variant_id, c.condition, c.year, c.mileage_km] for c in case.cars],
        "priorities": sorted((p.criterion, p.strength) for p in case.priorities),
        "weights": sorted((k, round(v, 2)) for k, v in case.weights.items()),
        "usage": sorted(case.usage),
        "budget": [case.budget.max_eur, case.budget.intent, case.budget.currency, case.budget.kind],
        "running": case.running_cost_limit.model_dump() if case.running_cost_limit else None,
        "needs": case.needs.model_dump(),
        "annual_km": case.annual_km,
        "rates": case.rates_override.model_dump(exclude_none=True),
        "race": case.race_settings.model_dump() if case.race_settings else None,
        "prediction": case.prediction.winner_key if case.prediction else None,
        "profile_age": case.profile.age,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()[:32]
