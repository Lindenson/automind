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
          cars: {car#1: {model: C-Class, settled: false, label_not_contains: [E-Class]}}   # spec 013
          reply_kind: ASK
          not_repeated: true
          stopped: true
        known_bug: "..."             # spec 013: strict expected failure of the current code
        later:                       # spec 013: checks of a later step; `expect` above must pass now
          - known_bug: "no stop intent (S4)"
            expect: {stopped: true}
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


class CarExpect(BaseModel):
    """Spec 013 T002: one car of the case after the turn."""

    make: str | None = None
    model: str | None = None  # the model the case keeps (the person's, never a look-alike)
    resolution: str | None = None  # until S5; then identity_state
    identity_state: str | None = None  # spec 013 S5 (NAMED … CONFIRMED); not checked before the field exists
    asked_level: str | None = None  # the level identification asks about (ENGINE, MODEL …); "none": nothing asked
    settled: bool | None = None  # false: no version chosen for the car without the person's answer
    label_not_contains: list[str] = Field(default_factory=list)  # e.g. ["E-Class"] for a C-Class


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
    # spec 013 T002: dialogue quality
    cars: dict[str, CarExpect] = Field(default_factory=dict)  # car key -> expectations
    reply_kind: str | None = None  # ASK | CONFIRM | REPORT | ANSWER | STOPPED (derived from status, action, pending)
    not_repeated: bool = False  # no question of this turn (car, kind, options) was asked on the previous turn
    stopped: bool = False  # the open question / search ended: nothing pending, no research, no question asked
    reply_not_contains: list[str] = Field(default_factory=list)  # e.g. "Я не понял ответ" (a complaint as an answer)


class Later(BaseModel):
    """Spec 013: expectations a later step makes pass. Each block must still fail (strict, like `known_bug`); the
    turn's own `expect` must pass now. A turn whose message is fixed in steps keeps each step's checks apart."""

    known_bug: str
    expect: Expect = Field(default_factory=Expect)


class Turn(BaseModel):
    user: str | None = None
    confirm: str | None = None
    # spec 013 T003: a known failure of the current code. The turn must fail (strict: a fix that makes it pass
    # fails the gate until the marker is removed); the dialogue is reported xfail while every marked turn fails.
    known_bug: str | None = None
    expect: Expect = Field(default_factory=Expect)
    later: list[Later] = Field(default_factory=list)

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
    # spec 013: a catalogue row as the replayed chat found it (identification reads these)
    transmission: str | None = None
    drive: str | None = None
    trim: str | None = None
    engine_cc: int | None = None
    power_kw: int | None = None
    fuel: str | None = None


class SeedLineup(BaseModel):
    """A make's cached line-up (`brand_lineups`), as found in the database of the chat replayed."""

    make: str
    market: str = "ES"
    models: list[dict[str, Any]]
    sources: list[dict[str, Any]] = Field(default_factory=list)


class SeedVersions(BaseModel):
    """A model generation's cached versions (`model_versions`), as found in the database of the chat replayed."""

    make: str
    model: str
    generation: str
    years_from: int | None = None
    years_to: int | None = None
    body_class: str | None = None
    versions: list[dict[str, Any]]
    sources: list[dict[str, Any]] = Field(default_factory=list)


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
    # spec 013: the line-ups and versions caches the chat saw; either one wires the line-up look-up and the
    # versions store into the ports (identification as in production)
    lineups: list[SeedLineup] = Field(default_factory=list)
    model_versions: list[SeedVersions] = Field(default_factory=list)
    turns: list[Turn]
