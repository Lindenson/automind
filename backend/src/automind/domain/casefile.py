"""Case file: the structured, versioned understanding of the user and the task (FR-002; R3, R4).

`apply(case, delta)` is the only way the hub changes the case. It is pure and deterministic,
returns a new case plus a human-readable change log, and the latest explicit statement wins
(FR-003). The LLM proposes a typed `CaseDelta`; code validates and applies it.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

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
Usage = Literal["CITY", "MOTORWAY", "MOUNTAINS", "OFFROAD", "TRACK", "FAMILY"]
Depth = Literal["QUICK", "STANDARD", "DEEP"]
Condition = Literal["NEW", "USED", "UNKNOWN"]
Resolution = Literal["UNRESOLVED", "PROPOSED", "CONFIRMED", "AUTO_OK"]
Strength = Literal["LOW", "MEDIUM", "HIGH"]
QuestionKind = Literal["TOO_MANY_CARS", "CAR_IDENTITY", "USED_AGE", "TRIM", "PERSONA"]

MAX_CARS = 3


class Profile(BaseModel):
    age: int | None = Field(default=None, ge=14, le=100)
    experience: str | None = None


class Budget(BaseModel):
    max_eur: int | None = Field(default=None, ge=0)
    note: str | None = None


class Rates(BaseModel):
    fuel_eur_per_l: float | None = Field(default=None, gt=0)
    diesel_eur_per_l: float | None = Field(default=None, gt=0)
    electricity_eur_per_kwh: float | None = Field(default=None, gt=0)
    labour_eur_per_h: float | None = Field(default=None, gt=0)


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


class Constraints(BaseModel):
    generation_hint: str | None = None
    fuel_hint: str | None = None
    body_hint: str | None = None
    trim_hint: str | None = None
    url: str | None = None


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


class Pending(BaseModel):
    kind: Literal["QUESTIONS", "CONFIRM_VARIANTS", "CONFIRM_COST"]
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
    annual_km: int = Field(default=15000, ge=1000, le=200000)
    rates_override: Rates = Field(default_factory=Rates)
    depth: Depth = "STANDARD"
    priorities: list[Priority] = Field(default_factory=list)
    weights: dict[str, float] = Field(default_factory=dict)
    weights_overridden: bool = False
    unmapped_wishes: list[str] = Field(default_factory=list)
    cars: list[CaseCar] = Field(default_factory=list)
    next_car_no: int = 1
    race_settings: RaceSettings | None = None
    prediction: Prediction | None = None
    asked: list[QuestionKind] = Field(default_factory=list)  # question kinds already asked (one round, FR-005)
    declined_plan: str | None = None  # research plan the user declined; not offered again until it changes
    pending: Pending | None = None
    shown: list[Shown] = Field(default_factory=list)

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
    set_profile: Profile | None = None
    set_usage: list[Usage] | None = None
    set_budget: Budget | None = None
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


def _apply_persona_profile(c: CaseFile, d: CaseDelta, log: list[str]) -> None:
    p = d.set_persona
    weak_over_edit = p is not None and p.source == "INFERRED" and c.persona_source == "USER_EDIT"
    if p is not None and not weak_over_edit and (p.persona != c.persona or p.source != c.persona_source):
        if p.persona != c.persona:
            log.append(f"persona: {c.persona} → {p.persona}")
        c.persona, c.persona_source = p.persona, p.source
    if d.set_profile is not None:
        if d.set_profile.age is not None and d.set_profile.age != c.profile.age:
            c.profile.age = d.set_profile.age
            log.append(f"age: {c.profile.age}")
        if d.set_profile.experience and d.set_profile.experience != c.profile.experience:
            c.profile.experience = d.set_profile.experience
            log.append(f"experience: {c.profile.experience}")


def _money(v: int | None) -> str:
    return "none" if v is None else f"≤ €{v:,}"


def _apply_settings(c: CaseFile, d: CaseDelta, log: list[str]) -> None:
    if d.set_usage is not None and d.set_usage != c.usage:
        c.usage = list(dict.fromkeys(d.set_usage))
        log.append("usage: " + ", ".join(c.usage))
    if d.set_budget is not None and d.set_budget != c.budget:
        log.append(f"budget: {_money(c.budget.max_eur)} → {_money(d.set_budget.max_eur)}")
        c.budget = d.set_budget
    if d.set_annual_km is not None and d.set_annual_km != c.annual_km:
        log.append(f"annual mileage: {c.annual_km:,} → {d.set_annual_km:,} km")
        c.annual_km = d.set_annual_km
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
    c.cars[c.cars.index(old)] = new
    log.append(f"{old.key} replaced: {old.request_text} → {_describe(new)}")


def _set_context(c: CaseFile, ctx: CarContext, log: list[str], current_year: int) -> None:
    car = c.car(ctx.target_key)
    before = _identity(car)
    changes = _context_changes(car, ctx, current_year)
    if _identity(car) != before:
        car.variant_id, car.label, car.resolution, car.alternatives = None, None, "UNRESOLVED", []
    if changes:
        log.append(f"{car.key}: " + ", ".join(changes))


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
    if ctx.mileage_km is not None and ctx.mileage_km != car.mileage_km:
        car.mileage_km = ctx.mileage_km
        changes.append(f"mileage {ctx.mileage_km:,} km")
    if ctx.constraints is not None:
        hints = ctx.constraints.model_dump(exclude_none=True)
        merged = car.constraints.model_copy(update=hints)
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
