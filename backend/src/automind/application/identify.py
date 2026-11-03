"""Identify step (spec 005 R1, R2, R10): every intake turn, each unsettled or changed car is identified again from
its current facts — make registry → known models (catalog, config, line-up) → catalog fit → resolver with sources.

Outcome per car (`IdentifyOutcome`):
- IDENTIFIED: nothing to ask about the identity (a variant is set, or the catalog has candidates to confirm);
- CHOICES: concrete options to pick from (models of the make, versions, engines);
- NEED: one named item is missing (MAKE, MODEL, ENGINE, YEAR …);
- NOT_FOUND: looked up and not found; `checked` names what was looked at, `choices` the closest real names.

Never raises UnknownModel to the caller; the policy asks with concrete options instead (FR-009).
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections.abc import Awaitable, Callable
from typing import Any

from automind.application import resolve
from automind.application.ports import Ports
from automind.domain import intake
from automind.domain.casefile import CaseCar, CaseFile, Choice, IdentifyOutcome

LineupLookup = Callable[[Ports, str], Awaitable[Any]]  # (ports, make) -> application.lineup.Lineup | None


def _plain(s: str | None) -> str:
    return unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()


def key_of(car: CaseCar) -> str:
    return hashlib.sha1(repr(intake.identity_key(car)).encode()).hexdigest()[:12]


def needs_identify(car: CaseCar) -> bool:
    """Run the identify step for this car? Not for a car identified with the same facts, nor for a car confirmed
    before spec 005 (no outcome recorded)."""
    o = car.identify
    if o is None:
        return not (car.variant_id and car.resolution in ("CONFIRMED", "AUTO_OK"))
    return o.outcome != "IDENTIFIED" or o.key != key_of(car)


def _lineup_models(lineup: Any) -> list[Any]:
    return list(getattr(lineup, "models", None) or [])


def _choices_from_lineup(lineup: Any, make: str) -> list[Choice]:
    out = []
    for m in _lineup_models(lineup)[:6]:
        pts = ", ".join(m.powertrains) if getattr(m, "powertrains", None) else None
        bits = ", ".join(x for x in (getattr(m, "body", "") or "", pts or "") if x)
        out.append(Choice(label=f"{make} {m.model}" + (f" ({bits})" if bits else ""), make=make, model=m.model,
                          body=getattr(m, "body", None) or None, powertrain=pts,
                          source_url=getattr(m, "source_url", None),
                          price_from_eur=getattr(m, "price_from_eur", None)))  # fmt: skip
    return out


def _strip_make(text: str, make: str, aliases: list[str]) -> str:
    low = text
    for a in sorted({make.lower(), *aliases}, key=len, reverse=True):
        low = re.sub(rf"(?i)(?<![\w]){re.escape(a)}(?![\w])", " ", low)
    return " ".join(low.split())


async def identify_car(
    ports: Ports, case: CaseFile, car: CaseCar, current_year: int, lineup_lookup: LineupLookup | None = None
) -> IdentifyOutcome:
    """Identify one car in place (make/model canonical, variant proposed when found) and return the outcome."""
    reg = ports.ref.makes
    if reg is not None:
        canon = reg.canonical(car.make) if car.make else reg.match_make(car.request_text)
        if canon and _plain(canon) != _plain(car.make):  # "Skoda" / "Škoda": keep the catalog's spelling
            car.make = canon
    if not car.make:
        return _done(car, IdentifyOutcome(outcome="NEED", need="MAKE"))
    lineup = await lineup_lookup(ports, car.make) if lineup_lookup is not None else None
    known = set(await resolve.known_models(car.make, ports.ref)) | {m.model for m in _lineup_models(lineup)}
    _match_model(car, reg, known)
    if not car.model:
        choices = _choices_from_lineup(lineup, car.make) or [
            Choice(label=f"{car.make} {m}", make=car.make, model=m) for m in sorted(known)[:6]
        ]
        kind = "CHOICES" if choices else "NEED"
        return _done(car, IdentifyOutcome(outcome=kind, need="MODEL", choices=choices))  # type: ignore[arg-type]
    if car.variant_id and car.resolution in ("CONFIRMED", "AUTO_OK", "PROPOSED"):
        return _done(car, IdentifyOutcome(outcome="IDENTIFIED"))
    if car.condition == "USED" and car.year is None and car.age_years is None and not car.constraints.generation_hint:
        return _done(car, IdentifyOutcome(outcome="IDENTIFIED"))  # the age is asked first (USED_AGE), then resolved
    a = await resolve.assess_car(car, ports.ref, current_year, case.compare_level)
    if a.candidates:
        resolve.auto_resolve(car, a)
        return _done(car, IdentifyOutcome(outcome="IDENTIFIED"))
    return await _resolve_open(ports, case, car, current_year, lineup)


def _match_model(car: CaseCar, reg: Any, known: set[str]) -> None:
    """The model in any script or spelling, mapped to a known one ("атека" → Ateca, "сил ю" → Seal U)."""
    if reg is None or not known or not car.make:
        return
    if not car.model:
        aliases = [n for n, c in reg.names.items() if c == car.make]
        rest = _strip_make(car.request_text, car.make, aliases)
        if rest and (m := reg.match_model(rest, known)):
            car.model = m
    elif car.model not in known and (m := reg.match_model(car.model, known)):
        car.model = m


async def _resolve_open(ports: Ports, case: CaseFile, car: CaseCar, year: int, lineup: Any) -> IdentifyOutcome:
    """Catalog miss: the resolver with sources; a model of the make's line-up is known even without a generation."""
    try:
        v, ident = await resolve.resolve_with_llm(ports, car, year, case.compare_level, lineup=lineup)
    except resolve.GenerationMismatch as e:
        return _done(car, IdentifyOutcome(outcome="NEED", need="YEAR", note=str(e)))
    except resolve.UnknownModel as e:
        names = e.closest or [f"{car.make} {m.model}" for m in _lineup_models(lineup)[:6]]
        choices = [Choice(label=n, make=car.make, model=n.removeprefix(f"{car.make} ")) for n in names]
        car.resolution, car.variant_id, car.label = "UNRESOLVED", None, None
        return _done(car, IdentifyOutcome(outcome="NOT_FOUND", need="MODEL", choices=choices, checked=e.checked))
    car.variant_id, car.label, car.resolution = v.id, v.label, "PROPOSED"
    return _done(car, IdentifyOutcome(outcome="IDENTIFIED", note=ident.note))


def _done(car: CaseCar, o: IdentifyOutcome) -> IdentifyOutcome:
    o.key = key_of(car)
    car.identify = o
    return o
