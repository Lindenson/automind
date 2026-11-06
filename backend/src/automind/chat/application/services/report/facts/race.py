"""The drag race inputs of a car and the race of the compared cars (spec 001: deterministic simulation)."""

from __future__ import annotations

from automind.chat.application.services.report.facts.car import num, txt
from automind.chat.domain.assessment import dragrace


def race_inputs(car: dict) -> dragrace.CarInput:
    v = car["variant"]
    return dragrace.CarInput(
        car_id=v.id,
        label=v.label,
        powertrain=v.powertrain,
        power_kw=num(car, "max_power"),
        mass_kg=num(car, "curb_mass"),
        drivetrain=txt(car, "drivetrain"),
        transmission=txt(car, "transmission"),
        top_speed_kmh=num(car, "top_speed"),
        body_class=v.body_class,
        claimed_0_100=num(car, "claimed_0_100"),
    )


def run_race(cars: list[dict], settings: dict | None = None) -> dragrace.RaceResult:
    st = {k: v for k, v in (settings or {}).items() if v is not None}
    return dragrace.simulate([race_inputs(c) for c in cars], dragrace.RaceSettings(**st))
