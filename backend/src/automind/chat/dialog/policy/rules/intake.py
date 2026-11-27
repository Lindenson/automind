"""Stage INTAKE: essentials first — the intake step about the identity of the cars (spec 005), then the other
questions that change the result (≤ 3, persona only alongside another question)."""

from __future__ import annotations

from typing import ClassVar

from automind.chat.dialog.policy.contracts import MAX_QUESTIONS, RuleOutcome, Situation, Stage, fire, skip
from automind.chat.domain import intake
from automind.chat.domain.case import MAX_CARS, CaseFile, QuestionKind
from automind.chat.domain.decision import Action, PolicyConfig
from automind.chat.domain.identification.identification import REASK
from automind.chat.domain.identification.tactic import NOT_FOUND

QUESTION_ORDER: tuple[QuestionKind, ...] = (
    "TOO_MANY_CARS", "CAR_IDENTITY", "MAKE_LINEUP", "UNKNOWN_MODEL", "FUEL", "ENGINE", "POWER", "CONDITION",
    "USED_AGE", "TRIM", "GEARBOX", "DRIVE", "BUDGET_INTENT", "PERSONA",
)  # fmt: skip
# spec 005: intake item -> question kind (the outcome of the identify step decides between two kinds for MODEL)
ITEM_KIND: dict[str, QuestionKind] = {"MAKE": "CAR_IDENTITY", "ENGINE": "ENGINE", "YEAR": "USED_AGE",
                                      "MILEAGE": "USED_AGE", "CONDITION": "CONDITION", "CHOICE": "TRIM",
                                      "TRIM": "TRIM", "GEARBOX": "GEARBOX", "FUEL": "FUEL", "POWER": "POWER",
                                      "DRIVE": "DRIVE"}  # fmt: skip
# the intake steps that end the questions about one car: the question named after the step
END_OF_ATTEMPTS: dict[intake.StepKind, QuestionKind] = {
    intake.StepKind.PROPOSE: "PROPOSE", intake.StepKind.REMOVE_OR_CHOOSE: "REMOVE_OR_CHOOSE",
}  # fmt: skip


class IntakeStep:
    """Questions about the identity of the cars: bounded attempts, then a proposal, then "remove or choose for me".
    Cars without an identify outcome (cases before spec 005) are left to `MissingEssentials`."""

    name: ClassVar[str] = "intake_step"
    stage: ClassVar[Stage] = Stage.INTAKE
    requirement: ClassVar[str | None] = "spec 005 R6"

    def check(self, s: Situation, cfg: PolicyConfig) -> RuleOutcome:
        case = s.case
        if len(case.cars) > MAX_CARS:
            return skip(self, "too many cars: which to compare is asked first")
        if not any(c.identify is not None for c in case.cars):
            return skip(self, "no car went through identification")
        step = intake.next_step(case, cfg.intake)
        if (question := END_OF_ATTEMPTS.get(step.kind)) is not None:
            return fire(self, Action.ask([question], [step.car_key or ""], "intake: " + question))
        if step.kind is not intake.StepKind.ASK:
            return skip(self, f"intake step {step.kind}: nothing to ask")
        questions, cars = _identity_questions(case, step)
        return fire(self, Action.ask(questions, cars, "intake: identity not settled"))


class MissingEssentials:
    """Information that changes the result is missing: ask (≤ 3 questions)."""

    name: ClassVar[str] = "missing_essentials"
    stage: ClassVar[Stage] = Stage.INTAKE
    requirement: ClassVar[str | None] = "spec 004 FR-005, FR-021, FR-031"

    def check(self, s: Situation, cfg: PolicyConfig) -> RuleOutcome:
        questions, concerned = questions_for(s)
        if not questions:
            return skip(self, "nothing essential missing")
        return fire(self, Action.ask(questions, concerned, "information that changes the result is missing"))


def questions_for(s: Situation) -> tuple[list[QuestionKind], list[str]]:
    """The essential questions still open (in `QUESTION_ORDER`, ≤ 3) and the cars they concern."""
    case = s.case
    needed: dict[QuestionKind, list[str]] = {}
    if len(case.cars) > MAX_CARS:
        needed["TOO_MANY_CARS"] = [c.key for c in case.cars]
    for c in case.cars:
        st = s.car(c.key)
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


def _identity_questions(case: CaseFile, step: intake.Step) -> tuple[list[QuestionKind], list[str]]:
    """The question kinds of an intake ASK step (≤ 3, in `QUESTION_ORDER`) and the cars they concern."""
    kinds: dict[QuestionKind, list[str]] = {}
    for it in step.items:
        car = case.car(it.car_key) if it.car_key else None
        if it.item == "MODEL":
            not_found = car is not None and car.identify is not None and car.identify.outcome == NOT_FOUND
            kind: QuestionKind = "UNKNOWN_MODEL" if not_found else "MAKE_LINEUP"
        else:
            kind = ITEM_KIND.get(it.item, "CAR_IDENTITY")
        kinds.setdefault(kind, []).extend([it.car_key] if it.car_key else [c.key for c in case.cars])
    ordered = [q for q in QUESTION_ORDER if q in kinds][:MAX_QUESTIONS]
    return ordered, sorted({k for q in ordered for k in kinds[q]})
