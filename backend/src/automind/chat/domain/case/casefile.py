"""The case file (FR-002; R3): the structured, versioned understanding of the person and the task, the aggregate root,
with the dialogue state it keeps (intake attempts, pending questions, what was shown)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from automind.chat.domain.case.car import CaseCar, Choice
from automind.chat.domain.case.enums import (
    BASIS_RANK,
    MAX_CARS,
    Body,
    Depth,
    Persona,
    PersonaSource,
    ProfileBasis,
    QuestionKind,
    Usage,
)
from automind.chat.domain.case.person import Budget, Needs, Priority, Profile, Rates, RunningLimit, StatedEnergy


class RaceSettings(BaseModel):
    surface: Literal["DRY", "WET"] = "DRY"
    extra_load_kg: float = Field(default=0, ge=0, le=500)
    temperature_c: float | None = Field(default=None, ge=-30, le=50)
    altitude_m: float | None = Field(default=None, ge=0, le=5000)


class Prediction(BaseModel):
    winner_key: str


class Intake(BaseModel):
    """Intake loop state (spec 005 R6): attempts per car and item, the last question hashes, the card."""

    attempts: dict[str, dict[str, int]] = Field(default_factory=dict)
    last_questions: list[str] = Field(default_factory=list)  # ≤ 6 hashes, newest last
    proposed: dict[str, Choice] = Field(default_factory=dict)
    card: dict[str, object] | None = None  # the card last shown (for highlighting edits)
    card_confirmed: bool = False

    def attempt(self, car_key: str, item: str) -> int:
        return self.attempts.get(car_key, {}).get(item, 0)

    def bump(self, car_key: str, item: str) -> None:
        self.attempts.setdefault(car_key, {})[item] = self.attempt(car_key, item) + 1


class Pending(BaseModel):
    kind: Literal["QUESTIONS", "CONFIRM_VARIANTS", "CONFIRM_COST", "CONFIRM_INTAKE"]
    items: list[dict[str, object]] = Field(default_factory=list)


class Shown(BaseModel):
    turn_seq: int
    fingerprint: str
    blocks: list[str] = Field(default_factory=list)
    persona: str | None = None  # persona the report was written for


class CaseFile(BaseModel):
    persona: Persona = "UNKNOWN"
    persona_source: PersonaSource = "INFERRED"
    profile: Profile = Field(default_factory=Profile)
    usage: list[Usage] = Field(default_factory=list)
    budget: Budget = Field(default_factory=Budget)
    running_cost_limit: RunningLimit | None = None
    needs: Needs = Field(default_factory=Needs)
    feasibility_ack: str | None = None  # fingerprint of the feasibility verdict the user answered (spec 003)
    annual_km: int = Field(default=15000, ge=1000, le=200000)
    annual_km_stated: bool = False  # the user said it (spec 004: otherwise it may be asked when it matters)
    rates_override: Rates = Field(default_factory=Rates)
    depth: Depth = "STANDARD"
    priorities: list[Priority] = Field(default_factory=list)
    weights: dict[str, float] = Field(default_factory=dict)
    weights_overridden: bool = False  # before spec 007: `weights` were absolute; now read as adjustments
    # spec 007 FR-010: manual weights are points on top of the automatic ones; excluded criteria stay at 0
    weight_adjustments: dict[str, float] = Field(default_factory=dict)
    weights_excluded: list[str] = Field(default_factory=list)
    unmapped_wishes: list[str] = Field(default_factory=list)
    cars: list[CaseCar] = Field(default_factory=list)
    next_car_no: int = 1
    race_settings: RaceSettings | None = None
    prediction: Prediction | None = None
    asked: list[QuestionKind] = Field(default_factory=list)  # question kinds already asked (one round, FR-005)
    declined_plan: str | None = None  # research plan the user declined; not offered again until it changes
    pending: Pending | None = None
    # spec 004 FR-029: all cars are compared at one equipment level (base unless the user named a version)
    compare_level: Literal["BASE", "MID", "TOP"] = "BASE"
    compare_level_source: Literal["DEFAULT", "USER_TRIM"] = "DEFAULT"
    last_values: dict[str, int] = Field(default_factory=dict)  # validated values per car at the last report
    # spec 007 F: areas a "find it" searched deeper without reaching the minimum (variant id -> areas); the button
    # is not offered again for them (incident 2026-11-03: three clicks, nothing new)
    find_tried: dict[str, list[str]] = Field(default_factory=dict)
    # spec 007 US7: the body the user asked for without naming a car ("семейный кроссовер"), and the candidates
    # proposed for it: {key, make, model, why: [reason keys], price_from_eur}
    wanted_body: Body | None = None
    candidates: list[dict[str, object]] = Field(default_factory=list)
    # 009 FR-022: the make to choose from when the user names a make but no model ("find me a Kia to replace my
    # Prado"): candidates of that make are proposed instead of asking "which model?"
    wanted_make: str | None = None
    # spec 007 FR-013: scores and weights at the last report, so the next one can show what changed
    last_scores: dict[str, dict[str, float]] = Field(default_factory=dict)
    last_weights: dict[str, float] = Field(default_factory=dict)
    shown: list[Shown] = Field(default_factory=list)
    intake: Intake = Field(default_factory=Intake)  # spec 005
    # spec 007: how each profile field is known, and how long the user keeps a car
    basis: dict[str, ProfileBasis] = Field(default_factory=dict)
    ownership_years: int | None = Field(default=None, ge=1, le=20)
    stated_energy: list[StatedEnergy] = Field(default_factory=list)  # the user's own consumption figures

    @model_validator(mode="after")
    def _legacy_basis(self) -> CaseFile:
        """Older case files carry flags instead of a basis (read-time upgrade, no migration)."""
        b = self.basis
        if "persona" not in b and self.persona != "UNKNOWN":
            b["persona"] = "STATED" if self.persona_source in ("USER_EDIT", "ASKED") else "INFERRED"
        if "annual_km" not in b and self.annual_km_stated:
            b["annual_km"] = "STATED"
        for f in ("family", "age_band", "driving_style"):
            if f not in b and getattr(self.profile, f) is not None:
                b[f] = "STATED"  # set from the user's own words in that message (spec 004 FR-017)
        if "budget" not in b and self.budget.max_eur is not None:
            b["budget"] = "STATED"
        if "condition" not in b and self.budget.intent != "UNKNOWN":
            b["condition"] = "STATED"
        if "monthly_limit" not in b and self.running_cost_limit is not None:
            b["monthly_limit"] = "STATED"
        if "usage" not in b and self.usage:
            b["usage"] = "STATED"
        return self

    def may_set(self, field: str, basis: str) -> bool:
        """A weaker basis never overwrites a stronger one (STATED > INFERRED > ASSUMED)."""
        return BASIS_RANK[basis] >= BASIS_RANK[self.basis.get(field, "ASSUMED")]

    @property
    def too_many_cars(self) -> bool:
        return len(self.cars) > MAX_CARS

    def car(self, key: str) -> CaseCar:
        for c in self.cars:
            if c.key == key:
                return c
        raise ValueError(f"unknown car reference {key!r} (known: {', '.join(x.key for x in self.cars) or 'none'})")
