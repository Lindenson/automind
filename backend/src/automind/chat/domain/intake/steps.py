"""The intake step machine (spec 005 R5, R6, R11, R12): what to ask next about the cars (ASK, PROPOSE,
REMOVE_OR_CHOOSE, CARD, NONE), progress of a reply, and the questions never repeated (FR-003). Pure."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

from automind.chat.domain.case import CaseCar, CaseFile, Choice, IdentifyKind, IntakeItem
from automind.shared.contracts.json import JsonObject

StepKind = Literal["ASK", "PROPOSE", "REMOVE_OR_CHOOSE", "CARD", "NONE"]


ALL = "*"  # attempts key for questions about every car (CONDITION)


MAX_ITEMS = 3


_RANK: dict[str | None, int] = {None: 0, "NEED": 1, "NOT_FOUND": 1, "CHOICES": 2, "IDENTIFIED": 3}


@dataclass(frozen=True)
class Limits:
    max_attempts_per_item: int = 2
    max_attempts_per_car: int = 4
    full_intake: bool = True  # ask new/used for every car and the year of used ones (US4)

    @classmethod
    def from_config(cls, section: JsonObject) -> Limits:
        """The limits of `search.yaml intake`; a key not given takes its default, `full_intake` is off."""
        return cls(
            max_attempts_per_item=int(section.get("max_attempts_per_item", 2)),
            max_attempts_per_car=int(section.get("max_attempts_per_car", 4)),
            full_intake=bool(section.get("full_intake", False)),
        )


@dataclass(frozen=True)
class StepItem:
    item: IntakeItem
    car_key: str | None  # None: a question about every car (CONDITION)
    rephrase: bool = False  # asked before: other words and concrete options
    choices: tuple[Choice, ...] = ()


@dataclass(frozen=True)
class Step:
    kind: StepKind
    items: tuple[StepItem, ...] = ()
    car_key: str | None = None  # PROPOSE / REMOVE_OR_CHOOSE


def identity_key(car: CaseCar) -> tuple[object, ...]:
    k = car.constraints
    e = k.engine_hint
    engine = (e.displacement_l, e.power_kw, e.fuel, (e.family or "").lower()) if e and not e.empty() else None
    return ((car.make or "").lower(), (car.model or "").lower(), (k.generation_hint or "").lower(), engine,
            k.gearbox_hint, k.drive_hint, car.year, car.age_years, car.condition, (k.trim_hint or "").lower(),
            k.fuel_hint, k.url, (k.version_hint or "").lower())  # fmt: skip


def progress(before: CaseCar | None, after: CaseCar | None, outcome_before: str | None,
             outcome_after: str | None) -> bool:  # fmt: skip
    if before is None or after is None:
        return True  # a car was added or removed
    if identity_key(before) != identity_key(after):
        return True
    return _RANK.get(outcome_after, 0) > _RANK.get(outcome_before, 0)


def _need(car: CaseCar) -> IntakeItem | None:
    """What is still missing for this car (None: identified)."""
    o = car.identify
    if not car.make:
        return "MAKE"
    if not car.model:
        return o.need if o and o.need in ("MODEL", "CHOICE") else "MODEL"
    if o is None:
        return None  # not identified yet in this turn (a case before 005, or a 4th car): the policy rules decide
    outcome: IdentifyKind = o.outcome
    if outcome == "IDENTIFIED":
        return None
    if outcome == "CHOICES":
        return o.need or "CHOICE"
    return o.need or "MODEL"


def next_step(case: CaseFile, limits: Limits = Limits()) -> Step:  # noqa: B008 - frozen dataclass
    items: list[StepItem] = []
    for car in case.cars:
        item = _need(car)
        if item is None:
            continue
        laddered = car.identify is not None and car.identify.level is not None
        total = sum(case.intake.attempts.get(car.key, {}).values())
        if laddered:  # spec 008: a ladder level asked twice is settled by the identify step, never "remove or choose"
            n = case.intake.attempt(car.key, item)
            items.append(StepItem(item, car.key, rephrase=n >= 1, choices=tuple(car.identify.choices)))  # type: ignore[union-attr]
            continue
        if (
            total >= limits.max_attempts_per_car
            or case.intake.attempt(car.key, "CHOICE") >= limits.max_attempts_per_item
        ):
            return Step("REMOVE_OR_CHOOSE", car_key=car.key)
        n = case.intake.attempt(car.key, item)
        if n >= limits.max_attempts_per_item:
            return Step("PROPOSE", car_key=car.key)
        choices = tuple(car.identify.choices) if car.identify else ()
        items.append(StepItem(item, car.key, rephrase=n >= 1, choices=choices))
    if limits.full_intake and items:  # asked together with an identity question, never on its own (FR-018)
        items += _condition_and_year(case, limits)
    if items:
        return Step("ASK", tuple(items[:MAX_ITEMS]))
    if not case.cars or case.intake.card_confirmed:
        return Step("NONE")
    return Step("CARD")


def _condition_and_year(case: CaseFile, limits: Limits) -> list[StepItem]:
    """New or used, asked once for every car together; then year (and mileage) of each used car."""
    n = case.intake.attempt(ALL, "CONDITION")
    if any(c.condition == "UNKNOWN" for c in case.cars) and n < limits.max_attempts_per_item:
        return [StepItem("CONDITION", None, rephrase=n >= 1)]
    out = []
    for car in case.cars:
        n = case.intake.attempt(car.key, "YEAR")
        if car.condition == "USED" and car.year is None and car.age_years is None and n < limits.max_attempts_per_item:
            out.append(StepItem("YEAR", car.key, rephrase=n >= 1))
    return out


def question_hash(car_key: str | None, item: str, text: str) -> str:
    norm = " ".join(text.lower().split())
    return hashlib.sha1(f"{car_key or ALL}|{item}|{norm}".encode()).hexdigest()[:12]


def is_repeat(case: CaseFile, car_key: str | None, item: str, text: str) -> bool:
    return question_hash(car_key, item, text) in case.intake.last_questions


def record_asked(case: CaseFile, asked: Iterable[tuple[StepItem, str]]) -> CaseFile:
    """Remember what was asked: attempts +1 per item, the text hashes (≤ 6, newest last)."""
    c = case.model_copy(deep=True)
    for it, text in asked:
        c.intake.bump(it.car_key or ALL, it.item)
        c.intake.last_questions = [*c.intake.last_questions, question_hash(it.car_key, it.item, text)][-6:]
    return c
