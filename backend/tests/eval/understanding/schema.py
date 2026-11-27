"""The format of `cases.yaml`, the golden message set of the understanding layer (spec 013 T004).

A case is one message in a named context (a case file and an open bot question with option ids, `fixtures.yaml`) and
the expected significant fields of the `Intent` (understanding-spec §4) plus the expected `Action.kind`. Only what is
written is checked, except three fields that always are: `answer` (absent = no answer to the open question), `goals`
(ordered; absent = none) and `action`. `reaction` is checked unless `any`; `rejections` / `changes` only when present.
Cross-references between cases and fixtures are checked by `coverage.check_set`; T005 runs the set on a model.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import Field, model_validator

from automind.chat.domain.case.enums import Condition, CriterionKey, Drive, Gearbox, Persona, Usage
from automind.chat.domain.identification.rejection import RejectLevel
from automind.shared.vehicle.engine import Fuel
from tests.eval.understanding.fixture_models import HERE, CarKey, Strict
from tests.eval.understanding.vocab import ActionKind, AnswerKind, Category, GoalKind, Lang, ReactionExpect, Source


class AnswerExpect(Strict):
    pending_id: str
    kind: AnswerKind
    option_id: str | None = None  # None with kind `option` is refused; None otherwise = not checked

    @model_validator(mode="after")
    def _option_named(self) -> AnswerExpect:
        if self.kind is AnswerKind.OPTION and not self.option_id:
            raise ValueError("an `option` answer names its option_id")
        return self


class GoalExpect(Strict):
    kind: GoalKind
    focus_cars: list[CarKey] | None = None  # None = not checked
    focus_areas: list[str] | None = None


class RejectionExpect(Strict):
    car: CarKey
    level: RejectLevel
    value: str | None = None  # None = "the current one"
    wanted: str | None = None


class CarChange(Strict):
    """Facts about one existing car (`set_car_context` / `replace_cars`); only what is written is checked."""

    make: str | None = None
    model: str | None = None
    condition: Condition | None = None
    age_years: int | None = None
    year: int | None = None
    generation: str | None = None
    fuel: Fuel | None = None
    engine: str | None = None  # a family / version word the person used ("R-EV", "D-4D")
    displacement_l: float | None = None
    power_hp: int | None = None
    power_kw: int | None = None
    gearbox: Gearbox | None = None
    drive: Drive | None = None
    trim: str | None = None
    url: str | None = None
    replace: bool | None = None  # True = replace_cars (a correction), not set_car_context


class ChangesExpect(Strict):
    """Key `case_changes`; `empty: true` = nothing changes. `add_cars: []` = no car is added."""

    empty: bool = False
    add_cars: list[str] | None = None  # "Make Model" (or "Make") of each car added, in order
    replaced_car: str | None = None  # "Make Model" of the person's own car (`replaced: true`)
    choose_from_make: str | None = None
    cars: dict[CarKey, CarChange] = Field(default_factory=dict)
    persona: Persona | None = None
    priorities: list[CriterionKey] | None = None
    unmapped_wishes: bool | None = None
    budget_max_eur: int | None = None
    budget_intent: Literal["NEW", "USED", "ANY"] | None = None
    running_cost_eur: int | None = None
    passengers: int | None = None
    luggage_high: bool | None = None
    towing_kg: int | None = None
    annual_km: int | None = None
    ownership_years: int | None = None
    usage: list[Usage] | None = None
    family: Literal["SINGLE", "COUPLE", "FAMILY"] | None = None
    age: int | None = None
    region: str | None = None
    home_charging: Literal["YES", "WORK", "NO"] | None = None
    race: bool | None = None
    prediction: CarKey | None = None

    @model_validator(mode="after")
    def _empty_alone(self) -> ChangesExpect:
        if self.empty and len(self.model_fields_set - {"empty"}) > 0:
            raise ValueError("`empty: true` takes no other field")
        return self


class Expected(Strict):
    language: Lang
    answer: AnswerExpect | None = None
    goals: list[GoalExpect] = Field(default_factory=list)
    reaction: ReactionExpect = ReactionExpect.ANY
    rejections: list[RejectionExpect] | None = None
    changes: ChangesExpect | None = None
    action: ActionKind


class Case(Strict):
    id: str = Field(pattern=r"^(ru|es|en)-\d{3}$")
    lang: Lang
    sources: list[Source] = Field(min_length=1)
    ref: str | None = None  # golden "g13 t2", pre-prod "chat d170b861 11-26 19:16", interpreter "ex10b"
    fixture: str
    pending: str | None = None
    history: str | None = None  # the bot's last message (summary), for `reaction`
    message: str = Field(min_length=1)
    tags: list[Category] = Field(default_factory=list)
    words: list[str] = Field(default_factory=list)  # "YES:да" — phrases word lists this message carries
    patches: list[str] = Field(default_factory=list)  # interpreter.md rule / example ids (coverage.INTERPRETER)
    note: str | None = None
    expect: Expected

    @model_validator(mode="after")
    def _consistent(self) -> Case:
        if not self.id.startswith(self.lang.value):
            raise ValueError(f"{self.id}: id prefix differs from lang {self.lang}")
        needs_ref = {Source.GOLDEN, Source.PREPROD, Source.PREPROD_MISS, Source.INTERPRETER}
        if needs_ref & set(self.sources) and not self.ref:
            raise ValueError(f"{self.id}: a golden / pre-prod / interpreter.md source names its ref")
        if self.expect.answer and not self.pending:
            raise ValueError(f"{self.id}: an answer needs an open question")
        if self.expect.action is ActionKind.ANSWER_AND_REASK and not self.pending:
            raise ValueError(f"{self.id}: ANSWER_AND_REASK needs an open question")
        return self


class CaseSet(Strict):
    cases: list[Case]


def load_cases(path: Path = HERE / "cases.yaml") -> list[Case]:
    """The golden message set, validated per case (raises pydantic.ValidationError on a malformed case)."""
    return CaseSet.model_validate(yaml.safe_load(path.read_text(encoding="utf-8"))).cases
