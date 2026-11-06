"""Stage narrow_ladder (spec 008): one step of the identification ladder — generation → engine → gearbox → driven
wheels — over a pool of versions (sourced, or catalogue rows in the fallback). A newer answer wins over an older
one; the levels the hub settled are written as the car's facts with their origin; a level still open is asked
with its options. The domain `ladder` decides; this stage reads and writes the car."""

from __future__ import annotations

from typing import Any

from automind.chat.application.ports import Ports
from automind.chat.application.services.identification.stages.settle import settle
from automind.chat.domain.case import CaseCar, CaseFile, Choice, IdentifyOutcome, LadderMemo
from automind.chat.domain.identification import ladder
from automind.chat.domain.identification.variant_match import current_generation
from automind.shared.vehicle import identity
from automind.shared.vehicle.engine import EngineHint

Events = list[dict[str, str]]


def reconcile(ports: Ports, car: CaseCar) -> Events:
    """A newer answer wins over an older one; levels the hub filled below a changed level are opened again."""
    memo = car.ladder
    if memo is None:
        return []
    r = ladder.reconcile(memo.levels, _levels(car, wanted(car)), memo.origin, spans(ports, car))
    k = car.constraints
    for lvl in r.clear:
        memo.origin.pop(lvl, None)
        _clear(car, lvl)
    for lvl in r.changed:  # the user's own value now, whoever had filled it before
        memo.origin.pop(lvl, None)
    if k.engine_hint is not None and k.engine_hint.empty():
        k.engine_hint = None
    if r.drop == "YEAR":
        car.year, car.age_years, car.year_assumed = None, None, False
    elif r.drop == "GENERATION":
        k.generation_hint = None
    return [{"kind": "level_replaced", **{a: str(b) for a, b in r.note.items()}}] if r.note else []


def decide(ports: Ports, case: CaseFile, car: CaseCar, pool: list[ladder.Version], memo: LadderMemo,
           events: Events) -> ladder.Decision:  # fmt: skip
    """One ladder step over `pool`; the levels the hub settled are written with their origin."""
    cfg = intake_cfg(ports)
    asks = {i: case.intake.attempt(car.key, i) for i in ladder.ITEMS}
    before = wanted(car)
    d = ladder.decide(pool, before, asks, limit=int(cfg["max_attempts_per_item"]), chosen=car.chosen_for_me)
    if d.auto:
        old = _levels(car, before)
        _write(car, d.wanted)
        for lvl, val in _levels(car, d.wanted).items():
            if old.get(lvl) != val:
                memo.origin[lvl] = d.auto[0].origin
        events += [{"kind": "settled_by_rule", "label": a.label} for a in d.auto if a.origin == "LIMIT"]
    memo.levels = _levels(car, wanted(car))
    return d


def asked(car: CaseCar, d: ladder.Decision, events: Events) -> IdentifyOutcome:
    """The open level asked with its options."""
    step = d.step
    choices = [choice(car, o) for o in step.options]
    return settle(car, IdentifyOutcome(outcome="CHOICES", need=ladder.ITEM[step.kind], level=step.kind,  # type: ignore[arg-type]
                                       choices=choices, missing=d.missing, events=events))  # fmt: skip


def choice(car: CaseCar, o: ladder.Option) -> Choice:
    return Choice(label=o.label, make=car.make, model=car.model, engine=o.engine, level=o.level, fuel=o.fuel,
                  engine_cc=o.engine_cc, family=o.family, power_kw=o.power_kw, gearbox=o.gearbox,
                  drive=o.drive)  # fmt: skip


def wanted(car: CaseCar) -> ladder.Wanted:
    k = car.constraints
    words = " ".join(x for x in (car.model or "", car.request_text or "", k.trim_hint or "") if x)
    return ladder.wanted_of(k.engine_hint, engine=k.version_hint, gearbox=k.gearbox_hint, drive=k.drive_hint,
                            year=car.year if car.condition == "USED" else None, words=words)  # fmt: skip


def generation_of(ports: Ports, car: CaseCar, year: int) -> str | None:
    """The generation the facts name: the user's, the one on sale (new), or the only one built in the year."""
    if car.constraints.generation_hint:
        return car.constraints.generation_hint
    if car.condition != "USED":
        cur = current_generation(ports.ref, car, year)
        return cur[0] if cur else None
    gens = (getattr(ports.ref, "generations", None) or {}).get(f"{car.make}|{car.model}", [])
    built = [str(g) for g, lo, hi in gens
             if lo is not None and car.year and identity.generation_matches(car.year, lo, hi)]  # fmt: skip
    return built[0] if len(built) == 1 else None


def others(versions: list[ladder.Version], year: int | None, chosen: ladder.Version) -> list[str]:
    """Up to four other versions of the same generation (and year) for the card's engine chips."""
    pool = ladder.narrow(versions, ladder.Wanted(year=year)).versions
    out: list[str] = []
    for v in pool:
        if v.engine_key != chosen.engine_key and v.engine not in out:
            out.append(v.engine)
    return out[:4]


def spans(ports: Ports, car: CaseCar) -> dict[str, tuple[int | None, int | None]]:
    """The years of the model's generations (config, and the one the ladder found)."""
    gens = (getattr(ports.ref, "generations", None) or {}).get(f"{car.make}|{car.model}", [])
    out = {str(g).lower(): (lo, hi) for g, lo, hi in gens}
    m = car.ladder
    if m is not None and m.generation:
        out.setdefault(m.generation.lower(), (m.generation_from, m.generation_to))
    return out


def intake_cfg(ports: Ports) -> dict[str, Any]:
    """config/search.yaml `intake`: ask limits, assumed ages, catalogue staleness."""
    return dict((getattr(ports.ref, "search", None) or {}).get("intake") or {})


def _levels(car: CaseCar, w: ladder.Wanted) -> dict[str, str]:
    return ladder.levels_of(car.year, car.year_assumed, car.constraints.generation_hint, w)


def _clear(car: CaseCar, lvl: str) -> None:
    """Open one level again (a value the hub filled, below a level the user changed)."""
    k, e = car.constraints, car.constraints.engine_hint
    if lvl in ("ENGINE", "POWER"):
        k.version_hint = None
    if lvl == "GEARBOX":
        k.gearbox_hint = None
    elif lvl == "DRIVE":
        k.drive_hint = None
    elif e is not None and lvl == "FUEL":
        e.fuel = None
    elif e is not None and lvl == "ENGINE":
        e.displacement_l, e.family = None, None
    elif e is not None and lvl == "POWER":
        e.power_kw, e.power_hp = None, None


def _write(car: CaseCar, w: ladder.Wanted) -> None:
    """The levels the hub settled are written as the car's facts (with their origin in the memo)."""
    k = car.constraints
    if any((w.fuel, w.displacement_l, w.family, w.power_kw)):
        k.engine_hint = EngineHint(fuel=w.fuel, displacement_l=w.displacement_l,  # type: ignore[arg-type]
                                   family=(w.family or "")[:16] or None, power_kw=w.power_kw,
                                   power_hp=round(w.power_kw / 0.7355) if w.power_kw else None,
                                   evidence=(k.engine_hint.evidence if k.engine_hint else ""))  # fmt: skip
    k.version_hint = w.engine or k.version_hint
    k.gearbox_hint = w.gearbox or k.gearbox_hint  # type: ignore[assignment]
    k.drive_hint = w.drive or k.drive_hint  # type: ignore[assignment]
