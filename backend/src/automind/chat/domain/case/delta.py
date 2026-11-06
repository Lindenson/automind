"""Changes to a case: the delta the interpreter proposes (a typed, validated LLM output) and `apply`, the only code
that changes a case (FR-003), plus profile defaults."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from automind.chat.domain.case.car import CaseCar, Constraints
from automind.chat.domain.case.casefile import CaseFile, Prediction, RaceSettings
from automind.chat.domain.case.enums import Condition, CriterionKey, Depth, Persona, PersonaSource, Strength, Usage
from automind.chat.domain.case.person import Budget, Needs, Priority, Profile, Rates, RunningLimit


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
