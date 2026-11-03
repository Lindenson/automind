"""Phrasing of the code-built verdict and insights (spec 004 US1, FR-001). The structure and every number come
from domain.verdict / domain.insights; this module only writes them in ru / es / en. Deterministic.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from automind.domain.insights import Insight, InsightSet
from automind.domain.verdict import Verdict

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
    "trade": {
        "en": "{gain_car} wins on {gain} but costs {extra} more to buy; it pays back in about {years} years",
        "ru": "{gain_car} выигрывает по показателю «{gain}», но дороже на {extra}; окупится примерно за {years} лет",
        "es": "{gain_car} gana en {gain} pero cuesta {extra} más; se amortiza en unos {years} años",
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


def tr(key: str, lang: str | None, **kw: Any) -> str:
    table = _T[key]
    return table.get((lang or "en")[:2], table["en"]).format(**kw)


def fmt(value: float, unit: str) -> str:
    if unit == "EUR":
        return f"€{value:,.0f}".replace(",", ".")
    if unit in ("L", "kg", "mm", "N·m", "kW", "km/h"):
        return f"{value:,.0f} {unit}".replace(",", ".")
    if unit == "%":
        return f"{value:.0f}%"
    return f"{value:g} {unit}".strip()


def reason_text(i: Insight, names: Mapping[str, str], lang: str | None) -> str:
    best = i.cars[0]
    other = next((c for c in i.cars if c.car_id not in i.tiers[0]), i.cars[-1])
    text = tr("better", lang, label=i.label, car=names.get(best.car_id, best.car_id), value=fmt(best.value, i.unit),
              other=names.get(other.car_id, other.car_id), other_value=fmt(other.value, i.unit),
              diff=fmt(i.diff, i.unit))  # fmt: skip
    if i.money_per_year:
        text += tr("money", lang, eur=f"{i.money_per_year:,.0f}".replace(",", "."))
    return text


def verdict_block(v: Verdict, s: InsightSet, names: Mapping[str, str], lang: str | None) -> dict[str, Any]:
    """The verdict card (contracts/report-blocks-and-protocol.md). Every number is from the insights."""
    gaps = ", ".join(v.gaps[:4])
    if v.not_enough_data:
        headline = tr("no_data", lang)
    elif s.single:
        headline = tr("single", lang, car=next(iter(names.values()), ""))
    elif v.tie:
        headline = tr("tie", lang, cars=" / ".join(names.get(c, c) for c in v.tied_cars))
    else:
        headline = tr("pick", lang, car=names.get(v.pick_car_id or "", ""))
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
        "trade_off": _trade(v, s, names, lang),
        "confidence": v.confidence,
        "confidence_reason": tr(f"conf_{v.confidence_reason}", lang, gaps=gaps or "—"),
        "would_change": _would_change(v, s, names, lang),
        "gaps": list(v.gaps),
    }


def _trade(v: Verdict, s: InsightSet, names: Mapping[str, str], lang: str | None) -> dict[str, Any] | None:
    t = v.trade_off
    if t is None:
        return None
    gain, cost = s.get(t.gain), s.get(t.cost)
    if gain is None or cost is None:
        return None
    numbers = [{"label": gain.label, "value": gain.money_per_year or gain.diff,
                "unit": "EUR/year" if gain.money_per_year else gain.unit},
               {"label": cost.label, "value": cost.diff, "unit": cost.unit}]  # fmt: skip
    if t.break_even_years:
        price = {c.car_id: c.value for c in cost.cars}
        extra = abs(price.get(t.gain_car, 0.0) - price.get(t.cost_car, 0.0))
        numbers[1] = {"label": cost.label, "value": extra, "unit": cost.unit}
        text = tr("trade", lang, gain_car=names.get(t.gain_car, t.gain_car), gain=gain.label,
                  extra=fmt(extra, cost.unit), years=f"{t.break_even_years:g}")  # fmt: skip
        numbers.append({"label": "break-even", "value": t.break_even_years, "unit": "years"})
    else:
        text = tr("trade_plain", lang, gain_car=names.get(t.gain_car, t.gain_car), gain=gain.label,
                  cost_car=names.get(t.cost_car, t.cost_car), cost=cost.label)  # fmt: skip
    return {"text": text, "numbers": numbers}


def _would_change(v: Verdict, s: InsightSet, names: Mapping[str, str], lang: str | None) -> str | None:
    w = v.would_change
    if w is None:
        return None
    car = names.get(w.car_id or "", w.car_id or "")
    if w.kind == "BREAK_EVEN" and w.years:
        return tr("wc_break_even", lang, years=f"{w.years:g}", car=car)
    if w.kind == "PRIORITY" and w.insight_id:
        i = s.get(w.insight_id)
        return tr("wc_priority", lang, label=i.label if i else w.insight_id, car=car)
    if w.kind == "DATA" and w.gaps:
        return tr("wc_data", lang, gaps=", ".join(w.gaps[:4]))
    return None


def insights_for_llm(s: InsightSet, v: Verdict, names: Mapping[str, str], lang: str | None) -> dict[str, Any]:
    """What the writer receives first (FR-009): the verdict, the meaningful differences, and what is the same."""
    return {
        "verdict": verdict_block(v, s, names, lang),
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
        "about_the_same": [s.get(t).label for t in s.ties if s.get(t) is not None],  # type: ignore[union-attr]
    }
