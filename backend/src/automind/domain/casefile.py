"""Case file: the structured, versioned understanding of the user and the task (FR-002; R3, R4).

`apply(case, delta)` is the only way the hub changes the case. It is pure and deterministic,
returns a new case plus a human-readable change log, and the latest explicit statement wins
(FR-003). The LLM proposes a typed `CaseDelta`; code validates and applies it.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

CRITERION_KEYS = (
    "reliability",
    "ownership_cost",
    "purchase_price",
    "practicality",
    "comfort",
    "performance",
    "driving_fun",
    "traction_all_weather",
    "offroad_mountain",
    "efficiency",
    "safety",
    "status",
    "engineering",
)
CriterionKey = Literal[
    "reliability",
    "ownership_cost",
    "purchase_price",
    "practicality",
    "comfort",
    "performance",
    "driving_fun",
    "traction_all_weather",
    "offroad_mountain",
    "efficiency",
    "safety",
    "status",
    "engineering",
]
Persona = Literal["EXPERT", "PERFORMANCE", "BUYER", "UNKNOWN"]
PersonaSource = Literal["INFERRED", "ASKED", "USER_EDIT"]
# spec 007 FR-001: how each profile field is known. STATED: the user said it (chat or panel); INFERRED: read from
# the user's words with evidence; ASSUMED: a default. A weaker basis never overwrites a stronger one.
ProfileBasis = Literal["STATED", "INFERRED", "ASSUMED"]
BASIS_RANK: dict[str, int] = {"ASSUMED": 0, "INFERRED": 1, "STATED": 2}
PROFILE_FIELDS = ("persona", "ownership_years", "condition", "annual_km", "budget", "monthly_limit", "family",
                  "driving_style", "age_band", "region", "usage")  # fmt: skip
Usage = Literal["CITY", "MOTORWAY", "MOUNTAINS", "OFFROAD", "TRACK", "FAMILY"]
Depth = Literal["QUICK", "STANDARD", "DEEP"]
Condition = Literal["NEW", "USED", "UNKNOWN"]
Resolution = Literal["UNRESOLVED", "PROPOSED", "CONFIRMED", "AUTO_OK", "UNKNOWN_MODEL"]
Strength = Literal["LOW", "MEDIUM", "HIGH"]
QuestionKind = Literal[
    "TOO_MANY_CARS", "CAR_IDENTITY", "USED_AGE", "TRIM", "PERSONA", "BUDGET_INTENT", "UNKNOWN_MODEL", "GEARBOX",
    "KM_PER_YEAR", "FAMILY_SIZE", "CONDITION", "ENGINE", "MAKE_LINEUP", "PROPOSE", "REMOVE_OR_CHOOSE",
    "OWNERSHIP_YEARS", "CONFIRM_PROFILE", "HOME_CHARGING", "FUEL", "POWER", "DRIVE",
]  # fmt: skip
# spec 005: what an intake step is about (R6)
IntakeItem = Literal["MAKE", "MODEL", "ENGINE", "GEARBOX", "YEAR", "CONDITION", "MILEAGE", "TRIM", "CHOICE", "FUEL",
                     "POWER", "DRIVE"]  # fmt: skip
Fuel = Literal["petrol", "diesel", "hybrid", "mhev", "phev", "bev", "lpg"]
Climate = Literal["HOT", "MILD", "COLD", "MOUNTAIN"]
BudgetIntent = Literal["NEW", "USED", "ANY", "UNKNOWN"]

MAX_CARS = 3


class Profile(BaseModel):
    age: int | None = Field(default=None, ge=14, le=100)
    experience: str | None = None
    # spec 004 FR-017: inferred only from the user's words; `evidence` keeps those words per field
    family: Literal["SINGLE", "COUPLE", "FAMILY"] | None = None
    age_band: Literal["UNDER_25", "25_40", "40_60", "OVER_60"] | None = None
    driving_style: Literal["CALM", "MIXED", "SPORTY"] | None = None
    # spec 005 R11: where the car is driven and how far (a range when the user gives one)
    region: str | None = Field(default=None, max_length=60)
    region_code: str | None = None
    climate: Climate | None = None
    annual_km_min: int | None = Field(default=None, ge=1000, le=200000)
    annual_km_max: int | None = Field(default=None, ge=1000, le=200000)
    # spec 006 R5: where the user can charge (UNKNOWN is assumed YES and said so in the report)
    home_charging: Literal["YES", "WORK", "NO", "UNKNOWN"] = "UNKNOWN"
    evidence: dict[str, str] = Field(default_factory=dict)


class Budget(BaseModel):
    max_eur: int | None = Field(default=None, ge=0)  # the amount as stated (see currency and kind)
    note: str | None = None
    intent: BudgetIntent = "UNKNOWN"  # spec 003: a new car, a used one, or either
    currency: Literal["EUR", "GBP", "USD"] = "EUR"
    kind: Literal["TOTAL", "MONTHLY"] = "TOTAL"


class RunningLimit(BaseModel):
    """Most the user wants to spend on running the car (spec 003 FR-018)."""

    amount_eur: float = Field(gt=0)
    period: Literal["MONTH", "YEAR"] = "MONTH"

    @property
    def per_month(self) -> float:
        return self.amount_eur if self.period == "MONTH" else self.amount_eur / 12


class Needs(BaseModel):
    """Usage needs that a car must meet (spec 003 FR-018). Mountains come from `usage`."""

    passengers: int | None = Field(default=None, ge=1, le=9)
    luggage: Literal["LOW", "MEDIUM", "HIGH"] = "MEDIUM"
    towing_kg: int | None = Field(default=None, ge=100, le=4000)
    daily_km: int | None = Field(default=None, ge=1, le=2000)


class Rates(BaseModel):
    fuel_eur_per_l: float | None = Field(default=None, gt=0)
    diesel_eur_per_l: float | None = Field(default=None, gt=0)
    electricity_eur_per_kwh: float | None = Field(default=None, gt=0)  # legacy: read as the home price
    labour_eur_per_h: float | None = Field(default=None, gt=0)
    # spec 006 R7: the user's own electricity prices (0 = free charging at work) and a night tariff
    home_electricity_eur_per_kwh: float | None = Field(default=None, ge=0, le=1.5)
    public_ac_eur_per_kwh: float | None = Field(default=None, ge=0, le=1.5)
    public_dc_eur_per_kwh: float | None = Field(default=None, ge=0, le=1.5)
    night_tariff: bool | None = None


class RaceSettings(BaseModel):
    surface: Literal["DRY", "WET"] = "DRY"
    extra_load_kg: float = Field(default=0, ge=0, le=500)
    temperature_c: float | None = Field(default=None, ge=-30, le=50)
    altitude_m: float | None = Field(default=None, ge=0, le=5000)


class Prediction(BaseModel):
    winner_key: str


class Priority(BaseModel):
    criterion: CriterionKey
    strength: Strength
    source: Literal["USER", "PERSONA"] = "USER"


class EngineHint(BaseModel):
    """The engine the user named (spec 005 R4): any subset of displacement, power, fuel and family."""

    displacement_l: float | None = Field(default=None, ge=0.6, le=8.0)
    power_hp: int | None = Field(default=None, ge=40, le=1000)
    power_kw: int | None = Field(default=None, ge=30, le=750)
    fuel: Fuel | None = None
    family: str | None = Field(default=None, max_length=16)  # TSI, TDI, DM-i, e:HEV …
    evidence: str = Field(default="", max_length=120)

    def empty(self) -> bool:
        return not any((self.displacement_l, self.power_hp, self.power_kw, self.fuel, self.family))

    def text(self) -> str:
        bits = [f"{self.displacement_l:.1f}" if self.displacement_l else "", self.family or "",
                f"{self.power_hp} CV" if self.power_hp else (f"{self.power_kw} kW" if self.power_kw else ""),
                self.fuel if self.fuel and not self.family else ""]  # fmt: skip
        return " ".join(b for b in bits if b)


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


IdentifyKind = Literal["IDENTIFIED", "CHOICES", "NEED", "NOT_FOUND"]


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


class StatedEnergy(BaseModel):
    """A consumption figure the user gave for one of the cars ("в гибридном режиме 5,5 л"): it replaces the sourced
    or estimated value in the energy cost and is labelled as the user's (spec 006 follow-up). FUEL: l/100 km in real
    use (combustion and non-plug hybrids); CS: a plug-in with an empty battery; KWH: kWh/100 km as the car shows it;
    RANGE: real electric km on a full charge. No car_key: the one car the figure can apply to (decided at compute)."""

    kind: Literal["FUEL", "CS", "KWH", "RANGE"]
    value: float = Field(gt=0, le=1000)
    words: str = Field(default="", max_length=120)
    car_key: str | None = None


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
    wanted_body: Literal["suv", "estate", "mpv", "sedan", "hatchback"] | None = None
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


# --- delta -------------------------------------------------------------------------------------


class PersonaChange(BaseModel):
    persona: Persona
    source: PersonaSource = "INFERRED"


class PriorityChange(BaseModel):
    criterion: CriterionKey
    strength: Strength = "MEDIUM"


class CarRef(BaseModel):
    """A car the user mentioned: what they said plus the hints the interpreter could read from it."""

    request_text: str
    make: str | None = None
    model: str | None = None
    condition: Condition = "UNKNOWN"
    year: int | None = Field(default=None, ge=1950, le=2100)
    age_years: int | None = Field(default=None, ge=0, le=80)
    mileage_km: int | None = Field(default=None, ge=0)
    constraints: Constraints = Field(default_factory=Constraints)
    replaced: bool = Field(default=False, description="The user's own car that the purchase replaces ('to replace "
                           "my Prado'); it is compared with the candidates")  # fmt: skip


class CarContext(BaseModel):
    """Changes to an existing car (`set_car_context`) or its replacement (`replace_cars`)."""

    target_key: str
    request_text: str | None = None
    make: str | None = None
    model: str | None = None
    condition: Condition | None = None
    year: int | None = Field(default=None, ge=1950, le=2100)
    age_years: int | None = Field(default=None, ge=0, le=80)
    mileage_km: int | None = Field(default=None, ge=0)
    constraints: Constraints | None = None


class CaseDelta(BaseModel):
    set_persona: PersonaChange | None = None
    # spec 007: STATED unless the interpreter marks a field INFERRED (with the user's words in profile.evidence)
    profile_basis: dict[str, Literal["STATED", "INFERRED"]] = Field(default_factory=dict)
    set_ownership_years: int | None = Field(default=None, ge=1, le=20)
    set_profile: Profile | None = None
    set_usage: list[Usage] | None = None
    set_budget: Budget | None = None
    set_running_cost_limit: RunningLimit | None = None
    set_needs: Needs | None = None
    set_annual_km: int | None = Field(default=None, ge=1000, le=200000)
    set_depth: Depth | None = None
    set_rates_override: Rates | None = None
    add_priorities: list[PriorityChange] = Field(default_factory=list)
    remove_priorities: list[CriterionKey] = Field(default_factory=list)
    add_cars: list[CarRef] = Field(default_factory=list)
    replace_cars: list[CarContext] = Field(default_factory=list)
    remove_cars: list[str] = Field(default_factory=list)
    set_car_context: list[CarContext] = Field(default_factory=list)
    unmapped_wishes: list[str] = Field(default_factory=list)
    set_race_settings: RaceSettings | None = None
    set_prediction: Prediction | None = None
    choose_from_make: str | None = Field(default=None, description="A make the user wants a car of without naming "
                                         "a model ('find me a Kia'); never also in add_cars")  # fmt: skip

    def is_empty(self) -> bool:
        return self == CaseDelta()


# --- apply -------------------------------------------------------------------------------------


def apply(case: CaseFile, delta: CaseDelta, *, current_year: int) -> tuple[CaseFile, list[str]]:
    """Apply a validated delta. Pure: returns (new case, change log). Unknown car keys raise ValueError."""
    c = case.model_copy(deep=True)
    log: list[str] = []
    _apply_persona_profile(c, delta, log)
    _apply_settings(c, delta, log)
    _apply_priorities(c, delta, log)
    _apply_cars(c, delta, log, current_year)
    p = delta.set_prediction
    if p is not None and p != c.prediction:
        c.car(p.winner_key)  # must reference a car in the case
        c.prediction = p
        log.append(f"prediction: {p.winner_key} wins")
    for wish in delta.unmapped_wishes:
        w = wish.strip()
        if w and w not in c.unmapped_wishes:
            c.unmapped_wishes.append(w)
            log.append(f"not assessable: {w}")
    return c, log


def _basis(d: CaseDelta, field: str) -> str:
    return d.profile_basis.get(field, "STATED")


def _apply_persona_profile(c: CaseFile, d: CaseDelta, log: list[str]) -> None:
    _apply_persona(c, d, log)
    if d.set_ownership_years is not None and c.may_set("ownership_years", _basis(d, "ownership_years")):
        if d.set_ownership_years != c.ownership_years:
            log.append(f"ownership: {d.set_ownership_years} years")
        c.ownership_years = d.set_ownership_years
        c.basis["ownership_years"] = _basis(d, "ownership_years")  # type: ignore[assignment]
    if d.set_profile is not None:
        _apply_profile(c, d, d.set_profile, log)


def _apply_persona(c: CaseFile, d: CaseDelta, log: list[str]) -> None:
    p = d.set_persona
    if p is not None:
        b = "STATED" if p.source in ("USER_EDIT", "ASKED") else _basis(d, "persona")
        if p.source == "INFERRED" and "persona" not in d.profile_basis:
            b = "INFERRED"
        weak_over_edit = p.source == "INFERRED" and c.persona_source == "USER_EDIT"
        if not weak_over_edit and c.may_set("persona", b) and (p.persona != c.persona or p.source != c.persona_source):
            if p.persona != c.persona:
                log.append(f"persona: {c.persona} → {p.persona}")
            c.persona, c.persona_source = p.persona, p.source
            c.basis["persona"] = b  # type: ignore[assignment]


def _apply_profile(c: CaseFile, d: CaseDelta, sp: Profile, log: list[str]) -> None:
    if sp.age is not None and sp.age != c.profile.age:
        c.profile.age = sp.age
        log.append(f"age: {c.profile.age}")
    if sp.experience and sp.experience != c.profile.experience:
        c.profile.experience = sp.experience
        log.append(f"experience: {c.profile.experience}")
    for f in ("family", "age_band", "driving_style"):
        val = getattr(sp, f)
        words = sp.evidence.get(f, "").strip()
        b = _basis(d, f)
        if val is None or not words or not c.may_set(f, b):  # only with the user's own words
            continue
        if val != getattr(c.profile, f):
            setattr(c.profile, f, val)
            tag = "" if b == "STATED" else " — inferred"
            log.append(f'{f.replace("_", " ")}: {val.lower()} ("{words[:60]}"){tag}')
        c.profile.evidence[f] = words[:120]
        c.basis[f] = b  # type: ignore[assignment]


def apply_defaults(case: CaseFile, defaults: dict[str, object] | None) -> CaseFile:
    """Fill what the user has not said with the persona's defaults, marked ASSUMED (spec 007 FR-003). Pure."""
    per = dict((defaults or {}).get("personas", {}) or {})  # type: ignore[call-overload]
    d = dict(per.get(case.persona) or per.get("UNKNOWN") or {})
    c = case.model_copy(deep=True)
    years = d.get("ownership_years")
    if years is not None and c.basis.get("ownership_years", "ASSUMED") == "ASSUMED":
        c.ownership_years = int(years)
        c.basis["ownership_years"] = "ASSUMED"
    km = d.get("annual_km")
    if km is not None and c.basis.get("annual_km", "ASSUMED") == "ASSUMED" and not c.annual_km_stated:
        c.annual_km = int(km)
        c.basis["annual_km"] = "ASSUMED"
    if c.basis.get("persona") is None:
        c.basis["persona"] = "ASSUMED"
    if c.budget.intent == "UNKNOWN" and "condition" not in c.basis:
        c.basis["condition"] = "ASSUMED"
    return c


def _money(v: int | None) -> str:
    return "none" if v is None else f"≤ €{v:,}"


def _apply_settings(c: CaseFile, d: CaseDelta, log: list[str]) -> None:
    if d.set_usage is not None and c.may_set("usage", _basis(d, "usage")):
        if d.set_usage != c.usage:
            c.usage = list(dict.fromkeys(d.set_usage))
            log.append("usage: " + ", ".join(c.usage))
        c.basis["usage"] = _basis(d, "usage")  # type: ignore[assignment]
    _apply_constraints(c, d, log)
    if d.set_annual_km is not None and c.may_set("annual_km", _basis(d, "annual_km")):
        if d.set_annual_km != c.annual_km:
            log.append(f"annual mileage: {c.annual_km:,} → {d.set_annual_km:,} km")
            c.annual_km = d.set_annual_km
        c.basis["annual_km"] = _basis(d, "annual_km")  # type: ignore[assignment]
        c.annual_km_stated = c.basis["annual_km"] == "STATED"
    if d.set_depth is not None and d.set_depth != c.depth:
        log.append(f"depth: {c.depth} → {d.set_depth}")
        c.depth = d.set_depth
    if d.set_rates_override is not None:
        merged = c.rates_override.model_copy(update=d.set_rates_override.model_dump(exclude_none=True))
        if merged != c.rates_override:
            c.rates_override = merged
            log.append("rates: " + ", ".join(f"{k}={v}" for k, v in merged.model_dump(exclude_none=True).items()))
    if d.set_race_settings is not None and d.set_race_settings != c.race_settings:
        c.race_settings = d.set_race_settings
        log.append(f"race: {d.set_race_settings.surface}, +{d.set_race_settings.extra_load_kg:g} kg")
    if d.choose_from_make and d.choose_from_make.strip() and d.choose_from_make.strip() != c.wanted_make:
        c.wanted_make = d.choose_from_make.strip()
        log.append(f"make to choose from: {c.wanted_make}")


def _apply_constraints(c: CaseFile, d: CaseDelta, log: list[str]) -> None:
    """Budget (amount, intent, currency, kind), running-cost limit and usage needs (spec 003 FR-018)."""
    _apply_budget(c, d, log)
    if d.set_running_cost_limit is not None and d.set_running_cost_limit != c.running_cost_limit:
        c.running_cost_limit = d.set_running_cost_limit
        c.basis["monthly_limit"] = _basis(d, "monthly_limit")  # type: ignore[assignment]
        log.append(f"running cost limit: €{d.set_running_cost_limit.amount_eur:,.0f} per "
                   f"{d.set_running_cost_limit.period.lower()}")  # fmt: skip
    if d.set_needs is not None:
        needs = c.needs.model_copy(update=d.set_needs.model_dump(exclude_unset=True))
        if needs != c.needs:
            c.needs = needs
            log.append("needs: " + ", ".join(f"{k}={v}" for k, v in needs.model_dump(exclude_none=True).items()))


def _apply_budget(c: CaseFile, d: CaseDelta, log: list[str]) -> None:
    if d.set_budget is not None and d.set_budget != c.budget:
        new = d.set_budget
        if new.max_eur is None and c.budget.max_eur is not None:  # an intent-only answer keeps the amount
            new = c.budget.model_copy(update={"intent": new.intent} if new.intent != "UNKNOWN" else {})
        if new != c.budget:
            if new.max_eur != c.budget.max_eur:
                log.append(f"budget: {_money(c.budget.max_eur)} → {_money(new.max_eur)}")
            if new.intent != c.budget.intent:
                log.append(f"budget for: {new.intent.lower()}")
            c.budget = new
        if new.max_eur is not None:
            c.basis["budget"] = _basis(d, "budget")  # type: ignore[assignment]
        if new.intent != "UNKNOWN":
            c.basis["condition"] = _basis(d, "condition")  # type: ignore[assignment]


def _apply_priorities(c: CaseFile, d: CaseDelta, log: list[str]) -> None:
    for pc in d.add_priorities:
        existing = next((p for p in c.priorities if p.criterion == pc.criterion), None)
        if existing is None:
            c.priorities.append(Priority(criterion=pc.criterion, strength=pc.strength, source="USER"))
            log.append(f"priority added: {pc.criterion} ({pc.strength})")
        elif existing.strength != pc.strength or existing.source != "USER":
            if existing.strength != pc.strength:
                log.append(f"priority {pc.criterion}: {existing.strength} → {pc.strength}")
            existing.strength, existing.source = pc.strength, "USER"
    for key in d.remove_priorities:
        if any(p.criterion == key for p in c.priorities):
            c.priorities = [p for p in c.priorities if p.criterion != key]
            log.append(f"priority removed: {key}")


def _age_year(year: int | None, age: int | None, current_year: int) -> tuple[int | None, int | None]:
    if year is None and age is not None:
        year = current_year - age
    if age is None and year is not None:
        age = max(0, current_year - year)
    return year, age


def _describe(car: CaseCar) -> str:
    bits: list[str] = [car.condition] if car.condition != "UNKNOWN" else []
    if car.year is not None:
        bits.append(f"~{car.year}")
    return f"{car.request_text} ({', '.join(bits)})" if bits else car.request_text


def _identity(car: CaseCar) -> tuple[object, ...]:
    return (
        (car.make or "").lower(),
        (car.model or "").lower(),
        car.condition,
        car.year,
        car.mileage_km,
        car.constraints.model_dump(exclude_none=True),
    )


def _same_request(car: CaseCar, ref: CarRef, year: int | None) -> bool:
    if not (ref.make and ref.model):
        return car.request_text.strip().lower() == ref.request_text.strip().lower()
    return (
        (car.make or "").lower() == ref.make.lower()
        and (car.model or "").lower() == ref.model.lower()
        and car.condition == ref.condition
        and car.year == year
        and car.constraints == ref.constraints
    )


def _apply_cars(c: CaseFile, d: CaseDelta, log: list[str], current_year: int) -> None:
    for key in d.remove_cars:
        removed = c.car(key)
        c.cars = [x for x in c.cars if x.key != key]
        log.append(f"{key} removed: {removed.request_text}")
        if c.prediction is not None and c.prediction.winner_key == key:
            c.prediction = None
    for ctx in d.replace_cars:
        _replace(c, ctx, log, current_year)
    for ctx in d.set_car_context:
        _set_context(c, ctx, log, current_year)
    for ref in d.add_cars:
        year, age = _age_year(ref.year, ref.age_years, current_year)
        if any(_same_request(x, ref, year) for x in c.cars):
            continue  # the user repeated a car that is already in the case
        key = f"car#{c.next_car_no}"
        c.next_car_no += 1
        c.cars.append(CaseCar(key=key, **ref.model_dump(exclude={"year", "age_years"}), year=year, age_years=age))
        c.intake.card_confirmed = False  # spec 005: a new car is confirmed on the card like the others
        log.append(f"{key} added: {ref.request_text}")


def _replace(c: CaseFile, ctx: CarContext, log: list[str], current_year: int) -> None:
    old = c.car(ctx.target_key)
    make = ctx.make if ctx.make is not None else old.make
    model = ctx.model if ctx.model is not None else old.model
    # The same make and model restated with fewer details keeps the known context (age, mileage):
    # "I meant the used 150" must not forget that it is ~10 years old.
    same_line = (make or "").lower() == (old.make or "").lower() and (model or "").lower() == (old.model or "").lower()
    year, age = _age_year(ctx.year, ctx.age_years, current_year)
    if same_line and year is None:
        year, age = old.year, old.age_years
    new = CaseCar(
        key=old.key,
        request_text=ctx.request_text or old.request_text,
        make=make,
        model=model,
        condition=ctx.condition or old.condition,
        year=year,
        age_years=age,
        mileage_km=ctx.mileage_km if ctx.mileage_km is not None or not same_line else old.mileage_km,
        constraints=ctx.constraints or (old.constraints if same_line else Constraints()),
    )
    if _identity(new) == _identity(old):
        return  # the same car again (e.g. "I meant the used 150"): nothing to change
    new.previous_label = old.label or old.previous_label
    c.intake.card_confirmed = False
    c.cars[c.cars.index(old)] = new
    log.append(f"{old.key} replaced: {old.request_text} → {_describe(new)}")


def _set_context(c: CaseFile, ctx: CarContext, log: list[str], current_year: int) -> None:
    car = c.car(ctx.target_key)
    before = _identity(car)
    changes = _context_changes(car, ctx, current_year)
    if _identity(car) != before:
        _forget_variant(c, car)
    if changes:
        log.append(f"{car.key}: " + ", ".join(changes))


def _forget_variant(c: CaseFile, car: CaseCar) -> None:
    """A correction changes the car (spec 005 FR-013): the resolved version is dropped (kept as previous_label for
    "before → after"), the car is identified again and the confirmation card must be confirmed again."""
    if car.label:
        car.previous_label = car.label
    car.variant_id, car.label, car.resolution, car.alternatives = None, None, "UNRESOLVED", []
    car.identify = None
    car.chosen_for_me = False  # spec 008: a correction opens the levels again; "choose for me" was for the old ones
    c.intake.card_confirmed = False


def _context_changes(car: CaseCar, ctx: CarContext, current_year: int) -> list[str]:
    """Mutate `car` with the context and describe each change."""
    changes: list[str] = []
    if ctx.condition is not None and ctx.condition != car.condition:
        changes.append(f"condition {car.condition} → {ctx.condition}")
        car.condition = ctx.condition
    if ctx.year is not None or ctx.age_years is not None:
        year, age = _age_year(ctx.year, ctx.age_years, current_year)
        if year != car.year:
            changes.append(f"year {year}")
        car.year, car.age_years = year, age
        car.year_assumed = False  # spec 008: a year the user gives replaces an assumed one
    if ctx.mileage_km is not None and ctx.mileage_km != car.mileage_km:
        car.mileage_km = ctx.mileage_km
        changes.append(f"mileage {ctx.mileage_km:,} km")
    if ctx.constraints is not None:
        hints = ctx.constraints.model_dump(exclude_none=True)
        merged = Constraints.model_validate({**car.constraints.model_dump(), **hints})
        if merged != car.constraints:
            car.constraints = merged
            changes.append("hints " + ", ".join(f"{k}={v}" for k, v in hints.items()))
    for attr in ("make", "model"):
        val = getattr(ctx, attr)
        if val is not None and val != getattr(car, attr):
            setattr(car, attr, val)
            changes.append(f"{attr} {val}")
    return changes


def set_weights(case: CaseFile, raw: dict[str, float]) -> CaseFile:
    """User weight edit (FR-026): validate keys, reject negatives, normalize to 100."""
    unknown = [k for k in raw if k not in CRITERION_KEYS]
    if unknown:
        raise ValueError(f"unknown criteria: {', '.join(unknown)}")
    if any(v < 0 for v in raw.values()):
        raise ValueError("weights must be ≥ 0")
    total = sum(raw.values())
    if total <= 0:
        raise ValueError("at least one weight must be > 0")
    c = case.model_copy(deep=True)
    c.weights = {k: round(v * 100 / total, 4) for k, v in raw.items()}
    c.weights_overridden = True
    return c
