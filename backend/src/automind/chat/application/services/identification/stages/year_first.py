"""Stage year_first: a used car's year is asked once, with the identity questions (spec 008 FR-021); not given after
that ask, it is assumed — from the mileage, else the middle of the generation the hint names, else the default —
and shown as assumed everywhere it is used (FR-022)."""

from __future__ import annotations

from automind.chat.application.ports import Ports
from automind.chat.application.services.identification.stages.narrow_ladder import intake_cfg, spans
from automind.chat.application.services.identification.stages.settle import settle
from automind.chat.domain.case import CaseCar, CaseFile, IdentifyOutcome
from automind.chat.domain.identification import used


def year_first(ports: Ports, case: CaseFile, car: CaseCar, now: int) -> IdentifyOutcome | None:
    """The year asked (an outcome), or None: not needed, or assumed now."""
    if car.condition != "USED" or car.year is not None or car.age_years is not None:
        return None
    if car.constraints.generation_hint:
        return None
    if case.intake.attempt(car.key, "YEAR") < 1:
        return settle(car, IdentifyOutcome(outcome="NEED", need="YEAR"))
    _assume_year(ports, car, now)
    return None


def _assume_year(ports: Ports, car: CaseCar, now: int) -> None:
    cfg = intake_cfg(ports)
    span = spans(ports, car).get((car.constraints.generation_hint or "").lower(), (None, None))
    age, _ = used.assumed_age(car.mileage_km, span[0], span[1], now,
                              km_per_year=int(cfg.get("km_per_year_used", used.KM_PER_YEAR_USED)),
                              default=int(cfg.get("default_used_age", used.DEFAULT_USED_AGE)))  # fmt: skip
    car.year, car.age_years, car.year_assumed = now - age, age, True
