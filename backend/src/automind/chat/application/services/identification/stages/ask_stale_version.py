"""Stage ask_stale_version (chats 5821ac77, 6e001ee0): only old catalogue rows for a new car and no sourced list —
the version is uncertain, asked once (its power), never taken silently. The options are the catalogue row and the
versions the EU registration datasets list besides it — a newer engine first (the facelift), by its engine size,
engine kW and years, never a power in CV the data does not give."""

from __future__ import annotations

import re

from automind.acquisition.api import DatasetVersion
from automind.chat.application.ports import Ports
from automind.chat.application.services.identification import versions
from automind.chat.application.services.identification.stages.narrow_ladder import Events, choice
from automind.chat.application.services.identification.stages.settle import settle
from automind.chat.domain.case import CaseCar, Choice, IdentifyOutcome, LadderMemo
from automind.chat.domain.identification import ladder

_POWER_WRITTEN = re.compile(r"\d\s*(cv|ps|hp|kw|ch)\b", re.IGNORECASE)  # "1.6 T-GDi 265 CV"
_SINCE = re.compile(r"·\s*(\d{4})–\s*$")  # the engine text of a registered version still on sale ("… · 2024–")


def ask_stale_version(car: CaseCar, v: ladder.Version, events: Events, found: list[DatasetVersion] | None = None,
                      pool: list[ladder.Version] | None = None) -> IdentifyOutcome:  # fmt: skip
    """The power level asked over the catalogue row `v` and the registered versions `found`; the answer or the next
    turn takes it, less certain."""
    car.ladder = car.ladder or LadderMemo()
    car.ladder.certainty = "LESS_CERTAIN"
    pool = pool or [v]
    found = found or []
    newer = newer_versions(found, pool)
    era = [x for x in found if x not in newer]
    until = next((x.years_to for x in era if _same_engine(x, v)), None)
    label = v.engine
    # the row is one version among others: its power and years tell it apart
    if found and v.power_kw and not _POWER_WRITTEN.search(label):
        label = f"{label} {round(v.power_kw / 0.7355)} CV"
    named = label  # the notice says since when it is sold
    if found and (span := ladder.years_text(v.years_from, until)):
        label = f"{label} · {span}"
    choices = [choice(car, ladder.Option("POWER", label, fuel=v.fuel, engine_cc=v.engine_cc,
                                         power_kw=v.power_kw, engine=v.engine))]  # fmt: skip
    rest = [x for x in era if not any(_same_engine(x, p) for p in pool)]
    choices[:0] = [registered_choice(car, x) for x in newer]
    choices += [registered_choice(car, x) for x in rest]
    choices = choices[: ladder.MAX_OPTIONS - 1]
    if newer:
        events.append({"kind": "version_uncertain_datasets", "label": named, "since": str(v.years_from or ""),
                       "newest": str(newer[0].years_from or "")})  # fmt: skip
    else:
        events.append({"kind": "version_uncertain", "label": named, "since": str(v.years_from or "")})
    return settle(car, IdentifyOutcome(outcome="CHOICES", need="POWER", level="POWER", choices=choices, events=events))


async def registered(ports: Ports, car: CaseCar, pool: list[ladder.Version], year: int) -> list[DatasetVersion]:
    """The model's versions registered in the EU since its catalog rows' first year, of the car's fuel."""
    fuel = (car.constraints.engine_hint.fuel if car.constraints.engine_hint else None) or next(
        (p.fuel for p in pool if p.fuel), None)  # fmt: skip
    since = min((p.years_from for p in pool if p.years_from), default=year - versions.DATASET_YEARS)
    return await versions.dataset_versions(ports, car.make or "", car.model or "", None, fuel, since)


def newer_versions(found: list[DatasetVersion], pool: list[ladder.Version]) -> list[DatasetVersion]:
    """Registered versions first registered after the catalog rows and after the model's first registered
    versions (a facelift's engine, not the first year of the data), still registered, newest first."""
    first = min((x.years_from for x in found if x.years_from), default=None)
    rows = max((p.years_from for p in pool if p.years_from), default=None)
    return [x for x in found if x.years_from and x.years_to is None and first is not None and x.years_from > first
            and (rows is None or x.years_from > rows)]  # fmt: skip


def registered_choice(car: CaseCar, x: DatasetVersion) -> Choice:
    """A registered version as an option of the power level: its label is built in the user's language from its
    facts (application/ask.py); the engine text names it for the resolver ("1.6 PHEV · engine 118 kW · 2024–")."""
    label = ladder.registered_label(x.fuel, x.displacement_cc, x.engine_kw, x.power_is_max, x.years_from,
                                    x.years_to, {})  # fmt: skip
    return Choice(label=label, make=car.make, model=car.model, engine=label, level="POWER", fuel=x.fuel,
                  engine_cc=x.displacement_cc, power_kw=x.engine_kw if x.power_is_max else None,
                  engine_kw=x.engine_kw, power_is_max=x.power_is_max, years_from=x.years_from, years_to=x.years_to,
                  source_url=x.source_url or None)  # fmt: skip


def picked_since(car: CaseCar) -> int | None:
    """The first year of the registered version the user picked (its engine text is the version hint)."""
    m = _SINCE.search(car.constraints.version_hint or "")
    return int(m.group(1)) if m else None


def _same_engine(x: DatasetVersion, v: ladder.Version) -> bool:
    """A registered version and a catalog version of the same engine (fuel, ±5 % cm3; the kW is not compared: a
    hybrid's registered kW is its combustion engine's, the catalog's the system power)."""
    if v.fuel and x.fuel != v.fuel and not ({x.fuel, v.fuel} <= {"hybrid", "mhev"}):
        return False
    return not (x.displacement_cc and v.engine_cc) or abs(x.displacement_cc - v.engine_cc) <= 0.05 * v.engine_cc
