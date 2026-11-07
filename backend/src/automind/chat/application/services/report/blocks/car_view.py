"""What the user sees of each car (spec 010 US10, FR-036/FR-037): the full version line and the choices of a
structured "Change", from the catalog and the cached version ladder only (no search, no model call)."""

from __future__ import annotations

from collections.abc import Callable, Sequence

from automind.acquisition.api import CatalogueVariant
from automind.chat.application.services.identification import catalogue
from automind.chat.domain.case import CarContext, CaseCar, CaseDelta, CaseFile, Constraints
from automind.chat.domain.case.enums import GEARBOXES, Gearbox
from automind.shared.contracts.json import JsonObject
from automind.shared.vehicle.identity import parse_engine

EDIT_FIELDS = ("generation", "engine", "gearbox", "trim", "not_this_car", "remove")
MakeMatcher = Callable[[str], str | None]  # the make a text names (`MakeNames.match_make`)


def engine_text(v: CatalogueVariant) -> str:
    """ "1.5 TSI 150 CV" from a catalog row: the family from its name, displacement and power from its facts."""
    e = parse_engine(v.variant_name)
    bits = []
    cc = v.engine_cc
    if cc:
        bits.append(f"{cc / 1000:.1f}")
    elif e is not None and e.displacement_l:
        bits.append(f"{e.displacement_l:.1f}")
    if e is not None and e.family:
        bits.append(e.family)
    kw = v.power_kw
    if kw:
        bits.append(f"{round(kw / 0.7355)} CV")
    elif e is not None and e.power_hp:
        bits.append(f"{e.power_hp} CV")
    return " ".join(bits) or str(v.variant_name or "")


def gearbox_kind(text: str | None) -> Gearbox | None:
    """The kind of gearbox a label names ("DSG" → dct, "6MT" → manual); any other automatic is "automatic"."""
    t = (text or "").lower()
    if not t:
        return None
    if t in GEARBOXES:
        return GEARBOXES[t]
    if "manual" in t or t == "mt":
        return "manual"
    if any(w in t for w in ("dsg", "dct", "edc", "s tronic", "pdk")):
        return "dct"
    if "e-cvt" in t or "ecvt" in t:
        return "e-cvt"
    if "cvt" in t:
        return "cvt"
    return "automatic"


def variant_label(car: CaseCar, v: CatalogueVariant | None) -> str | None:
    """engine · gearbox · trim · year of the resolved version (FR-036); None while the car is not identified."""
    if v is None:
        return None
    year: str | None = str(car.year) if car.year else None
    if year is None and car.condition != "USED":
        lo, hi = v.generation_years_from, v.generation_years_to
        year = f"{lo}–{hi}" if lo and hi else (f"{lo}–" if lo else None)
    bits = [engine_text(v), v.transmission, v.trim, year]
    return " · ".join(str(b) for b in bits if b)


async def view(case: CaseFile) -> dict[str, JsonObject]:
    """Per car key: `variant_label` and `options` {generation, engine, gearbox, trim} for the "Change" action."""
    out: dict[str, JsonObject] = {}
    catalogs: dict[tuple[str, str], list[CatalogueVariant]] = {}
    for car in case.cars:
        v = await catalogue.get_variant(car.variant_id) if car.variant_id else None
        rows: list[CatalogueVariant] = []
        if car.make and car.model:
            k = (car.make.lower(), car.model.lower())
            if k not in catalogs:
                catalogs[k] = await catalogue.find_variants(car.make, car.model)
            rows = catalogs[k]
        out[car.key] = {"variant_label": variant_label(car, v), "options": options(car, v, rows)}
    return out


def _distinct(values: Sequence[str | None], current: str | None) -> list[str]:
    seen: list[str] = []
    for x in values:
        if x and x != current and x not in seen:
            seen.append(x)
    return seen[:6]


def options(car: CaseCar, v: CatalogueVariant | None, rows: list[CatalogueVariant]) -> dict[str, list[str]]:
    """The choices of the catalog (and the sourced versions of the ladder) for this make and model."""
    gen = (v.generation if v is not None else None) or car.constraints.generation_hint
    same_gen = [r for r in rows if not gen or r.generation == gen] or rows
    current_engine = engine_text(v) if v is not None else None
    engines = [engine_text(r) for r in same_gen]
    if car.ladder is not None and car.ladder.certainty == "SOURCED":
        engines = [*car.ladder.others, *engines]
    gearboxes = [gearbox_kind(r.transmission) for r in same_gen]
    if car.ladder is not None:
        gearboxes = [*gearboxes, *(gearbox_kind(x) for x in car.ladder.levels.get("GEARBOX", "").split("|"))]
    return {
        "generation": _distinct([r.generation for r in rows], gen),
        "engine": _distinct(engines, current_engine),
        "gearbox": _distinct(gearboxes, gearbox_kind(v.transmission if v is not None else None)),
        "trim": _distinct([r.trim for r in same_gen], v.trim if v is not None else None),
    }


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
        make = (match_make(v) if match_make is not None and v else None) or car.make
        model = _model_words(v, make) if v else None
        ctx = CarContext(target_key=car.key, request_text=v or (make or car.request_text), make=make,
                         model=model or None, condition=car.condition, constraints=Constraints())  # fmt: skip
        return CaseDelta(replace_cars=[ctx])
    if not v:
        raise ValueError(f"{field}: a value is needed")
    k = _constraints(car.constraints.model_copy(deep=True), field, v)
    if k == car.constraints:
        raise ValueError(f"{field}: unchanged")
    return CaseDelta(replace_cars=[CarContext(target_key=car.key, constraints=k)])


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


async def case_payload(case: CaseFile) -> JsonObject:
    """The case as the client sees it: each car also carries its version line and the choices of "Change"
    (FR-036/FR-037); these are views, never stored in the case."""
    data = case.model_dump(mode="json")
    try:
        views = await view(case)
    except Exception:  # noqa: BLE001 - a view, never a reason to fail a turn
        return data
    for car in data.get("cars") or []:
        car.update(views.get(car.get("key"), {}))
    return data
