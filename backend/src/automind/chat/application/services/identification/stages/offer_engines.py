"""Stage offer_engines: when the version named does not exist (another generation, no such engine) the catalogued
versions of the model that fit the car without the engine named are offered, each with its variant so a tap
identifies it (spec 007 F, spec 005 FR-015); an option naming a generation not built in the car's year never is
(chat 9b5c0b0c). A model the resolver could not place is offered the make's line-up instead."""

from __future__ import annotations

import re

from automind.chat.application.ports import Ports
from automind.chat.application.services.identification.catalogue import find_variants
from automind.chat.application.services.identification.contracts import Lineup
from automind.chat.application.services.identification.stages.place_market import lineup_models
from automind.chat.domain.case import CaseCar, Choice
from automind.chat.domain.identification.variant_match import fits, same_model
from automind.shared.contracts.config import Reference
from automind.shared.vehicle import identity

MAX_OPTIONS = 6
_GEN_TOKEN = re.compile(r"(?<![\w.])(?:[A-Z]{1,3}\d{1,3}[a-z]?|Mk\s?\d+(?:\.\d)?)(?![\w.])")  # "B5", "Mk8", "XA50"
_ENGINE_TOKEN = re.compile(r"^[VWR]\d{1,2}$")  # V6, W12: cylinders, not a generation


async def engines_on_sale(ports: Ports, car: CaseCar, year: int, alternatives: list[str]) -> list[Choice]:
    """Catalogued versions of this model that fit the car without the engine named (a new car: the generation on
    sale now); then the resolver's alternatives."""
    probe = car.model_copy(deep=True)
    probe.constraints.engine_hint = probe.constraints.trim_hint = probe.constraints.generation_hint = None
    same = await find_variants(car.make or "", car.model or "")
    fitting = sorted((v for v in same if fits(v, probe, year, ports.ref)), key=lambda v: v.label)
    out = [Choice(label=v.label, make=v.make, model=v.model, variant_id=v.id) for v in fitting
           if not year_conflict(v.label, car, ports.ref)]  # fmt: skip
    seen = {c.label.lower() for c in out}
    for a in alternatives:
        label = a if a.lower().startswith((car.make or "").lower()) else f"{car.make} {car.model} {a}"
        if label.lower() not in seen and not year_conflict(label, car, ports.ref):
            out.append(Choice(label=label, make=car.make, model=car.model))
            seen.add(label.lower())
    return out[:MAX_OPTIONS]


def year_conflict(label: str, car: CaseCar, ref: Reference | None) -> bool:
    """The option names a generation that was not built in the user's year (chat 9b5c0b0c: "Audi A4 B5 2.5 TDI"
    offered for a 2023 car). A generation config knows is checked by its years; an unknown one is a conflict
    when config knows the generation of that year (it is another one)."""
    if car.year is None or not (car.make and car.model) or ref is None:
        return False
    gens = list(ref.generations.get(f"{car.make}|{car.model}", []))
    if not gens:
        return False
    rest = re.sub(re.escape(car.model), " ", re.sub(re.escape(car.make), " ", label, flags=re.I), flags=re.I)
    years = {str(g).lower(): (lo, hi) for g, lo, hi in gens}
    of_year = any(lo is not None and identity.generation_matches(car.year, lo, hi, 1) for lo, hi in years.values())
    for tok in _GEN_TOKEN.findall(rest):
        if _ENGINE_TOKEN.match(tok):
            continue
        span = years.get(tok.lower())
        if span is not None:
            if span[0] is not None and not identity.generation_matches(car.year, span[0], span[1], 1):
                return True
        elif of_year:
            return True
    return False


def close_lineup(lineup: Lineup | None, car: CaseCar) -> list[Choice]:
    """Models of the make's line-up close to the name the user gave (the same model first)."""
    models = lineup_models(lineup)
    close = [m for m in models if same_model(car.model, m.model) or same_model(m.model, car.model)]
    rest = [m for m in models if m not in close]
    return [Choice(label=f"{car.make} {m.model}", make=car.make, model=m.model, source_url=m.source_url)
            for m in [*close, *rest][:MAX_OPTIONS]]  # fmt: skip
