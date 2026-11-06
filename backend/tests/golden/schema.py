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
    # spec 006: electrified cars (car keys as in `variants`)
    energy_for: list[str] = Field(default_factory=list)  # the TCO energy line has an amount for these cars
    energy_missing_for: list[str] = Field(default_factory=list)  # "cannot be computed" for these cars
    no_weighted_priced: bool = False  # no energy part uses a weighted plug-in figure
    labels: dict[str, str] = Field(default_factory=dict)  # car -> DGT label in the verdict
    break_even: str | None = None  # YEARS | NEVER | ALREADY_CHEAPER | CHEAPER_TO_BUY | UNKNOWN
    electric_cars: list[str] | None = None  # exactly these cars are rows of the electric section
    electric_share_for: list[str] = Field(default_factory=list)  # a plug-in with a computed electric share
    retention_insufficient: list[str] = Field(default_factory=list)  # "insufficient data for this brand"
    notes_contain: list[str] = Field(default_factory=list)  # substrings of the verdict's profile notes
    energy_metrics: dict[str, Any] = Field(default_factory=dict)  # FR-022: fields of this turn's ENERGY_REPORT


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
    # spec 006: the market facts (incentives) this dialogue starts with; the table is reset for every dialogue
    market_facts: list[dict[str, Any]] = Field(default_factory=list)
    forget: list[str] = Field(default_factory=list)  # makes whose catalog rows from other tests are hidden first
    settings: dict[str, Any] = Field(
        default_factory=dict
    )  # overrides of automind.shared.infrastructure.config.settings settings for this dialogue
    turns: list[Turn]
