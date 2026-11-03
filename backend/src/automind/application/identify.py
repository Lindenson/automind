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
from urllib.parse import urlparse

from automind.application import resolve
from automind.application.ports import Ports
from automind.domain import evidence, intake
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


def fit_of(case: CaseFile) -> intake.Fit:
    """What the person needs, for ranking models of a line-up (FR-008) and candidates (spec 007 US7)."""
    others = [int(p) for p in (getattr(c, "price_eur", None) for c in case.cars) if p]  # set by the caller if known
    return intake.Fit(
        family=case.profile.family == "FAMILY" or "FAMILY" in case.usage or (case.needs.passengers or 0) >= 4,
        annual_km=case.profile.annual_km_max or case.annual_km,
        priorities=tuple(p.criterion for p in case.priorities),
        budget_eur=case.budget.max_eur if case.budget.kind == "TOTAL" and case.budget.currency == "EUR" else None,
        reference_price_eur=others[0] if others else None,
    )


def _choices_from_lineup(lineup: Any, make: str, case: CaseFile | None = None) -> list[Choice]:
    """Models of the line-up as options; the 1–3 that fit the person come first, marked as suggestions with
    machine reasons (FR-008, FR-024)."""
    models = _lineup_models(lineup)
    ranked = intake.rank_lineup(models, fit_of(case)) if case is not None else []
    why = {m.model: r for m, r in ranked if r}
    order = [m for m, _ in ranked if m.model in why] + [m for m in models if m.model not in why]
    out = []
    for m in order[:6]:
        pts = ", ".join(m.powertrains) if getattr(m, "powertrains", None) else None
        bits = ", ".join(x for x in (getattr(m, "body", "") or "", pts or "") if x)
        out.append(Choice(label=f"{make} {m.model}" + (f" ({bits})" if bits else ""), make=make, model=m.model,
                          body=getattr(m, "body", None) or None, powertrain=pts,
                          source_url=getattr(m, "source_url", None),
                          price_from_eur=getattr(m, "price_from_eur", None),
                          suggested=m.model in why, reason=",".join(why.get(m.model, [])) or None))  # fmt: skip
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
    note = _classify_url(car, reg)
    if reg is not None:
        canon = reg.canonical(car.make) if car.make else reg.match_make(car.request_text)
        if canon and _plain(canon) != _plain(car.make):  # "Skoda" / "Škoda": keep the catalog's spelling
            car.make = canon
    if not car.make:
        return _done(car, IdentifyOutcome(outcome="NEED", need="MAKE", note=note))
    lineup = await lineup_lookup(ports, car.make) if lineup_lookup is not None else None
    known = set(await resolve.known_models(car.make, ports.ref)) | {m.model for m in _lineup_models(lineup)}
    _match_model(car, reg, known)
    if not car.model:
        choices = _choices_from_lineup(lineup, car.make, case) or [
            Choice(label=f"{car.make} {m}", make=car.make, model=m) for m in sorted(known)[:6]
        ]
        kind = "CHOICES" if choices else "NEED"
        return _done(car, IdentifyOutcome(outcome=kind, need="MODEL", choices=choices, note=note))  # type: ignore[arg-type]
    if car.variant_id and car.resolution in ("CONFIRMED", "AUTO_OK", "PROPOSED"):
        return _done(car, IdentifyOutcome(outcome="IDENTIFIED"))
    if car.condition == "USED" and car.year is None and car.age_years is None and not car.constraints.generation_hint:
        return _done(car, IdentifyOutcome(outcome="IDENTIFIED"))  # the age is asked first (USED_AGE), then resolved
    a = await resolve.assess_car(car, ports.ref, current_year, case.compare_level)
    if a.candidates:
        choices = [
            Choice(label=c["label"], make=c["make"], model=c["model"], variant_id=c["id"]) for c in a.candidates[:4]
        ]
        if not resolve.auto_resolve(car, a):  # several fit, or used: the best is proposed, the others are options
            best = a.candidates[0]
            car.variant_id, car.label, car.resolution = best["id"], best["label"], "PROPOSED"
        return _done(car, IdentifyOutcome(outcome="IDENTIFIED", choices=choices))
    return await _resolve_open(ports, case, car, current_year, lineup)


def _classify_url(car: CaseCar, reg: Any) -> str | None:
    """A URL in the reply (R10): a classifieds site is never read; a maker's home page names the make only; a
    model page stays for the resolver, which reads it (robots respected)."""
    url = car.constraints.url
    if not url:
        return None
    host = (urlparse(url if "//" in url else f"//{url}").hostname or url).removeprefix("www.")
    if evidence.is_denied(url):
        car.constraints.url = None
        return f"refused:{host}"
    if reg is not None and reg.is_home_page(url):
        car.make = car.make or reg.make_of_url(url)
        car.constraints.url = None
        return None
    return f"page:{host}"


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
        if not resolve.same_model(car.model, v.model):  # the resolver answered another model: insist once
            v, ident = await resolve.resolve_with_llm(
                ports, car, year, case.compare_level, lineup=lineup,
                insist=f"Your previous answer was {v.model}, which is NOT the model asked ({car.model}). "
                "Return a version of the model asked, or known_model=false.",
            )  # fmt: skip
        if not resolve.same_model(car.model, v.model):  # still another model: never accepted, ask with real options
            car.resolution, car.variant_id, car.label = "UNRESOLVED", None, None
            return _done(car, IdentifyOutcome(outcome="NOT_FOUND", need="MODEL", note=f"resolver returned {v.model}",
                                              choices=_close_lineup(lineup, car)))  # fmt: skip
    except resolve.GenerationMismatch as e:
        return _done(car, IdentifyOutcome(outcome="NEED", need="YEAR", note=str(e)))
    except resolve.NotOnSale as e:
        choices = await _engines_on_sale(ports, car, year, [])
        return _done(car, IdentifyOutcome(outcome="CHOICES" if choices else "NEED", need="ENGINE", choices=choices,
                                          note=str(e)))  # fmt: skip
    except resolve.UnknownModel as e:
        names = e.closest or [f"{car.make} {m.model}" for m in _lineup_models(lineup)[:6]]
        choices = [Choice(label=n, make=car.make, model=n.removeprefix(f"{car.make} ")) for n in names]
        car.resolution, car.variant_id, car.label = "UNRESOLVED", None, None
        return _done(car, IdentifyOutcome(outcome="NOT_FOUND", need="MODEL", choices=choices, checked=e.checked))
    hint = car.constraints.engine_hint
    if hint is not None and not hint.empty() and not resolve.engine_of_fits(v, hint):
        # no version with the named engine (FR-015): offer the engines that exist
        choices = await _engines_on_sale(ports, car, year, ident.alternatives)
        return _done(car, IdentifyOutcome(outcome="CHOICES" if choices else "NEED", need="ENGINE", choices=choices))
    car.variant_id, car.label, car.resolution = v.id, v.label, "PROPOSED"
    return _done(car, IdentifyOutcome(outcome="IDENTIFIED", note=ident.note))


async def _engines_on_sale(ports: Ports, car: CaseCar, year: int, alternatives: list[str]) -> list[Choice]:
    """Catalogued versions of this model that fit the car without the engine named (a new car: the generation on
    sale now), each with its variant so a tap identifies it (spec 007 F); then the resolver's alternatives."""
    probe = car.model_copy(deep=True)
    probe.constraints.engine_hint = probe.constraints.trim_hint = probe.constraints.generation_hint = None
    same = await resolve.catalog_for(car.make or "", car.model or "")
    fits = sorted((v for v in same if resolve.fits(v, probe, year, ports.ref)), key=lambda v: v.label)
    out = [Choice(label=v.label, make=v.make, model=v.model, variant_id=v.id) for v in fits]
    seen = {c.label.lower() for c in out}
    for a in alternatives:
        label = a if a.lower().startswith((car.make or "").lower()) else f"{car.make} {car.model} {a}"
        if label.lower() not in seen:
            out.append(Choice(label=label, make=car.make, model=car.model))
            seen.add(label.lower())
    return out[:6]


def _close_lineup(lineup: Any, car: CaseCar) -> list[Choice]:
    """Models of the make's line-up close to the name the user gave (the same model first)."""
    models = _lineup_models(lineup)
    close = [m for m in models if resolve.same_model(car.model, m.model) or resolve.same_model(m.model, car.model)]
    rest = [m for m in models if m not in close]
    return [Choice(label=f"{car.make} {m.model}", make=car.make, model=m.model, source_url=m.source_url)
            for m in [*close, *rest][:6]]  # fmt: skip


async def drop_wrong_variant(car: CaseCar) -> bool:
    """A stored version of another model than the one named (an earlier wrong resolution) is dropped (spec 005)."""
    if not (car.variant_id and car.model):
        return False
    v = await resolve.get_variant(car.variant_id)
    if v is None or resolve.same_model(car.model, v.model):
        return False
    car.previous_label = car.label or v.label
    car.variant_id, car.label, car.resolution, car.identify = None, None, "UNRESOLVED", None
    return True


def _done(car: CaseCar, o: IdentifyOutcome) -> IdentifyOutcome:
    o.key = key_of(car)
    car.identify = o
    return o
