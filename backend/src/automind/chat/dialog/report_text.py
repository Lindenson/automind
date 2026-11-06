"""Phrasing of the code-built verdict and insights (spec 004 US1, FR-001). The structure and every number come
from domain.verdict / domain.insights; this module only writes them in ru / es / en. Deterministic.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from automind.chat.domain.verdict.insights import Insight, InsightSet
from automind.chat.domain.verdict.verdict import MAX_BREAK_EVEN_YEARS, Limit, Verdict

_T: dict[str, dict[str, str]] = {
    "pick": {
        "en": "For you: the {car}",
        "ru": "Для вас: {car}",
        "es": "Para ti: el {car}",
    },
    "tie": {
        "en": "Too close to call: {cars}",
        "ru": "Слишком близко, чтобы выбрать: {cars}",
        "es": "Demasiado igualados: {cars}",
    },
    "no_data": {
        "en": "Not enough data to recommend yet",
        "ru": "Пока недостаточно данных для рекомендации",
        "es": "Aún no hay datos suficientes para recomendar",
    },
    "single": {"en": "Profile of the {car}", "ru": "Профиль: {car}", "es": "Perfil del {car}"},
    "different": {
        "en": "These cars serve different needs; ",
        "ru": "Эти машины для разных задач; ",
        "es": "Estos coches cubren necesidades distintas; ",
    },
    "better": {
        "en": "{label}: {car} {value} vs {other} {other_value} ({diff} better)",
        "ru": "{label}: {car} {value} против {other} {other_value} (лучше на {diff})",
        "es": "{label}: {car} {value} frente a {other} {other_value} ({diff} mejor)",
    },
    "money": {"en": ", about €{eur} a year", "ru": ", около {eur} € в год", "es": ", unos {eur} € al año"},
    "trade_total": {
        "en": "{gain_car} costs {extra} more to buy but less to own over your {years} years including depreciation "
        "({gain_total} vs {cost_total}); it pays back after about {be} years",
        "ru": "{gain_car} дороже при покупке на {extra}, но за ваши {years} лет с учётом потери стоимости обходится "
        "дешевле ({gain_total} против {cost_total}); окупается примерно за {be} лет",
        "es": "{gain_car} cuesta {extra} más pero, contando la depreciación, sale más barato en tus {years} años "
        "({gain_total} frente a {cost_total}); se amortiza en unos {be} años",
    },
    "trade_late": {
        "en": "{gain_car} has lower running costs (without depreciation, {saving} a year less), but over your "
        "{years} years including depreciation it costs more: {gain_total} vs {cost_total} for the {cost_car}; it "
        "would pay back only after about {be} years",
        "ru": "У {gain_car} ниже расходы на содержание (без учёта потери стоимости — на {saving} в год), но за ваши "
        "{years} лет с учётом потери стоимости он дороже: {gain_total} против {cost_total} у {cost_car}; окупился "
        "бы только примерно за {be} лет",
        "es": "{gain_car} tiene menor coste de uso (sin depreciación, {saving} menos al año), pero en tus {years} "
        "años, con la depreciación, cuesta más: {gain_total} frente a {cost_total} del {cost_car}; solo se "
        "amortizaría en unos {be} años",
    },
    "trade_never": {
        "en": "{gain_car} has lower running costs (without depreciation, {saving} a year less), but over your "
        "{years} years including depreciation it costs more: {gain_total} vs {cost_total} for the {cost_car}; it "
        "does not pay back within 15 years",
        "ru": "У {gain_car} ниже расходы на содержание (без учёта потери стоимости — на {saving} в год), но за ваши "
        "{years} лет с учётом потери стоимости он дороже: {gain_total} против {cost_total} у {cost_car}; не "
        "окупается даже за 15 лет",
        "es": "{gain_car} tiene menor coste de uso (sin depreciación, {saving} menos al año), pero en tus {years} "
        "años, con la depreciación, cuesta más: {gain_total} frente a {cost_total} del {cost_car}; no se amortiza "
        "ni en 15 años",
    },
    "trade_plain": {
        "en": "{gain_car} is better on {gain}, {cost_car} on {cost}",
        "ru": "{gain_car} лучше по показателю «{gain}», {cost_car} — по показателю «{cost}»",
        "es": "{gain_car} es mejor en {gain}, {cost_car} en {cost}",
    },
    "wc_break_even": {
        "en": "If you keep the car more than {years} years, the {car} comes out ahead",
        "ru": "Если вы будете ездить на машине дольше {years} лет, выгоднее {car}",
        "es": "Si conservas el coche más de {years} años, sale ganando el {car}",
    },
    "wc_break_even_short": {
        "en": "If you keep the car less than {years} years, the {car} comes out ahead (counting depreciation)",
        "ru": "Если вы будете ездить на машине меньше {years} лет, выгоднее {car} (с учётом потери стоимости)",
        "es": "Si conservas el coche menos de {years} años, sale ganando el {car} (contando la depreciación)",
    },
    "wc_priority": {
        "en": "If {label} matters more to you, the {car} wins",
        "ru": "Если для вас важнее показатель «{label}», лучше {car}",
        "es": "Si te importa más {label}, gana el {car}",
    },
    "wc_data": {
        "en": "Missing data could change it: {gaps}",
        "ru": "Вывод может измениться, когда найдутся данные: {gaps}",
        "es": "Los datos que faltan podrían cambiarlo: {gaps}",
    },
    "best_if_budget": {
        "en": "Best if the budget allows: the {car}",
        "ru": "Лучший, если позволяет бюджет: {car}",
        "es": "El mejor si el presupuesto lo permite: el {car}",
    },
    "OVER_BUDGET": {
        "en": "The {car} costs {value}, over your budget of {limit}",
        "ru": "{car} стоит {value} — больше вашего бюджета {limit}",
        "es": "El {car} cuesta {value}, por encima de tu presupuesto de {limit}",
    },
    "OVER_MONTHLY": {
        "en": "Running the {car} costs about {value} a month, over your limit of {limit}",
        "ru": "Содержание {car} — около {value} в месяц, больше вашего лимита {limit}",
        "es": "Mantener el {car} cuesta unos {value} al mes, por encima de tu límite de {limit}",
    },
    "moved_pick": {
        "en": "The {best} scores a little higher but is over your limit; within it the {car} is the pick",
        "ru": "{best} набирает чуть больше баллов, но выходит за ваш лимит; в его рамках лучший выбор — {car}",
        "es": "El {best} puntúa algo más pero supera tu límite; dentro de él, la elección es el {car}",
    },
    "other_profile": {
        "en": "Someone who cares most about {focus} would take the {car}",
        "ru": "Тот, кому важнее всего {focus}, выбрал бы {car}",
        "es": "Quien priorice {focus} elegiría el {car}",
    },
    "used_missing": {
        "en": "{car} (used): not found yet — {missing}",
        "ru": "{car} (б/у): пока не найдено — {missing}",
        "es": "{car} (usado): aún no encontrado — {missing}",
    },
    "miss_price_used": {"en": "used prices", "ru": "цены на б/у", "es": "precios de segunda mano"},
    "miss_wear": {
        "en": "typical wear at this age",
        "ru": "типичный износ в этом возрасте",
        "es": "desgaste típico a esta edad",
    },
    "within_period": {
        "en": "Counting depreciation, over your {years} years the {car} pays back its higher price (break-even about "
        "{be} years)",
        "ru": "С учётом потери стоимости за ваши {years} лет {car} окупает более высокую цену (окупаемость около {be} "
        "лет)",
        "es": "Contando la depreciación, en tus {years} años el {car} amortiza su mayor precio (en unos {be} años)",
    },
    "beyond_period": {
        "en": "Counting depreciation, the {car} pays back its higher price only after about {be} years; you plan "
        "{years}",
        "ru": "С учётом потери стоимости {car} окупает более высокую цену только примерно за {be} лет, а вы "
        "планируете {years}",
        "es": "Contando la depreciación, el {car} solo amortiza su mayor precio en unos {be} años; tú planeas {years}",
    },
    "no_payback": {
        "en": "Counting depreciation, the {car} costs more to own and its lower running costs do not pay that back "
        "within 15 years; you plan {years}",
        "ru": "С учётом потери стоимости {car} обходится дороже, и более низкие расходы на содержание не окупят "
        "разницу даже за 15 лет, а вы планируете {years}",
        "es": "Contando la depreciación, el {car} cuesta más y su menor coste de uso no lo compensa ni en 15 años; "
        "tú planeas {years}",
    },
    "conf_COVERAGE_HIGH": {
        "en": "the comparison covers what matters to you, from several sources",
        "ru": "сравнение охватывает важное для вас, данные из нескольких источников",
        "es": "la comparación cubre lo que te importa, con varias fuentes",
    },
    "conf_COVERAGE_MEDIUM": {
        "en": "part of what matters to you could not be compared",
        "ru": "часть важного для вас сравнить не удалось",
        "es": "parte de lo que te importa no se pudo comparar",
    },
    "conf_COVERAGE_LOW": {
        "en": "most of what matters to you could not be compared",
        "ru": "большую часть важного для вас сравнить не удалось",
        "es": "la mayor parte de lo que te importa no se pudo comparar",
    },
    "conf_GAPS": {
        "en": "key data is missing: {gaps}",
        "ru": "не хватает ключевых данных: {gaps}",
        "es": "faltan datos clave: {gaps}",
    },
    "conf_NO_DATA": {
        "en": "the cars have no common data to compare",
        "ru": "у машин нет общих данных для сравнения",
        "es": "los coches no tienen datos comunes para comparar",
    },
    "conf_SINGLE": {
        "en": "a profile of one car, scored on absolute scales",
        "ru": "профиль одной машины по абсолютным шкалам",
        "es": "perfil de un coche con escalas absolutas",
    },
}


LABELS: dict[str, dict[str, str]] = {
    "boot_volume": {"en": "Boot volume", "ru": "Объём багажника", "es": "Maletero"},
    "consumption": {"en": "Consumption (WLTP)", "ru": "Расход (WLTP)", "es": "Consumo (WLTP)"},
    "accel_0_100": {"en": "0–100 km/h", "ru": "Разгон 0–100 км/ч", "es": "0–100 km/h"},
    "measured_0_100": {"en": "0–100 km/h (measured)", "ru": "Разгон 0–100 (замер)", "es": "0–100 km/h (medido)"},
    "max_power": {"en": "Power", "ru": "Мощность", "es": "Potencia"},
    "max_torque": {"en": "Torque", "ru": "Крутящий момент", "es": "Par"},
    "curb_mass": {"en": "Weight", "ru": "Масса", "es": "Peso"},
    "official_price_es": {"en": "Price", "ru": "Цена", "es": "Precio"},
    "tco_per_year": {"en": "Running costs per year (without depreciation)",
                     "ru": "Расходы на содержание в год (без учёта потери стоимости)",
                     "es": "Coste de uso anual (sin depreciación)"},
    "tco_period": {"en": "Total cost over the period (incl. depreciation)",
                   "ru": "Полная стоимость владения за период (с потерей стоимости)",
                   "es": "Coste total en el periodo (con depreciación)"},
    "value_retention_5y": {"en": "Value after 5 years", "ru": "Остаточная стоимость через 5 лет",
                           "es": "Valor a 5 años"},
    "reliability_score": {"en": "Reliability score", "ru": "Оценка надёжности", "es": "Fiabilidad"},
    "ground_clearance": {"en": "Ground clearance", "ru": "Клиренс", "es": "Altura libre"},
    "rear_legroom": {"en": "Rear legroom", "ru": "Место сзади", "es": "Espacio trasero"},
    "euro_ncap_stars": {"en": "Euro NCAP", "ru": "Euro NCAP", "es": "Euro NCAP"},
    "euro_ncap_year": {"en": "Euro NCAP year", "ru": "Год теста Euro NCAP", "es": "Año Euro NCAP"},
    "top_speed": {"en": "Top speed", "ru": "Максимальная скорость", "es": "Velocidad máxima"},
}  # fmt: skip
UNITS: dict[str, dict[str, str]] = {"EUR/year": {"en": "EUR/year", "ru": "€/год", "es": "€/año"},
                                    "years": {"en": "years", "ru": "лет", "es": "años"}}  # fmt: skip


def label(i: Insight, lang: str | None) -> str:
    t = LABELS.get(i.attribute)
    return t.get((lang or "en")[:2], t["en"]) if t else i.label


def _num(x: float, lang: str | None) -> str:
    s = f"{x:g}"
    return s.replace(".", ",") if (lang or "en")[:2] in ("ru", "es") else s


_S: dict[str, dict[str, str]] = {
    "WHY_AHEAD": {"en": "Why is the {car} ahead?", "ru": "Почему {car} впереди?", "es": "¿Por qué gana el {car}?"},
    "TIE_BREAK": {"en": "What would tip it for me?", "ru": "Что склонит выбор в мою пользу?",
                  "es": "¿Qué inclinaría la balanza para mí?"},
    "FIND_MISSING": {"en": "Find the missing data", "ru": "Найти недостающие данные",
                     "es": "Buscar los datos que faltan"},
    "COMPARE_RELIABILITY": {"en": "Compare them on reliability", "ru": "Сравнить по надёжности",
                            "es": "Compararlos en fiabilidad"},
    "WHAT_IF_USED": {"en": "And if I buy used, 3–5 years old?", "ru": "А если брать б/у, 3–5 лет?",
                     "es": "¿Y si compro de segunda mano, de 3–5 años?"},
    "CHEAPER_ALTERNATIVE": {"en": "A cheaper alternative to the {car}?", "ru": "Есть дешевле альтернатива {car}?",
                            "es": "¿Una alternativa más barata al {car}?"},
}  # fmt: skip


def suggestions_block(items: list[Any], names: Mapping[str, str], lang: str | None) -> dict[str, Any] | None:
    """One-click next steps (spec 004 FR-020). FIND_MISSING sends a "find it" request, the others a message."""
    out = []
    for i, sg in enumerate(items):
        table = _S[sg.kind]
        label = table.get((lang or "en")[:2], table["en"]).format(car=names.get(sg.car_id or "", ""))
        req: dict[str, Any] = {"kind": "find" if sg.kind == "FIND_MISSING" else "message", "text": label}
        if sg.kind == "FIND_MISSING":
            req |= {"focus_cars": list(sg.focus_cars), "areas": list(sg.areas)}
        out.append({"id": f"s{i + 1}-{sg.kind.lower()}", "label": label, "request": req})
    return {"type": "suggestions", "items": out} if out else None


def tr(key: str, lang: str | None, **kw: Any) -> str:
    table = _T[key]
    return table.get((lang or "en")[:2], table["en"]).format(**kw)


def _thousands(value: float, lang: str | None) -> str:
    """48,500 in English; 48.500 in Spanish and Russian (as before)."""
    s = f"{value:,.0f}"
    return s if (lang or "en")[:2] == "en" else s.replace(",", ".")


thousands = _thousands


def fmt(value: float, unit: str, lang: str | None = None) -> str:
    if unit == "EUR":
        return f"€{_thousands(value, lang)}"
    if unit in ("L", "kg", "mm", "N·m", "kW", "km/h"):
        return f"{_thousands(value, lang)} {unit}"
    if unit == "%":
        return f"{value:.0f}%"
    return f"{_num(round(value, 2), lang)} {unit}".strip()


def reason_text(i: Insight, names: Mapping[str, str], lang: str | None) -> str:
    best = i.cars[0]
    other = next((c for c in i.cars if c.car_id not in i.tiers[0]), i.cars[-1])
    text = tr("better", lang, label=label(i, lang), car=names.get(best.car_id, best.car_id),
              value=fmt(best.value, i.unit, lang), other=names.get(other.car_id, other.car_id),
              other_value=fmt(other.value, i.unit, lang), diff=fmt(i.diff, i.unit, lang))  # fmt: skip
    if i.money_per_year:
        text += tr("money", lang, eur=_thousands(i.money_per_year, lang))
    return text


FOCUS: dict[str, dict[str, str]] = {
    "PERFORMANCE": {"en": "driving and performance", "ru": "динамика и удовольствие от вождения",
                    "es": "la conducción y las prestaciones"},
    "BUYER": {"en": "practicality and running costs", "ru": "практичность и расходы",
              "es": "la practicidad y el coste"},
    "EXPERT": {"en": "engineering", "ru": "техника и инженерия", "es": "la ingeniería"},
}  # fmt: skip


AREA: dict[str, dict[str, str]] = {
    "price": {"en": "price", "ru": "цена", "es": "precio"},
    "specs": {"en": "specifications", "ru": "характеристики", "es": "ficha técnica"},
    "maintenance": {"en": "maintenance", "ru": "обслуживание", "es": "mantenimiento"},
    "reliability": {"en": "reliability", "ru": "надёжность", "es": "fiabilidad"},
    "reviews": {"en": "reviews", "ru": "отзывы", "es": "opiniones"},
    "manufacturer": {"en": "manufacturer", "ru": "производитель", "es": "fabricante"},
    "depreciation": {"en": "depreciation", "ru": "потеря стоимости", "es": "depreciación"},
    "used_price": {"en": "used price", "ru": "цена б/у", "es": "precio de ocasión"},
    "used_issues": {"en": "used-car issues", "ru": "проблемы б/у", "es": "problemas de ocasión"},
    "engineering": {"en": "engineering", "ru": "инженерия", "es": "ingeniería"},
    "measured": {"en": "measured tests", "ru": "замеры", "es": "mediciones"},
}


def area_label(area: str, lang: str | None) -> str:
    return _l(AREA, area, lang) if area in AREA else area.replace("_", " ")


def gap_text(gap: str, lang: str | None) -> str:
    """ "Mazda CX-5: price" in the chat's language."""
    car, sep, area = gap.rpartition(": ")
    return f"{car}{sep}{area_label(area, lang)}" if sep else area_label(gap, lang)


def _l(table: Mapping[str, Mapping[str, str]], key: str, lang: str | None) -> str:
    t = table.get(key) or {}
    return t.get((lang or "en")[:2], t.get("en", key))


def limit_text(x: Limit, names: Mapping[str, str], lang: str | None) -> str:
    return tr(x.kind, lang, car=names.get(x.car_id, x.car_id), value=fmt(x.value_eur, "EUR", lang),
              limit=fmt(x.limit_eur, "EUR", lang))  # fmt: skip


def _headline(v: Verdict, s: InsightSet, names: Mapping[str, str], lang: str | None) -> str:
    if v.not_enough_data:
        return tr("no_data", lang)
    if s.single:
        return tr("single", lang, car=next(iter(names.values()), ""))
    if v.tie:
        return tr("tie", lang, cars=" / ".join(names.get(c, c) for c in v.tied_cars))
    if v.best_if_budget and v.best_if_budget == v.pick_car_id:
        return tr("best_if_budget", lang, car=names.get(v.pick_car_id or "", ""))
    return tr("pick", lang, car=names.get(v.pick_car_id or "", ""))


def profile_lines(v: Verdict, names: Mapping[str, str], lang: str | None, years: int | None = None) -> list[str]:
    """What the profile changes in this verdict (spec 007 FR-017..FR-019): limits, another profile's pick,
    the payback against the user's period, missing used data. Code facts only."""
    out = [limit_text(x, names, lang) for x in v.limits]
    if v.best_if_budget and v.pick_car_id and v.best_if_budget != v.pick_car_id:
        out.append(tr("moved_pick", lang, best=names.get(v.best_if_budget, ""), car=names.get(v.pick_car_id, "")))
    t = v.trade_off
    if years and t is not None and (t.break_even_years or t.no_payback):
        be = t.break_even_years or 0.0
        key = "within_period" if be and be <= years else "beyond_period"
        if t.no_payback or be > MAX_BREAK_EVEN_YEARS:
            key = "no_payback"
        out.append(tr(key, lang, years=years, car=names.get(t.gain_car, t.gain_car), be=_num(be, lang)))
    if v.other_profile is not None:
        out.append(tr("other_profile", lang, focus=_l(FOCUS, v.other_profile.persona, lang),
                      car=names.get(v.other_profile.car_id, v.other_profile.car_id)))  # fmt: skip
    for u in v.used_missing:
        miss = ", ".join(tr(f"miss_{m}", lang) for m in u.missing)
        out.append(tr("used_missing", lang, car=names.get(u.car_id, u.car_id), missing=miss))
    return out


def verdict_block(
    v: Verdict, s: InsightSet, names: Mapping[str, str], lang: str | None, years: int | None = None
) -> dict[str, Any]:
    """The verdict card (contracts/report-blocks-and-protocol.md). Every number is from the insights."""
    gaps = ", ".join(gap_text(g, lang) for g in v.gaps[:4])
    headline = _headline(v, s, names, lang)
    if v.different_needs:
        headline = tr("different", lang) + headline[0].lower() + headline[1:]
    reasons = [{"text": reason_text(i, names, lang), "insight_id": i.id}
               for i in (s.get(r) for r in v.reasons) if i is not None]  # fmt: skip
    return {
        "type": "verdict",
        "headline": headline,
        "pick_car_id": v.pick_car_id,
        "tie": v.tie,
        "reasons": reasons,
        "trade_off": _trade(v, s, names, lang, years),
        "confidence": v.confidence,
        "confidence_reason": tr(f"conf_{v.confidence_reason}", lang, gaps=gaps or "—"),
        "would_change": _would_change(v, s, names, lang),
        "gaps": [gap_text(g, lang) for g in v.gaps],
        "profile_notes": profile_lines(v, names, lang, years),
        "best_if_budget": v.best_if_budget,
    }


def _trade(v: Verdict, s: InsightSet, names: Mapping[str, str], lang: str | None,
           years: int | None = None) -> dict[str, Any] | None:  # fmt: skip
    """The trade-off line. A payback is stated only on total cost (running + value lost): the cheaper-to-run car
    that is still dearer over the period is said to be dearer, with both totals (chat 5821ac77)."""
    t = v.trade_off
    if t is None:
        return None
    gain, cost = s.get(t.gain), s.get(t.cost)
    if gain is None or cost is None:
        return None
    if gain.id == "tco_period" or cost.id == "tco_period":
        return _trade_total(t, gain, cost, s, names, lang, years)
    yearly = gain.money_per_year is not None or gain.id == "tco_per_year"
    numbers = [{"label": label(gain, lang), "value": round(gain.money_per_year or gain.diff, 0),
                "unit": "EUR/year" if yearly else gain.unit},
               {"label": label(cost, lang), "value": cost.diff, "unit": cost.unit}]  # fmt: skip
    text = tr("trade_plain", lang, gain_car=names.get(t.gain_car, t.gain_car), gain=label(gain, lang),
              cost_car=names.get(t.cost_car, t.cost_car), cost=label(cost, lang))  # fmt: skip
    return {"text": text, "numbers": numbers}


def _value(i: Insight, car: str) -> float | None:
    return next((c.value for c in i.cars if c.car_id == car), None)


def _trade_total(t: Any, gain: Insight, cost: Insight, s: InsightSet, names: Mapping[str, str], lang: str | None,
                 years: int | None) -> dict[str, Any] | None:  # fmt: skip
    period = gain if gain.id == "tco_period" else cost
    g_total, c_total = _value(period, t.gain_car), _value(period, t.cost_car)
    if g_total is None or c_total is None:
        return None
    yrs = years or 5
    common = {
        "gain_car": names.get(t.gain_car, t.gain_car),
        "cost_car": names.get(t.cost_car, t.cost_car),
        "years": yrs,
        "gain_total": fmt(g_total, "EUR", lang),
        "cost_total": fmt(c_total, "EUR", lang),
    }
    numbers = [{"label": label(period, lang), "value": g_total, "unit": "EUR"},
               {"label": label(period, lang), "value": c_total, "unit": "EUR"}]  # fmt: skip
    be = t.break_even_years
    if gain.id == "tco_period":  # the dearer-to-buy car is cheaper over the period: it pays back within it
        price = s.get("official_price_es")
        p_g = _value(price, t.gain_car) if price else None
        p_c = _value(price, t.cost_car) if price else None
        if p_g is None or p_c is None or not be:
            return {"text": tr("trade_plain", lang, gain=label(gain, lang), cost=label(cost, lang), **common),
                    "numbers": numbers}  # fmt: skip
        extra = abs(p_g - p_c)
        numbers += [{"label": label(price, lang), "value": extra, "unit": "EUR"},  # type: ignore[arg-type]
                    {"label": "break-even", "value": be, "unit": "years"}]  # fmt: skip
        return {"text": tr("trade_total", lang, extra=fmt(extra, "EUR", lang), be=_num(be, lang), **common),
                "numbers": numbers}  # fmt: skip
    saving = round(gain.money_per_year or gain.diff, 0)
    numbers.insert(0, {"label": label(gain, lang), "value": saving, "unit": "EUR/year"})
    if be and be <= MAX_BREAK_EVEN_YEARS:
        numbers.append({"label": "break-even", "value": be, "unit": "years"})
        text = tr("trade_late", lang, saving=fmt(saving, "EUR", lang), be=_num(be, lang), **common)
    else:
        text = tr("trade_never", lang, saving=fmt(saving, "EUR", lang), **common)
    return {"text": text, "numbers": numbers}


def _would_change(v: Verdict, s: InsightSet, names: Mapping[str, str], lang: str | None) -> str | None:
    w = v.would_change
    if w is None:
        return None
    car = names.get(w.car_id or "", w.car_id or "")
    if w.kind == "BREAK_EVEN" and w.years:
        return tr("wc_break_even_short" if w.shorter else "wc_break_even", lang, years=_num(w.years, lang), car=car)
    if w.kind == "PRIORITY" and w.insight_id:
        i = s.get(w.insight_id)
        return tr("wc_priority", lang, label=label(i, lang) if i else w.insight_id, car=car)
    if w.kind == "DATA" and w.gaps:
        return tr("wc_data", lang, gaps=", ".join(gap_text(g, lang) for g in w.gaps[:4]))
    return None


def insights_for_llm(
    s: InsightSet, v: Verdict, names: Mapping[str, str], lang: str | None, years: int | None = None
) -> dict[str, Any]:
    """What the writer receives first (FR-009): the verdict, the meaningful differences, and what is the same."""
    return {
        "verdict": verdict_block(v, s, names, lang, years),
        "meaningful_differences": [
            {
                "attribute": i.label,
                "text": reason_text(i, names, lang),
                "relevance": i.relevance,
                "confidence": i.confidence,
                "winner": names.get(i.better_car or "", None),
            }
            for i in s.meaningful()
        ],  # fmt: skip
        "about_the_same": [label(i, lang) for i in (s.get(t) for t in s.ties) if i is not None],
    }


# --- electrified cars (spec 006 T050): share, cost per 100 km, break-even ------------------------------------
_E: dict[str, dict[str, str]] = {
    "share": {
        "en": "{car}: about {pct}% of your km on electricity (real electric range ≈{km} km)",
        "ru": "{car}: около {pct}% вашего пробега на электричестве (реальный запас хода ≈{km} км)",
        "es": "{car}: cerca del {pct}% de tus km en eléctrico (autonomía eléctrica real ≈{km} km)",
    },
    "share_no_range": {
        "en": "{car}: about {pct}% of your km on electricity",
        "ru": "{car}: около {pct}% вашего пробега на электричестве",
        "es": "{car}: cerca del {pct}% de tus km en eléctrico",
    },
    "cost": {
        "en": "{car}: €{home} per 100 km charging at home, €{public} at public chargers",
        "ru": "{car}: {home} € на 100 км при зарядке дома, {public} € — на общественных станциях",
        "es": "{car}: {home} € cada 100 km cargando en casa, {public} € en cargadores públicos",
    },
    "cost_one": {
        "en": "{car}: €{eur} per 100 km",
        "ru": "{car}: {eur} € на 100 км",
        "es": "{car}: {eur} € cada 100 km",
    },
    "YEARS": {
        "en": "Counting running costs and depreciation, the {e} pays back its higher price against the {c} in about "
        "{years} years",
        "ru": "С учётом расходов и потери стоимости {e} окупает разницу в цене с {c} примерно за {years} лет",
        "es": "Contando el uso y la depreciación, el {e} amortiza su mayor precio frente al {c} en unos {years} años",
    },
    "with_subsidy": {
        "en": "With the active subsidy (€{eur}), ",
        "ru": "С действующей субсидией ({eur} €) ",
        "es": "Con la ayuda vigente ({eur} €), ",
    },
    "beyond": {
        "en": " — longer than the {own} years you plan to keep it",
        "ru": " — дольше, чем вы планируете владеть ({own} лет)",
        "es": " — más que los {own} años que piensas tenerlo",
    },
    "NEVER": {
        "en": "Counting running costs and depreciation, the {e} costs more than the {c} and does not pay back its "
        "higher price within 15 years",
        "ru": "С учётом расходов и потери стоимости {e} обходится дороже {c} и не окупает разницу в цене даже за 15 "
        "лет",
        "es": "Contando el uso y la depreciación, el {e} cuesta más que el {c}: no se amortiza ni en 15 años",
    },
    "ALREADY_CHEAPER": {
        "en": "The {e} is cheaper than the {c} both to buy and to run",
        "ru": "{e} дешевле {c} и при покупке, и в эксплуатации",
        "es": "El {e} es más barato que el {c} de comprar y de usar",
    },
    "CHEAPER_TO_BUY": {
        "en": "The {e} is cheaper to buy than the {c} but dearer to run",
        "ru": "{e} дешевле {c} при покупке, но дороже в эксплуатации",
        "es": "El {e} es más barato de comprar que el {c}, pero más caro de usar",
    },
}


def _e(key: str, lang: str | None, **kw: Any) -> str:
    return _E[key].get((lang or "en")[:2], _E[key]["en"]).format(**kw)


def _money(x: float, lang: str | None) -> str:
    return _num(round(x, 2), lang)


def electric_lines(block: Mapping[str, Any] | None, break_even: Mapping[str, Any] | None,
                   names: Mapping[str, str], lang: str | None, *, years_said: bool = False) -> list[str]:  # fmt: skip
    """Sentences for the electrified cars, from the electric block and the break-even (numbers from code)."""
    out: list[str] = []
    for car in (block or {}).get("cars", []):
        name = names.get(car["car_id"], car["label"])
        v = car["values"]
        share = (v.get("electric_share") or {}).get("share")
        if share is not None and car.get("powertrain") != "BEV":
            km = (v.get("range") or {}).get("real_km")
            pct = f"{share * 100:.0f}"
            out.append(_e("share", lang, car=name, pct=pct, km=km) if km else
                       _e("share_no_range", lang, car=name, pct=pct))  # fmt: skip
        cost = v.get("cost_per_100km") or {}
        home, public = cost.get("home_eur"), cost.get("public_eur")
        if home is not None and public is not None:
            out.append(_e("cost", lang, car=name, home=_money(home, lang), public=_money(public, lang)))
        elif cost.get("used_eur") is not None:
            out.append(_e("cost_one", lang, car=name, eur=_money(cost["used_eur"], lang)))
    b = break_even or {}
    verdict = b.get("verdict")
    if verdict in ("YEARS", "NEVER", "ALREADY_CHEAPER", "CHEAPER_TO_BUY") and not (
        verdict == "YEARS" and years_said and not b.get("subsidy_eur")
    ):
        e = names.get(b["electrified_car_id"], b.get("electrified_label", ""))
        c = names.get(b["against_car_id"], b.get("against_label", ""))
        line = _e(verdict, lang, e=e, c=c, years=_num(b.get("years") or 0, lang))
        if verdict == "YEARS" and b.get("beyond_ownership") and b.get("ownership_years"):
            line += _e("beyond", lang, own=b["ownership_years"])
        if b.get("subsidy_eur"):  # the price trade-off above is without subsidies: say what this one counts
            first = line if (lang or "en")[:2] == "ru" else line[0].lower() + line[1:]
            line = _e("with_subsidy", lang, eur=_thousands(b["subsidy_eur"], lang)) + first
        out.append(line)
    return out
