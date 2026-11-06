"""A car in the case: what the person said (request, constraints), the options offered, the identification outcome and
its ladder memo."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from automind.chat.domain.case.enums import Condition, IdentifyKind, IntakeItem, Resolution
from automind.shared.vehicle.engine import EngineHint


class Constraints(BaseModel):
    generation_hint: str | None = None
    fuel_hint: str | None = None
    body_hint: str | None = None
    trim_hint: str | None = None
    gearbox_hint: Literal["manual", "automatic", "dct", "cvt", "e-cvt", "single"] | None = None  # spec 004 FR-028
    drive_hint: Literal["FWD", "RWD", "AWD"] | None = None
    version_hint: str | None = Field(default=None, max_length=80)  # spec 008: the exact engine of a tapped option
    url: str | None = None
    engine_hint: EngineHint | None = None  # spec 005 FR-012


class Choice(BaseModel):
    """A concrete option offered during the intake (a model of a line-up, a version, an engine)."""

    label: str
    make: str | None = None
    model: str | None = None
    variant_id: str | None = None
    engine: str | None = None
    body: str | None = None
    powertrain: str | None = None
    price_from_eur: int | None = None
    source_url: str | None = None
    suggested: bool = False  # the user did not name it (FR-024)
    reason: str | None = None
    # spec 008: an option of one ladder level, with its facts (a tap sets them; the label is never parsed)
    level: Literal["FUEL", "ENGINE", "FAMILY", "POWER", "GEARBOX", "DRIVE"] | None = None
    fuel: str | None = None
    engine_cc: int | None = None
    family: str | None = None
    power_kw: int | None = None
    gearbox: str | None = None
    drive: str | None = None
    # a version the open registration datasets list (chat 6e001ee0): the combustion engine's kW (a hybrid's is
    # not its power) and the registration years; the label is built from them in the user's language
    engine_kw: int | None = None
    power_is_max: bool = False
    years_from: int | None = None
    years_to: int | None = None


class IdentifyOutcome(BaseModel):
    """Result of the identify step for one car, recomputed every intake turn (spec 005 R1)."""

    outcome: IdentifyKind = "NEED"
    need: IntakeItem | None = None
    choices: list[Choice] = Field(default_factory=list)
    checked: list[str] = Field(default_factory=list)  # sources looked at before NOT_FOUND
    note: str | None = None  # e.g. "from the page I took: …"
    key: str | None = None  # hash of the identity facts the outcome was computed for
    level: str | None = None  # spec 008: the ladder level asked (FUEL, ENGINE, FAMILY, POWER, GEARBOX, DRIVE)
    missing: list[str] = Field(default_factory=list)  # spec 008 FR-004: what the user named that does not exist
    events: list[dict[str, str]] = Field(default_factory=list)  # spec 008: notices to show ({"kind": …, …})


class LadderMemo(BaseModel):
    """Where the identification ladder stood at the last identify (spec 008): the value of each level, who settled
    it (the user, "choose for me" or the ask limit) and whether the version comes from a sourced list."""

    levels: dict[str, str] = Field(default_factory=dict)
    origin: dict[str, Literal["STATED", "CHOSEN", "LIMIT"]] = Field(default_factory=dict)
    certainty: Literal["SOURCED", "LESS_CERTAIN"] | None = None
    generation: str | None = None
    generation_from: int | None = None
    generation_to: int | None = None
    source_url: str | None = None  # the document that lists the settled version
    source_name: str | None = None  # the list's source when not a web page ("EU registrations (EEA CO2 / RDW)")
    others: list[str] = Field(default_factory=list)  # other versions of this generation and year (card chips)


class CaseCar(BaseModel):
    key: str
    request_text: str
    make: str | None = None
    model: str | None = None
    condition: Condition = "UNKNOWN"
    year: int | None = None
    age_years: int | None = None
    mileage_km: int | None = None
    constraints: Constraints = Field(default_factory=Constraints)
    variant_id: str | None = None
    label: str | None = None  # resolved variant label, for display
    resolution: Resolution = "UNRESOLVED"
    alternatives: list[dict[str, object]] = Field(default_factory=list)
    previous_label: str | None = None  # spec 005: the label before the last correction ("before → after")
    identify: IdentifyOutcome | None = None  # spec 005 R1
    chosen_for_me: bool = False  # the user said "choose for me": the version found is taken without asking again
    year_assumed: bool = False  # spec 008 FR-022: a used car's year assumed from mileage or generation
    ladder: LadderMemo | None = None  # spec 008
    replaced: bool = False  # 009 FR-022: the user's own car that the purchase replaces (compared, not a candidate)
    # chat 2026-11-06: the market the car was identified on when it is not on the Spanish line-up ("EU", "CN",
    # "ANY"); None: Spain. Outside Europe no price is taken (spec 009 FR-009)
    market: str | None = None

    @property
    def display_name(self) -> str:
        """How the car is named in questions: the facts known now, never stale request text (spec 005 R5)."""
        if self.label:
            return self.label
        if not (self.make and self.model):
            return self.make or self.request_text
        k = self.constraints
        engine = k.engine_hint.text() if k.engine_hint else ""
        trim = k.trim_hint if k.trim_hint and k.trim_hint not in engine else ""
        bits = [self.make, self.model, k.generation_hint or "", engine, trim]
        return " ".join(b for b in bits if b)
