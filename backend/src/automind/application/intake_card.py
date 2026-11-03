"""The intake confirmation card (spec 005 R7, FR-019–FR-021; contracts/intake-protocol.md).

`build_card`: per car the resolved identity and (new) official price, the person's profile, the research cost; every
item carries its basis — STATED (the user's words), INFERRED (with evidence), LOOKED_UP (with a source) or ASSUMED.
`apply_edit`: a chip edit, applied by code (no model call); an identity edit re-identifies the car.
"""

from __future__ import annotations

from typing import Any

from automind.domain.casefile import CaseCar, CaseFile
from automind.domain.identity import parse_engine

FUEL = {"petrol": {"en": "petrol", "ru": "бензин", "es": "gasolina"},
        "diesel": {"en": "diesel", "ru": "дизель", "es": "diésel"},
        "hybrid": {"en": "hybrid", "ru": "гибрид", "es": "híbrido"},
        "mhev": {"en": "mild hybrid", "ru": "мягкий гибрид", "es": "microhíbrido"},
        "phev": {"en": "plug-in hybrid", "ru": "плагин-гибрид", "es": "híbrido enchufable"},
        "bev": {"en": "electric", "ru": "электро", "es": "eléctrico"},
        "lpg": {"en": "LPG", "ru": "газ", "es": "GLP"}}  # fmt: skip
WORDS = {
    "new": {"en": "new", "ru": "новая", "es": "nuevo"},
    "used": {"en": "used", "ru": "подержанная", "es": "de segunda mano"},
    "catalog": {
        "en": "AutoMind catalog (sourced identity)",
        "ru": "каталог AutoMind (идентификация по источникам)",
        "es": "catálogo AutoMind (identidad con fuentes)",
    },
    "family": {"en": "family", "ru": "семья", "es": "familia"},
}
USAGE = {
    "CITY": {"en": "city", "ru": "город", "es": "ciudad"},
    "MOTORWAY": {"en": "motorway", "ru": "трасса", "es": "autovía"},
    "FAMILY": {"en": "family", "ru": "семья", "es": "familia"},
    "MOUNTAINS": {"en": "mountains", "ru": "горы", "es": "montaña"},
    "OFFROAD": {"en": "off-road", "ru": "бездорожье", "es": "campo"},
    "TRACK": {"en": "track", "ru": "трек", "es": "circuito"},
}
CLIMATE = {"HOT": {"en": "hot climate", "ru": "жаркий климат", "es": "clima caluroso"},
           "MILD": {"en": "mild climate", "ru": "мягкий климат", "es": "clima suave"},
           "COLD": {"en": "cold winters", "ru": "холодная зима", "es": "inviernos fríos"},
           "MOUNTAIN": {"en": "mountain climate", "ru": "горный климат", "es": "clima de montaña"}}  # fmt: skip


def _w(table: dict[str, dict[str, str]], key: str, lang: str) -> str:
    return table.get(key, {}).get(lang) or table.get(key, {}).get("en") or key.lower()


def _item(field: str, value: str, basis: str, **extra: Any) -> dict[str, Any]:
    out: dict[str, Any] = {"field": field, "value": value, "basis": basis}
    out.update({k: v for k, v in extra.items() if v not in (None, [], "")})
    return out


def _engine_text(v: Any) -> str:
    bits = []
    if v.engine_cc:
        bits.append(f"{v.engine_cc / 1000:.1f}")
    if v.power_kw:
        bits.append(f"{round(v.power_kw / 0.7355)} CV ({v.power_kw} kW)")
    return " · ".join(bits) or v.variant_name


_STABLE = {"make", "model", "generation", "engine", "gearbox", "year", "mileage", "trim", "price_eur"}


def _car_items(car: CaseCar, v: Any, lang: str, options: list[str], before: dict[str, str]) -> list[dict[str, Any]]:
    k = car.constraints
    src = {"name": _w(WORDS, "catalog", lang), "url": None}
    stated = car.request_text.lower()
    items = [
        _item("make", v.make, "STATED" if v.make.lower() in stated else "INFERRED", evidence=car.request_text),
        _item("model", v.model, "STATED" if v.model.lower() in stated else "LOOKED_UP", source=src),
    ]
    if v.generation:
        items.append(_item("generation", v.generation, "LOOKED_UP", source=src))
    e = k.engine_hint
    items.append(_item("engine", _engine_text(v), "STATED" if e and not e.empty() else "LOOKED_UP",
                       evidence=e.evidence if e else None, source=None if e and not e.empty() else src,
                       options=[o for o in options if o != v.label]))  # fmt: skip
    if v.fuel:
        items.append(_item("fuel", _w(FUEL, v.fuel, lang), "LOOKED_UP", source=src))
    if v.transmission:
        items.append(_item("gearbox", v.transmission, "STATED" if k.gearbox_hint else "LOOKED_UP", source=src))
    items += _condition_items(car, lang)
    if v.trim:
        items.append(_item("trim", v.trim + (f" ({v.trim_level})" if v.trim_level else ""),
                           "STATED" if k.trim_hint else "LOOKED_UP", source=None if k.trim_hint else src))  # fmt: skip
    if v.price_eur and car.condition != "USED":
        items.append(_item("price_eur", f"€{int(v.price_eur):,}".replace(",", " "), "LOOKED_UP", source=src))
    for it in items:
        if it["field"] not in _STABLE:
            continue  # translated values (fuel, condition) differ by language, not by change
        if before and before.get(it["field"]) not in (None, it["value"]):
            it["changed"], it["before"] = True, before[it["field"]]
    return items


def _condition_items(car: CaseCar, lang: str) -> list[dict[str, Any]]:
    """New or used (new is assumed when nobody said), and the year and mileage of a used car."""
    if car.condition == "UNKNOWN":
        return [_item("condition", _w(WORDS, "new", lang), "ASSUMED")]
    out = [_item("condition", _w(WORDS, car.condition.lower(), lang), "STATED")]
    if car.condition == "USED" and car.year:
        out.append(_item("year", str(car.year), "STATED"))
    if car.condition == "USED" and car.mileage_km:
        out.append(_item("mileage", f"{car.mileage_km:,} km", "STATED"))
    return out


def _profile_items(case: CaseFile, lang: str) -> list[dict[str, Any]]:
    p, ev = case.profile, case.profile.evidence
    out = []
    usage = [u for u in case.usage]
    if p.family == "FAMILY" and "FAMILY" not in usage:
        usage.append("FAMILY")
    if usage:
        out.append(_item("usage", "; ".join(_w(USAGE, u, lang) for u in usage), "INFERRED",
                         evidence=ev.get("family") or ev.get("usage")))  # fmt: skip
    if p.annual_km_min and p.annual_km_max and p.annual_km_min != p.annual_km_max:
        out.append(_item("annual_km", f"{p.annual_km_min:,}–{p.annual_km_max:,} km".replace(",", " "), "STATED",
                         evidence=ev.get("annual_km")))  # fmt: skip
    else:
        out.append(_item("annual_km", f"{case.annual_km:,} km".replace(",", " "),
                         "STATED" if case.annual_km_stated else "ASSUMED", evidence=ev.get("annual_km")))  # fmt: skip
    if p.region:
        clim = f" ({_w(CLIMATE, p.climate, lang)})" if p.climate else ""
        out.append(_item("region", p.region + clim, "INFERRED", evidence=ev.get("region")))
    if case.budget.max_eur:
        out.append(_item("budget", f"€{case.budget.max_eur:,}".replace(",", " "), "STATED"))
    if case.priorities:
        out.append(_item("priorities", ", ".join(x.criterion.replace("_", " ") for x in case.priorities), "STATED"))
    return out


def build_card(
    case: CaseFile, variants: dict[str, Any], options: dict[str, list[str]], estimate: dict[str, Any], lang: str
) -> dict[str, Any]:
    """The card as in contracts/intake-protocol.md; items changed since the last card carry `changed`."""
    prev = (case.intake.card or {}).get("values") or {}
    cars = []
    values: dict[str, dict[str, str]] = {}
    for car in case.cars:
        v = variants.get(car.variant_id or "")
        if v is None:
            continue
        before = dict(prev.get(car.key) or {})
        if car.previous_label and "engine" not in before:
            before["engine"] = car.previous_label
        items = _car_items(car, v, lang, options.get(car.key, []), before)
        values[car.key] = {i["field"]: i["value"] for i in items}
        cars.append({"key": car.key, "display_name": v.label, "items": items})
    return {"cars": cars, "profile": _profile_items(case, lang), "cost": estimate, "values": values}


def apply_edit(case: CaseFile, car_key: str | None, field: str, value: str, current_year: int) -> list[str]:
    """A chip edit on the card, applied in place by code. Identity edits drop the resolved version (re-identified)."""
    car = next((c for c in case.cars if c.key == car_key), None) if car_key else None
    case.intake.card_confirmed = False
    if car is None:
        if field == "annual_km" and value.strip().replace(" ", "").isdigit():
            km = int(value.strip().replace(" ", ""))
            if 1000 <= km <= 200000:
                case.annual_km, case.annual_km_stated = km, True
                case.profile.annual_km_min = case.profile.annual_km_max = km
                return [f"annual km {km:,}"]
        return []
    if field == "variant":
        car.variant_id, car.label, car.resolution = value, None, "PROPOSED"
        car.identify = None
        return [f"{car.key}: version chosen"]
    if field == "engine" and (e := parse_engine(value)) is not None:
        car.constraints.engine_hint = e
    elif field == "condition" and value.upper() in ("NEW", "USED"):
        car.condition = value.upper()  # type: ignore[assignment]
    elif field == "year" and value.isdigit() and 1950 <= int(value) <= current_year + 1:
        car.year = int(value)
    else:
        return []
    if car.label:
        car.previous_label = car.label
    car.variant_id, car.label, car.resolution, car.identify = None, None, "UNRESOLVED", None
    return [f"{car.key}: {field} → {value}"]
