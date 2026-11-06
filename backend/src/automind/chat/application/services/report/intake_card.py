"""The intake confirmation card (spec 005 R7, FR-019–FR-021; contracts/intake-protocol.md).

`build_card`: per car the resolved identity and (new) official price, the person's profile, the research cost; every
item carries its basis — STATED (the user's words), INFERRED (with evidence), LOOKED_UP (with a source) or ASSUMED.
`apply_edit`: a chip edit, applied by code (no model call); an identity edit re-identifies the car.
"""

from __future__ import annotations

from typing import Any

from automind.chat.domain.case import CaseCar, CaseFile
from automind.shared.vehicle.identity import parse_engine

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
    "versions": {"en": "list of versions", "ru": "список версий", "es": "lista de versiones"},
    "chosen": {
        "en": 'chosen by me: the base version (you said "choose for me")',
        "ru": "выбрано мной: базовая версия (вы сказали «выбери сам»)",
        "es": "elegido por mí: la versión base (dijiste «elige tú»)",
    },
    "limit": {
        "en": "chosen by me: the base version (the question was not answered twice)",
        "ru": "выбрано мной: базовая версия (на вопрос дважды не было ответа)",
        "es": "elegido por mí: la versión base (la pregunta quedó sin respuesta dos veces)",
    },
}
ENGINE_LEVELS = ("FUEL", "ENGINE", "POWER")
UNSURE = {
    "en": "from the catalog: no source lists this model's versions — check the power",
    "ru": "из каталога: список версий этой модели в источниках не найден — проверьте мощность",
    "es": "del catálogo: ninguna fuente lista las versiones de este modelo — comprueba la potencia",
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


PERSONA = {"PERFORMANCE": {"en": "enthusiast: driving and performance", "ru": "энтузиаст: динамика и вождение",
                           "es": "entusiasta: conducción y prestaciones"},
           "BUYER": {"en": "family and practical buyer", "ru": "семья и практичный покупатель",
                     "es": "familia y compra práctica"},
           "EXPERT": {"en": "expert: engineering", "ru": "эксперт: техника", "es": "experto: ingeniería"},
           "UNKNOWN": {"en": "not clear yet", "ru": "пока не ясно", "es": "aún no está claro"}}  # fmt: skip
YEARS = {"en": "{n} years", "ru": "{n} лет", "es": "{n} años"}
YEAR_OPTIONS = (3, 5, 8, 12)


def _years(n: int, lang: str) -> str:
    if lang == "ru":
        word = "год" if n % 10 == 1 and n % 100 != 11 else ("года" if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14
                                                             else "лет")  # fmt: skip
        return f"{n} {word}"
    return (YEARS.get(lang) or YEARS["en"]).format(n=n)


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


def _settled_by_me(car: CaseCar, levels: tuple[str, ...]) -> str | None:
    """CHOSEN or LIMIT when the hub settled one of these ladder levels (spec 008 FR-009/FR-010), else None."""
    origin = car.ladder.origin if car.ladder else {}
    return next((origin[lv] for lv in levels if origin.get(lv) in ("CHOSEN", "LIMIT")), None)


def _engine_item(car: CaseCar, v: Any, lang: str, options: list[str], src: dict[str, Any]) -> dict[str, Any]:
    """The engine as settled: "you said" only when the user named it; chosen by me when "choose for me" or the
    ask limit settled it (spec 008, live chat 8c6a2a58)."""
    e, others = car.constraints.engine_hint, [o for o in options if o != v.label]
    by_me = _settled_by_me(car, ENGINE_LEVELS)
    if by_me:
        return _item("engine", _engine_text(v), "ASSUMED", evidence=_w(WORDS, by_me.lower(), lang), source=src,
                     options=others)  # fmt: skip
    said = bool(e and not e.empty())
    unsure = car.ladder is not None and car.ladder.certainty == "LESS_CERTAIN"
    power_said = said and e is not None and bool(e.power_kw or e.power_hp)
    if unsure and not power_said:  # FR-020: no source lists the versions, the power is the catalog's
        note = UNSURE.get(lang) or UNSURE["en"]
        if not said:
            return _item("engine", _engine_text(v), "ASSUMED", evidence=note, source=src, options=others)
        return _item("engine", _engine_text(v), "STATED", evidence=f"{e.evidence} — {note}" if e else note,
                     options=others)  # fmt: skip
    return _item("engine", _engine_text(v), "STATED" if said else "LOOKED_UP", evidence=e.evidence if e else None,
                 source=None if said else src, options=others)  # fmt: skip


def _car_items(car: CaseCar, v: Any, lang: str, options: list[str], before: dict[str, str]) -> list[dict[str, Any]]:
    k = car.constraints
    memo = car.ladder
    sourced = memo is not None and memo.certainty == "SOURCED"
    src = ({"name": memo.source_name, "url": memo.source_url} if sourced and memo and memo.source_name
           else {"name": _w(WORDS, "versions", lang), "url": memo.source_url} if sourced and memo and memo.source_url
           else {"name": _w(WORDS, "catalog", lang), "url": None})  # fmt: skip
    if sourced and memo and memo.others:
        options = list(memo.others)  # the other versions of this generation, never other generations' rows
    stated = car.request_text.lower()
    items = [
        _item("make", v.make, "STATED" if v.make.lower() in stated else "INFERRED", evidence=car.request_text),
        _item("model", v.model, "STATED" if v.model.lower() in stated else "LOOKED_UP", source=src),
    ]
    if v.generation:
        items.append(_item("generation", v.generation, "LOOKED_UP", source=src))
    items.append(_engine_item(car, v, lang, options, src))
    if v.fuel:
        items.append(_item("fuel", _w(FUEL, v.fuel, lang), "LOOKED_UP", source=src))
    if v.transmission:
        gb_me = _settled_by_me(car, ("GEARBOX",))
        items.append(_item("gearbox", v.transmission,
                           "ASSUMED" if gb_me else ("STATED" if k.gearbox_hint else "LOOKED_UP"),
                           evidence=_w(WORDS, gb_me.lower(), lang) if gb_me else None, source=src))  # fmt: skip
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
    p, ev, b = case.profile, case.profile.evidence, case.basis
    out = [
        # spec 007 US1: who the user is and how long they keep a car, with how it is known; chips edit it
        _item("persona", _w(PERSONA, case.persona, lang), b.get("persona", "ASSUMED"),
              evidence=ev.get("persona"), options=[_w(PERSONA, x, lang) for x in ("PERFORMANCE", "BUYER", "EXPERT")]),
        _item("ownership_years", _years(case.ownership_years or 5, lang), b.get("ownership_years", "ASSUMED"),
              options=[_years(n, lang) for n in YEAR_OPTIONS]),
    ]  # fmt: skip
    usage = [u for u in case.usage]
    if p.family == "FAMILY" and "FAMILY" not in usage:
        usage.append("FAMILY")
    if usage:
        out.append(_item("usage", "; ".join(_w(USAGE, u, lang) for u in usage), b.get("usage", "INFERRED"),
                         evidence=ev.get("family") or ev.get("usage")))  # fmt: skip
    if p.annual_km_min and p.annual_km_max and p.annual_km_min != p.annual_km_max:
        out.append(_item("annual_km", f"{p.annual_km_min:,}–{p.annual_km_max:,} km".replace(",", " "), "STATED",
                         evidence=ev.get("annual_km")))  # fmt: skip
    else:
        out.append(_item("annual_km", f"{case.annual_km:,} km".replace(",", " "),
                         b.get("annual_km", "STATED" if case.annual_km_stated else "ASSUMED"),
                         evidence=ev.get("annual_km")))  # fmt: skip
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
        return _profile_edit(case, field, value)
    return _car_edit(car, field, value, current_year)


def _profile_edit(case: CaseFile, field: str, value: str) -> list[str]:
    """A profile chip on the card is the user's statement (STATED), applied before research (spec 007 FR-015)."""
    v = value.strip()
    if field == "persona":
        key = next((k for k, tr in PERSONA.items() if v in tr.values() or v.upper() == k), None)
        if key and key != "UNKNOWN":
            case.persona, case.persona_source, case.basis["persona"] = key, "USER_EDIT", "STATED"  # type: ignore[assignment]
            return [f"persona: {key}"]
        return []
    if field == "ownership_years":
        n = next((int(x) for x in v.split() if x.isdigit()), None)
        if n is not None and 1 <= n <= 20:
            case.ownership_years, case.basis["ownership_years"] = n, "STATED"
            return [f"ownership: {n} years"]
        return []
    if field == "annual_km" and v.replace(" ", "").isdigit():
        km = int(v.replace(" ", ""))
        if 1000 <= km <= 200000:
            case.annual_km, case.annual_km_stated = km, True
            case.basis["annual_km"] = "STATED"
            case.profile.annual_km_min = case.profile.annual_km_max = km
            return [f"annual km {km:,}"]
    return []


def _car_edit(car: CaseCar, field: str, value: str, current_year: int) -> list[str]:
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
