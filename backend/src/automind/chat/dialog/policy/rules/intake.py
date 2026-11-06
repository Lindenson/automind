"""2. Essentials first: the intake step about the identity of the cars (spec 005), then the other questions that
change the result (≤ 3, persona only alongside another question)."""

from __future__ import annotations

from automind.chat.dialog.policy.contracts import MAX_QUESTIONS, Situation
from automind.chat.domain import intake
from automind.chat.domain.case import MAX_CARS, CaseFile, QuestionKind
from automind.chat.domain.decision import Action, CarState
from automind.chat.domain.identification.identification import REASK

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
