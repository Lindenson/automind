"""A structured "Change" on a car (spec 010 FR-037, spec 017 C1): the case delta of an edit of the generation,
engine, gearbox or trim, of "not this car" or of a removal — built by code; "not this car" may carry the
interpreter's reading of the words (`another_car`). Raises ValueError for an unknown field or a value it cannot take,
KeyError for an unknown car."""

from __future__ import annotations

from collections.abc import Callable

from automind.chat.application.services.report.blocks.car_view import gearbox_kind
from automind.chat.domain.case import CarContext, CarRef, CaseCar, CaseDelta, CaseFile, Constraints
from automind.shared.vehicle.identity import parse_engine

EDIT_FIELDS = ("generation", "engine", "gearbox", "trim", "not_this_car", "remove")
MakeMatcher = Callable[[str], str | None]  # the make a text names (`MakeNames.match_make`)


def edit_delta(
    case: CaseFile, car_key: str, field: str, value: str, match_make: MakeMatcher | None = None
) -> CaseDelta:
    """A structured car edit as a case delta, built by code (FR-037). Raises ValueError for an unknown car or
    field, or a value the field cannot take."""
    car = case.car(car_key)
    v = value.strip()[:120]
    if field == "remove":
        return CaseDelta(remove_cars=[car.key])
    if field == "not_this_car":
        return CaseDelta(replace_cars=[another_car(car, v, None, match_make)])
    if not v:
        raise ValueError(f"{field}: a value is needed")
    k = _constraints(car.constraints.model_copy(deep=True), field, v)
    if k == car.constraints:
        raise ValueError(f"{field}: unchanged")
    return CaseDelta(replace_cars=[CarContext(target_key=car.key, constraints=k)])


def named_text(car: CaseCar, value: str, match_make: MakeMatcher | None) -> str:
    """The words of "not this car" as a car description: the old car's make put in front when the words name no make
    ("320 d" on a BMW is "BMW 320 d")."""
    v = value.strip()[:120]
    named = match_make(v) if match_make is not None and v else None
    return v if named or not car.make else f"{car.make} {v}"


def another_car(car: CaseCar, value: str, read: CarRef | None, match_make: MakeMatcher | None = None) -> CarContext:
    """ "Not this car" (FR-037, spec 017 C1): the car the words name replaces `car`; the purchase the person
    described stays — condition, year and mileage are kept unless the words state them (chat 725e7437: "320 d"
    lost the year 2024 and became the model "320 d"). `read` is the interpreter's reading of `named_text`
    (model line, engine, fuel); without it the words are split by code (make, then the rest as the model)."""
    v = value.strip()[:120]
    if read is None:
        make = (match_make(v) if match_make is not None and v else None) or car.make
        read = CarRef(request_text=v or make or car.request_text, make=make, model=_model_words(v, make) or None)
    stated_year = read.year is not None or read.age_years is not None
    return CarContext(
        target_key=car.key,
        request_text=v or read.request_text,
        make=read.make or car.make,
        model=read.model,
        condition=read.condition if read.condition != "UNKNOWN" else car.condition,
        year=read.year if stated_year else car.year,
        age_years=read.age_years if stated_year else (None if car.year else car.age_years),
        mileage_km=read.mileage_km if read.mileage_km is not None else car.mileage_km,
        constraints=read.constraints.model_copy(deep=True),
    )


def _constraints(k: Constraints, field: str, v: str) -> Constraints:
    if field == "generation":
        k.generation_hint, k.version_hint = v, None
    elif field == "engine":
        e = parse_engine(v)
        if e is None:
            raise ValueError(f"not an engine: {v}")
        k.engine_hint, k.version_hint = e, None
        if k.trim_hint and parse_engine(k.trim_hint) is not None:  # an engine in the trim words is the old engine
            k.trim_hint = None
    elif field == "gearbox":
        k.gearbox_hint = gearbox_kind(v)
    elif field == "trim":
        k.trim_hint = v
    else:
        raise ValueError(f"unknown field: {field}")
    return k


def _model_words(text: str, make: str | None) -> str:
    words = text.split()
    if make:
        mk = make.lower().split()
        if [w.lower() for w in words[: len(mk)]] == mk:
            words = words[len(mk) :]
    return " ".join(words)[:60]
