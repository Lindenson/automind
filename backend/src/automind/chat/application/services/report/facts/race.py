"""The drag race inputs of a car and the race of the compared cars (spec 001: deterministic simulation)."""

from __future__ import annotations

from collections.abc import Mapping

from automind.chat.application.services.report.contracts import LoadedCar
from automind.chat.application.services.report.facts.car import num, txt
from automind.chat.domain.assessment import dragrace


def race_inputs(car: LoadedCar) -> dragrace.CarInput:
    """The car's facts the race simulates with (power, weight, gearbox, tyres, claimed times)."""
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


def run_race(cars: list[LoadedCar], settings: Mapping[str, str | float | None] | None = None) -> dragrace.RaceResult:
    """The drag race of the cars (the case's race settings; a setting not given takes the race's default)."""
    return dragrace.simulate([race_inputs(c) for c in cars], _settings(settings or {}))


def _settings(given: Mapping[str, str | float | None]) -> dragrace.RaceSettings:
    base = dragrace.RaceSettings()

    def pick(key: str, default: str | float) -> str | float:
        value = given.get(key)
        return default if value is None else value

    return dragrace.RaceSettings(surface=str(pick("surface", base.surface)),
                                 extra_load_kg=float(pick("extra_load_kg", base.extra_load_kg)),
                                 temperature_c=float(pick("temperature_c", base.temperature_c)),
                                 altitude_m=float(pick("altitude_m", base.altitude_m)))  # fmt: skip
