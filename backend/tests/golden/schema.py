"""Golden dialogue format (FR-046, SC-001/002).

Assertions cover the action, case-file fields and resolved variants per turn, not prose.

    id: g1_bigster_prado
    scenario: bigster_prado          # tests/fixtures/scenarios/<name> (replay search)
    seed:                            # catalog entries (and fresh cached specs) before the dialogue
      - {make: Toyota, model: Land Cruiser Prado, generation: J150, variant_name: 3.0 D-4D, powertrain: ICE,
         years: [2009, 2017], cached: true}
    turns:
      - user: "..."                  # or: confirm: run | skip | "option:<id>"
        expect:
          action: ASK
          status: DONE               # or WAITING_CONFIRMATION
          case:                      # path -> value | {contains|not_contains|lte|gte|in: ...}
            persona: BUYER
            cars[1].condition: USED
          variants: [{car: "car#2", generation: J150, years_include: 2015}]
          no_variant_generation: [J250]
          max_questions: 3
          no_search: true
          max_cost_eur: 0.30
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, model_validator


class VariantExpect(BaseModel):
    car: str
    generation: str | None = None
    years_include: int | None = None
    make: str | None = None
    model: str | None = None


class Expect(BaseModel):
    action: str | None = None
    status: str | None = None
    case: dict[str, Any] = Field(default_factory=dict)
    variants: list[VariantExpect] = Field(default_factory=list)
    no_variant_generation: list[str] = Field(default_factory=list)
    max_questions: int | None = None
    no_search: bool = False
    max_cost_eur: float | None = None
    confirm_kind: str | None = None
    language: str | None = None
    block_order_starts_with: list[str] = Field(default_factory=list)
    researched: list[str] | None = None  # exactly these car keys had research jobs this turn


class Turn(BaseModel):
    user: str | None = None
    confirm: str | None = None
    expect: Expect = Field(default_factory=Expect)

    @model_validator(mode="after")
    def one_input(self) -> Turn:
        if (self.user is None) == (self.confirm is None):
            raise ValueError("each turn needs exactly one of `user` or `confirm`")
        return self


class SeedVariant(BaseModel):
    make: str
    model: str
    generation: str | None = None
    variant_name: str
    powertrain: str = "ICE"
    body_class: str | None = None
    years: tuple[int, int | None] | None = None
    vehicle_class: str | None = None
    segment: str | None = None
    cached: bool = False
    specs: dict[str, float | str] = Field(default_factory=dict)


class Dialogue(BaseModel):
    id: str
    scenario: str | None = None
    description: str = ""
    seed: list[SeedVariant] = Field(default_factory=list)
    settings: dict[str, Any] = Field(default_factory=dict)  # overrides of automind.config settings for this dialogue
    turns: list[Turn]
