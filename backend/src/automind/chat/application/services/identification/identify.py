"""Identify step (spec 005 R1, R2, R10): every intake turn, each unsettled or changed car is identified again from
its current facts — make registry → known models (catalog, config, line-up) → catalog fit → resolver with sources.

Outcome per car (`IdentifyOutcome`):
- IDENTIFIED: nothing to ask about the identity (a variant is set, or the catalog has candidates to confirm);
- CHOICES: concrete options to pick from (models of the make, versions, engines);
- NEED: one named item is missing (MAKE, MODEL, ENGINE, YEAR …);
- NOT_FOUND: looked up and not found; `checked` names what was looked at, `choices` the closest real names.

Never raises UnknownModel to the caller; the policy asks with concrete options instead (FR-009).

A car not on the Spanish line-up (a make not sold in Spain, or a model its Spanish line-up lacks) is looked up where
it is sold — Europe first, then the make's home market, then anywhere (chat 2026-11-06: Deepal S09, Li Auto L9) —
and identified there (`CaseCar.market`); outside Europe it never carries a price (spec 009 FR-009).
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import urlparse

from automind.acquisition.api import DatasetVersion
from automind.chat.application.ports import Ports
from automind.chat.application.services.identification import resolve, versions
from automind.chat.domain.case import CaseCar, CaseFile, Choice, IdentifyOutcome, LadderMemo
from automind.chat.domain.identification import ladder, used
from automind.chat.domain.intake import intake
from automind.shared import evidence
from automind.shared.vehicle import identity, makes
from automind.shared.vehicle.engine import EngineHint

LineupLookup = Callable[..., Awaitable[Any]]  # (ports, make[, market=]) -> application.lineup.Lineup | None


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
        low = re.sub(rf"(?i){makes.alias_pattern(a)}", " ", low)
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
    in_spain = reg is None or reg.sold_in_spain(car.make)
    lineup = await lineup_lookup(ports, car.make) if lineup_lookup is not None and in_spain else None
    catalog = set(await resolve.known_models(car.make, ports.ref))
    known = catalog | {m.model for m in _lineup_models(lineup)}
    _match_model(car, reg, known)
    if not car.model and not in_spain:  # a make not sold in Spain: its models where it is sold
        _, lineup = await _where_sold(ports, car, reg, lineup_lookup, any_model=True)
        known |= {m.model for m in _lineup_models(lineup)}
        _match_model(car, reg, known)
    return await _identify_model(ports, case, car, current_year, lineup_lookup, lineup, catalog, known, note)


async def _identify_model(ports: Ports, case: CaseFile, car: CaseCar, current_year: int,
                          lineup_lookup: LineupLookup | None, lineup: Any, catalog: set[str], known: set[str],
                          note: str | None) -> IdentifyOutcome:  # fmt: skip
    """The model is named (or asked for): placed on its market, then the ladder or the fallback."""
    if not car.model:
        choices = _choices_from_lineup(lineup, car.make, case) or [
            Choice(label=f"{car.make} {m}", make=car.make, model=m) for m in sorted(known)[:6]
        ]
        kind = "CHOICES" if choices else "NEED"
        return _done(car, IdentifyOutcome(outcome=kind, need="MODEL", choices=choices, note=note))  # type: ignore[arg-type]
    if car.variant_id and car.resolution in ("CONFIRMED", "AUTO_OK", "PROPOSED"):
        return _done(car, IdentifyOutcome(outcome="IDENTIFIED"))
    lineup = await _place(ports, car, lineup_lookup, lineup, catalog, known)
    if (year_asked := _year_first(ports, case, car, current_year)) is not None:
        return year_asked
    if (laddered := await _ladder(ports, case, car, current_year)) is not None:
        return _abroad(car, laddered)
    return _abroad(car, await _fallback(ports, case, car, current_year, lineup))


async def _place(ports: Ports, car: CaseCar, lookup: LineupLookup | None, lineup: Any, catalog: set[str],
                 known: set[str]) -> Any:  # fmt: skip
    """The market of a car not on the Spanish line-up (a make not sold in Spain, or a model its Spanish line-up and
    the catalog lack): where a line-up lists it, else the make's home market (chat 2026-11-06). Returns the line-up
    to identify with: the one that lists the model, else one of the make's (its models are the nearest ones)."""
    reg = ports.ref.makes
    in_spain = reg is None or reg.sold_in_spain(car.make)
    car.market = None
    if in_spain and (lineup is None or _listed(lineup, car.model) or car.model in catalog):
        return lineup
    market, there = await _where_sold(ports, car, reg, lookup)
    # a make not sold in Spain is of its home market even when no line-up names the model
    home = reg.home(car.make) if reg is not None else None
    car.market = market or (None if in_spain else home or intake.ANYWHERE)
    if market == intake.EUROPE:  # the European country whose page lists it, when its domain says ("PL")
        car.market = next((m.country for m in _lineup_models(there) if m.country and _listed_as(m, car.model)),
                          intake.EUROPE)  # fmt: skip
    if there is None:
        return lineup
    if market is not None:
        _match_model(car, reg, known | {m.model for m in _lineup_models(there)})
    return there


def _listed_as(m: Any, model: str | None) -> bool:
    return resolve.same_model(model, m.model) or resolve.same_model(m.model, model)


def _listed(lineup: Any, model: str | None) -> bool:
    return any(_listed_as(m, model) for m in _lineup_models(lineup))


async def _where_sold(ports: Ports, car: CaseCar, reg: Any, lookup: LineupLookup | None,
                      any_model: bool = False) -> tuple[str | None, Any]:  # fmt: skip
    """The first market whose line-up lists the car's model (any model with `any_model`): Europe, then the make's
    home market, then anywhere (domain/intake.lookup_markets). When none lists it: (None, the first line-up found),
    whose models are the nearest ones to offer."""
    if lookup is None or not car.make:
        return None, None
    first = None
    for market in intake.lookup_markets(reg.home(car.make) if reg is not None else None):
        try:
            lu = await lookup(ports, car.make, market=market)
        except Exception:  # noqa: BLE001 - a failed look-up never blocks the intake
            lu = None
        if lu is not None and (_listed(lu, car.model) if not any_model else bool(_lineup_models(lu))):
            return market, lu
        first = first if first is not None or not _lineup_models(lu) else lu
    return None, first


def _abroad(car: CaseCar, o: IdentifyOutcome) -> IdentifyOutcome:
    """An identified car not sold in Spain says where its data and prices come from (spec 009 FR-009)."""
    if car.market is not None and o.outcome == "IDENTIFIED":
        kind = intake.market_note(car.market)
        if not any(e.get("kind") == kind for e in o.events):
            o.events.append({"kind": kind, "market": car.market})
    return o


def _year_first(ports: Ports, case: CaseFile, car: CaseCar, now: int) -> IdentifyOutcome | None:
    """A used car's year is asked once, with the identity questions (FR-021); not given after that ask, it is
    assumed and shown as assumed (FR-022)."""
    if car.condition != "USED" or car.year is not None or car.age_years is not None:
        return None
    if car.constraints.generation_hint:
        return None
    if case.intake.attempt(car.key, "YEAR") < 1:
        return _done(car, IdentifyOutcome(outcome="NEED", need="YEAR"))
    _assume_year(ports, car, now)
    return None


def _catalog_version(c: dict[str, Any]) -> ladder.Version:
    """A catalog row as a ladder version (unsourced: the fallback, FR-020)."""
    return ladder.Version(engine=str(c.get("variant_name") or c.get("label") or ""), fuel=c.get("fuel"),
                          engine_cc=c.get("engine_cc"), power_kw=c.get("power_kw"),
                          gearboxes=(c["transmission"],) if c.get("transmission") else (),
                          drives=(c["drive"],) if c.get("drive") else (),
                          years_from=c.get("generation_years_from"), years_to=c.get("generation_years_to"))  # fmt: skip


def _current_rows(rows: list[dict[str, Any]], year: int) -> list[dict[str, Any]]:
    """A new car bought now: never a row that ended, or that a newer row of the same engine supersedes (the 2020
    265 CV Sorento PHEV row next to the 2024 facelift's 288 CV row, chat 5821ac77)."""
    vs = [_catalog_version(c) for c in rows]
    now = ladder.on_sale(vs, year)
    return [c for c, v in zip(rows, vs, strict=True) if v in now]


CATALOG_STALE_YEARS = 4  # default; config/search.yaml intake.catalog_stale_years


async def _fallback(ports: Ports, case: CaseFile, car: CaseCar, current_year: int, lineup: Any) -> IdentifyOutcome:
    """No sourced list of versions (FR-020): the catalog rows of the model follow the same levels — where they
    differ at a level the user did not state, it is asked; a row is never taken by being first. The identity is
    marked less certain. Without catalog rows the resolver identifies."""
    memo = car.ladder or LadderMemo()
    memo.certainty, memo.source_url, memo.others = "LESS_CERTAIN", None, []
    car.ladder = memo
    events = _reconcile(ports, car)
    a = await resolve.assess_car(car, ports.ref, current_year, case.compare_level)
    now = resolve.bought_now(car, current_year)
    cands = _current_rows(a.candidates, current_year) if now else a.candidates
    since = _picked_since(car)
    if now and cands and since is not None and all((c.get("generation_years_from") or 0) < since for c in cands):
        # the user picked a registered version newer than every catalog row (the facelift): never an old row
        return await _open_less_certain(ports, case, car, current_year, lineup)
    if cands:
        # the user's words already pick one row (the ranker): that row; rows the words do not tell apart
        # ("2.0 diesel" with 115 and 150 CV rows) are asked level by level, never taken by being first
        rows = _base_first(cands) if a.state.ambiguous and len(cands) > 1 else cands[:1]
        pool = [_catalog_version(c) for c in rows]
        d = _decide(ports, case, car, pool, memo, events)
        if not d.done or d.step.version is None:
            events.append({"kind": "identity_less_certain"})
            return _asked(car, d, events)
        years = int(_intake_cfg(ports).get("catalog_stale_years", CATALOG_STALE_YEARS))
        # the sources were searched for the versions on sale and listed none (the versions store is there, the ladder
        # fell back), and every row left was first sold long ago: the version may be a pre-facelift one
        searched = getattr(ports, "versions", None) is not None
        old = now and searched and all(ladder.stale(v, current_year, years) for v in pool)
        if old:
            stated = car.constraints.engine_hint is not None and bool(car.constraints.engine_hint.power_kw)
            if stated and any(m.endswith(" CV") for m in d.missing):  # a power the old rows lack: the resolver
                return await _open_less_certain(ports, case, car, current_year, lineup)
            asked = case.intake.attempt(car.key, "POWER") > 0
            if not (stated or d.auto or asked or car.chosen_for_me):
                found = await _registered(ports, car, pool, current_year)
                return _stale_asked(car, d.step.version, events, found, pool)
            if car.chosen_for_me and not stated:  # "choose for me" on a new car: the version on sale now
                newest = _newer(await _registered(ports, car, pool, current_year), pool)
                if newest:
                    car.constraints.version_hint = _registered_choice(car, newest[0]).engine
                    return await _open_less_certain(ports, case, car, current_year, lineup)
        events.append({"kind": "identity_less_certain"})
        row = rows[pool.index(d.step.version)]
        fresh = car.resolution not in ("CONFIRMED", "AUTO_OK", "PROPOSED")
        car.variant_id, car.label = row["id"], row["label"]
        single = fresh and car.condition != "USED" and len(pool) == 1 and not old
        car.resolution = "AUTO_OK" if single else _proposed(car)
        memo.others = [c["label"] for c in cands if c["id"] != row["id"]][:4]
        choices = [Choice(label=c["label"], make=c["make"], model=c["model"], variant_id=c["id"])
                   for c in cands[:4]]  # fmt: skip
        return _done(car, IdentifyOutcome(outcome="IDENTIFIED", choices=choices, missing=d.missing, events=events))
    return await _open_less_certain(ports, case, car, current_year, lineup)


async def _open_less_certain(ports: Ports, case: CaseFile, car: CaseCar, year: int, lineup: Any) -> IdentifyOutcome:
    o = await _resolve_open(ports, case, car, year, lineup)
    if o.outcome == "IDENTIFIED":
        o.events.append({"kind": "identity_less_certain"})
    return o


def _stale_asked(car: CaseCar, v: ladder.Version, events: list[dict[str, str]],
                 found: list[DatasetVersion] | None = None,
                 pool: list[ladder.Version] | None = None) -> IdentifyOutcome:  # fmt: skip
    """Only old catalog rows for a new car (no sourced list): the version is uncertain, asked once (its power),
    never taken silently; the answer or the next turn takes it, less certain (chat 5821ac77). The options are the
    catalog row and the versions the registration datasets list besides it — a newer engine first (the facelift),
    by its engine size, engine kW and years, never a power in CV the data does not give (chat 6e001ee0)."""
    car.ladder = car.ladder or LadderMemo()
    car.ladder.certainty = "LESS_CERTAIN"
    pool = pool or [v]
    found = found or []
    newer = _newer(found, pool)
    era = [x for x in found if x not in newer]
    until = next((x.years_to for x in era if _same_engine(x, v)), None)
    label = v.engine
    # the row is one version among others: its power and years tell it apart
    if found and v.power_kw and not re.search(r"\d\s*(cv|ps|hp|kw|ch)\b", label, re.I):
        label = f"{label} {round(v.power_kw / 0.7355)} CV"
    named = label  # the notice says since when it is sold
    if found and (span := ladder.years_text(v.years_from, until)):
        label = f"{label} · {span}"
    choices = [_choice(car, ladder.Option("POWER", label, fuel=v.fuel, engine_cc=v.engine_cc,
                                          power_kw=v.power_kw, engine=v.engine))]  # fmt: skip
    others = [x for x in era if not any(_same_engine(x, p) for p in pool)]
    choices[:0] = [_registered_choice(car, x) for x in newer]
    choices += [_registered_choice(car, x) for x in others]
    choices = choices[: ladder.MAX_OPTIONS - 1]
    if newer:
        events.append({"kind": "version_uncertain_datasets", "label": named, "since": str(v.years_from or ""),
                       "newest": str(newer[0].years_from or "")})  # fmt: skip
    else:
        events.append({"kind": "version_uncertain", "label": named, "since": str(v.years_from or "")})
    return _done(car, IdentifyOutcome(outcome="CHOICES", need="POWER", level="POWER", choices=choices, events=events))


_SINCE = re.compile(r"·\s*(\d{4})–\s*$")  # the engine text of a registered version still on sale ("… · 2024–")


def _picked_since(car: CaseCar) -> int | None:
    """The first year of the registered version the user picked (its engine text is the version hint)."""
    m = _SINCE.search(car.constraints.version_hint or "")
    return int(m.group(1)) if m else None


def _same_engine(x: DatasetVersion, v: ladder.Version) -> bool:
    """A registered version and a catalog version of the same engine (fuel, ±5 % cm3; the kW is not compared: a
    hybrid's registered kW is its combustion engine's, the catalog's the system power)."""
    if v.fuel and x.fuel != v.fuel and not ({x.fuel, v.fuel} <= {"hybrid", "mhev"}):
        return False
    return not (x.displacement_cc and v.engine_cc) or abs(x.displacement_cc - v.engine_cc) <= 0.05 * v.engine_cc


def _newer(found: list[DatasetVersion], pool: list[ladder.Version]) -> list[DatasetVersion]:
    """Registered versions first registered after the catalog rows and after the model's first registered
    versions (a facelift's engine, not the first year of the data), still registered, newest first."""
    first = min((x.years_from for x in found if x.years_from), default=None)
    rows = max((p.years_from for p in pool if p.years_from), default=None)
    return [x for x in found if x.years_from and x.years_to is None and first is not None and x.years_from > first
            and (rows is None or x.years_from > rows)]  # fmt: skip


def _registered_choice(car: CaseCar, x: DatasetVersion) -> Choice:
    """A registered version as an option of the power level: its label is built in the user's language from its
    facts (application/ask.py); the engine text names it for the resolver ("1.6 PHEV · engine 118 kW · 2024–")."""
    label = ladder.registered_label(x.fuel, x.displacement_cc, x.engine_kw, x.power_is_max, x.years_from,
                                    x.years_to, {})  # fmt: skip
    return Choice(label=label, make=car.make, model=car.model, engine=label, level="POWER", fuel=x.fuel,
                  engine_cc=x.displacement_cc, power_kw=x.engine_kw if x.power_is_max else None,
                  engine_kw=x.engine_kw, power_is_max=x.power_is_max, years_from=x.years_from, years_to=x.years_to,
                  source_url=x.source_url or None)  # fmt: skip


async def _registered(ports: Ports, car: CaseCar, pool: list[ladder.Version], year: int) -> list[DatasetVersion]:
    """The model's versions registered in the EU since its catalog rows' first year, of the car's fuel."""
    fuel = (car.constraints.engine_hint.fuel if car.constraints.engine_hint else None) or next(
        (p.fuel for p in pool if p.fuel), None)  # fmt: skip
    since = min((p.years_from for p in pool if p.years_from), default=year - versions.DATASET_YEARS)
    return await versions.dataset_versions(ports, car.make or "", car.model or "", None, fuel, since)


def _base_first(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Catalog rows the words do not tell apart, in the base version order (the least power first, then the label):
    the database returns them in any order, and "choose for me" or the ask limit takes the first (FR-009; a
    test database where the 150 CV row came back first took it)."""
    return sorted(rows, key=lambda c: (c.get("power_kw") is None, c.get("power_kw") or 0, c.get("engine_cc") or 0,
                                       str(c.get("label") or "")))  # fmt: skip


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
        # the year is known and the version named is of another generation: the versions of that year are
        # offered (asking the year again loops, chat 9b5c0b0c)
        choices = await _engines_on_sale(ports, car, year, []) if car.year is not None else []
        if choices:
            return _done(car, IdentifyOutcome(outcome="CHOICES", need="ENGINE", choices=choices, note=str(e)))
        return _done(car, IdentifyOutcome(outcome="NEED", need="YEAR", note=str(e)))
    except resolve.NotOnSale as e:
        choices = await _engines_on_sale(ports, car, year, [])
        return _done(car, IdentifyOutcome(outcome="CHOICES" if choices else "NEED", need="ENGINE", choices=choices,
                                          note=str(e)))  # fmt: skip
    except resolve.UnknownModel as e:
        names = e.closest or [f"{car.make} {m.model}" for m in _lineup_models(lineup)[:6]]
        names = intake.other_names(f"{car.make} {car.model}", intake.other_names(car.model, names))  # never itself
        choices = [Choice(label=n, make=car.make, model=n.removeprefix(f"{car.make} ")) for n in names]
        car.resolution, car.variant_id, car.label = "UNRESOLVED", None, None
        return _done(car, IdentifyOutcome(outcome="NOT_FOUND", need="MODEL", choices=choices, checked=e.checked))
    hint = car.constraints.engine_hint
    if hint is not None and not hint.empty() and not resolve.engine_of_fits(v, hint):
        # no version with the named engine (FR-015): offer the engines that exist
        choices = await _engines_on_sale(ports, car, year, [])  # no unsourced alternatives (FR-020)
        return _done(car, IdentifyOutcome(outcome="CHOICES" if choices else "NEED", need="ENGINE", choices=choices))
    car.variant_id, car.label, car.resolution = v.id, v.label, _proposed(car)
    return _done(car, IdentifyOutcome(outcome="IDENTIFIED", note=ident.note))


def _proposed(car: CaseCar) -> Any:
    """A version the hub found is proposed; after "choose for me" it is taken (no second question)."""
    return "CONFIRMED" if car.chosen_for_me else "PROPOSED"


_GEN_TOKEN = re.compile(r"(?<![\w.])(?:[A-Z]{1,3}\d{1,3}[a-z]?|Mk\s?\d+(?:\.\d)?)(?![\w.])")
_ENGINE_TOKEN = re.compile(r"^[VWR]\d{1,2}$")  # V6, W12: cylinders, not a generation


def year_conflict(label: str, car: CaseCar, ref: Any) -> bool:
    """The option names a generation that was not built in the user's year (chat 9b5c0b0c: "Audi A4 B5 2.5 TDI"
    offered for a 2023 car). A generation config knows is checked by its years; an unknown one is a conflict
    when config knows the generation of that year (it is another one)."""
    if car.year is None or not (car.make and car.model) or ref is None:
        return False
    gens = list(getattr(ref, "generations", {}).get(f"{car.make}|{car.model}", []))
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


async def _engines_on_sale(ports: Ports, car: CaseCar, year: int, alternatives: list[str]) -> list[Choice]:
    """Catalogued versions of this model that fit the car without the engine named (a new car: the generation on
    sale now), each with its variant so a tap identifies it (spec 007 F); then the resolver's alternatives."""
    probe = car.model_copy(deep=True)
    probe.constraints.engine_hint = probe.constraints.trim_hint = probe.constraints.generation_hint = None
    same = await resolve.catalog_for(car.make or "", car.model or "")
    fits = sorted((v for v in same if resolve.fits(v, probe, year, ports.ref)), key=lambda v: v.label)
    out = [Choice(label=v.label, make=v.make, model=v.model, variant_id=v.id) for v in fits
           if not year_conflict(v.label, car, ports.ref)]  # fmt: skip
    seen = {c.label.lower() for c in out}
    for a in alternatives:
        label = a if a.lower().startswith((car.make or "").lower()) else f"{car.make} {car.model} {a}"
        if label.lower() not in seen and not year_conflict(label, car, ports.ref):
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


# --- the identification ladder (spec 008): generation → engine → gearbox → driven wheels over sourced versions ---


def _spans(ports: Ports, car: CaseCar) -> dict[str, tuple[int | None, int | None]]:
    gens = (getattr(ports.ref, "generations", None) or {}).get(f"{car.make}|{car.model}", [])
    out = {str(g).lower(): (lo, hi) for g, lo, hi in gens}
    m = car.ladder
    if m is not None and m.generation:
        out.setdefault(m.generation.lower(), (m.generation_from, m.generation_to))
    return out


def _intake_cfg(ports: Ports) -> dict[str, Any]:
    return dict((getattr(ports.ref, "search", None) or {}).get("intake") or {})


def _assume_year(ports: Ports, car: CaseCar, now: int) -> None:
    """A used car with no year after one ask: an age from the mileage, else the middle of the generation the hint
    names, else the default; the year is marked as assumed everywhere it is used (FR-022)."""
    cfg = _intake_cfg(ports)
    span = _spans(ports, car).get((car.constraints.generation_hint or "").lower(), (None, None))
    age, _ = used.assumed_age(car.mileage_km, span[0], span[1], now,
                              km_per_year=int(cfg.get("km_per_year_used", used.KM_PER_YEAR_USED)),
                              default=int(cfg.get("default_used_age", used.DEFAULT_USED_AGE)))  # fmt: skip
    car.year, car.age_years, car.year_assumed = now - age, age, True


def _generation(ports: Ports, car: CaseCar, year: int) -> str | None:
    """The generation the facts name: the user's, the one on sale (new), or the only one built in the year."""
    if car.constraints.generation_hint:
        return car.constraints.generation_hint
    if car.condition != "USED":
        cur = resolve.current_generation(ports.ref, car, year)
        return cur[0] if cur else None
    gens = (getattr(ports.ref, "generations", None) or {}).get(f"{car.make}|{car.model}", [])
    built = [str(g) for g, lo, hi in gens
             if lo is not None and car.year and identity.generation_matches(car.year, lo, hi)]  # fmt: skip
    return built[0] if len(built) == 1 else None


def _wanted(car: CaseCar) -> ladder.Wanted:
    k = car.constraints
    words = " ".join(x for x in (car.model or "", car.request_text or "", k.trim_hint or "") if x)
    return ladder.wanted_of(k.engine_hint, engine=k.version_hint, gearbox=k.gearbox_hint, drive=k.drive_hint,
                            year=car.year if car.condition == "USED" else None, words=words)  # fmt: skip


def _levels(car: CaseCar, w: ladder.Wanted) -> dict[str, str]:
    return ladder.levels_of(car.year, car.year_assumed, car.constraints.generation_hint, w)


def _reconcile(ports: Ports, car: CaseCar) -> list[dict[str, str]]:
    """A newer answer wins over an older one; levels the hub filled below a changed level are opened again."""
    memo = car.ladder
    if memo is None:
        return []
    r = ladder.reconcile(memo.levels, _levels(car, _wanted(car)), memo.origin, _spans(ports, car))
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


def _choice(car: CaseCar, o: ladder.Option) -> Choice:
    return Choice(label=o.label, make=car.make, model=car.model, engine=o.engine, level=o.level, fuel=o.fuel,
                  engine_cc=o.engine_cc, family=o.family, power_kw=o.power_kw, gearbox=o.gearbox,
                  drive=o.drive)  # fmt: skip


def _decide(ports: Ports, case: CaseFile, car: CaseCar, pool: list[ladder.Version], memo: LadderMemo,
            events: list[dict[str, str]]) -> ladder.Decision:  # fmt: skip
    """One ladder step over `pool`; the levels the hub settled are written with their origin."""
    cfg = _intake_cfg(ports)
    asks = {i: case.intake.attempt(car.key, i) for i in ladder.ITEMS}
    before = _wanted(car)
    d = ladder.decide(pool, before, asks, limit=int(cfg["max_attempts_per_item"]), chosen=car.chosen_for_me)
    if d.auto:
        old = _levels(car, before)
        _write(car, d.wanted)
        for lvl, val in _levels(car, d.wanted).items():
            if old.get(lvl) != val:
                memo.origin[lvl] = d.auto[0].origin
        events += [{"kind": "settled_by_rule", "label": a.label} for a in d.auto if a.origin == "LIMIT"]
    memo.levels = _levels(car, _wanted(car))
    return d


def _asked(car: CaseCar, d: ladder.Decision, events: list[dict[str, str]]) -> IdentifyOutcome:
    step = d.step
    choices = [_choice(car, o) for o in step.options]
    return _done(car, IdentifyOutcome(outcome="CHOICES", need=ladder.ITEM[step.kind], level=step.kind,  # type: ignore[arg-type]
                                      choices=choices, missing=d.missing, events=events))  # fmt: skip


async def _ladder(ports: Ports, case: CaseFile, car: CaseCar, year: int) -> IdentifyOutcome | None:
    """The car narrowed over the sourced versions of its generation; None when no source lists them (the
    fallback identifies then, FR-020)."""
    if not (car.make and car.model) or ports.versions is None:
        return None
    events = _reconcile(ports, car)
    new = car.condition != "USED"
    gen = _generation(ports, car, year)
    try:
        fuel = car.constraints.engine_hint.fuel if car.constraints.engine_hint else None
        g = await versions.lookup(ports, car.make, car.model, generation=gen, year=None if new else car.year, new=new,
                                  current_year=year, fuel=fuel, market=car.market)  # fmt: skip
    except Exception:  # noqa: BLE001 - a failed look-up never blocks the intake: the fallback identifies
        g = None
    if g is None or not g.versions:
        return None
    memo = car.ladder or LadderMemo()
    memo.certainty, memo.generation = "SOURCED", g.generation
    memo.generation_from, memo.generation_to = g.years_from, g.years_to
    car.ladder = memo
    # a new car is one of the versions on sale now (the facelift's, not the first years', chat 5821ac77); a used
    # one, of the versions sold in its year (`_wanted` carries the year, FR-023)
    pool = ladder.on_sale(g.versions, year) if new else g.versions
    d = _decide(ports, case, car, pool, memo, events)
    if d.done and d.step.version is not None:
        v = await _store_version(ports, car, g, d.step)
        car.variant_id, car.label, car.resolution = v.id, v.label, _proposed(car)
        memo.source_url = d.step.version.source_url or None
        memo.source_name = versions.DATASET_SOURCE if any(s.get("dataset") for s in g.sources) else None
        memo.others = _others(pool, car.year if not new else None, d.step.version)
        if d.missing and not d.auto:  # the user named something this generation has not: said, the one there is
            events.append({"kind": "ladder_missing", "missing": ", ".join(d.missing), "label": v.label})
        return _done(car, IdentifyOutcome(outcome="IDENTIFIED", missing=d.missing, events=events))
    return _asked(car, d, events)


def _others(versions: list[ladder.Version], year: int | None, chosen: ladder.Version) -> list[str]:
    """Up to four other versions of the same generation (and year) for the card's engine chips."""
    pool = ladder.narrow(versions, ladder.Wanted(year=year)).versions
    out: list[str] = []
    for v in pool:
        if v.engine_key != chosen.engine_key and v.engine not in out:
            out.append(v.engine)
    return out[:4]


async def _store_version(ports: Ports, car: CaseCar, g: ladder.Generation, step: ladder.Step) -> Any:
    """The catalog row of the settled version (one row per real version: an existing one is reused, FR-019)."""
    v = step.version
    assert v is not None
    name = v.engine + (f" {ladder.GEARBOX_LABEL.get(step.gearbox, step.gearbox)}" if step.gearbox else "")
    name += " AWD" if step.drive == "AWD" and not re.search(r"awd|4motion|quattro|xdrive|4x4|4wd", name, re.I) else ""
    ident = resolve.VariantIdentity(
        make=car.make or g.make, model=car.model or g.model, generation=g.generation,
        generation_years_from=g.years_from, generation_years_to=g.years_to, variant_name=name,
        powertrain=ladder.POWERTRAIN.get(v.fuel or "", "ICE"), body_class=g.body_class,  # type: ignore[arg-type]
        transmission=step.gearbox, drive=step.drive, engine_cc=v.engine_cc, power_kw=v.power_kw,  # type: ignore[arg-type]
        fuel=v.fuel, certainty="exact",  # type: ignore[arg-type]
    )  # fmt: skip
    return await resolve.upsert_variant(ident, ports.ref)
