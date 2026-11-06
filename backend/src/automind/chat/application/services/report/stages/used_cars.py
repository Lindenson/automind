"""Stage used_cars (spec 008 FR-022, FR-023, FR-026, FR-027): a used car is costed at its age, never as new — an
assumed age is said — and its own figures are read: the year, the sourced used price and what is left of the
maker's warranty."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from automind.chat.application.services.report.blocks.notice import notice
from automind.chat.application.services.report.contracts import ReportWording
from automind.chat.application.services.report.facts.car import short_name, used_price, warranty_years
from automind.chat.domain.case import CaseFile
from automind.chat.domain.identification import used
from automind.shared.contracts.config import Reference

DEFAULT_YEAR = 2026  # the clock's year when no clock is given (tests)
_YEAR_ASSUMED = {"ru": ", год предположен", "es": ", año supuesto"}  # the warranty notice's tail; else English


@dataclass
class UsedFacts:
    """What a used car is worth and covered by now (spec 008 FR-023, FR-026)."""

    year: int
    price: used.UsedPrice | None
    warranty: used.Warranty


def car_age(x: Any, v: Any, ref: Reference, year: int | None, notices: list[dict[str, Any]], lang: str,
            words: ReportWording) -> int | None:  # fmt: skip
    """A used car is costed at its age, never as new (spec 008 FR-022): an assumed year is said in a notice; a car
    with no age at all (a case from before 008) gets one assumed here."""
    if x.condition != "USED":
        return x.age_years
    now = year or DEFAULT_YEAR
    age, how = x.age_years, None
    if age is None:
        cfg = dict((ref.search or {}).get("intake") or {})
        age, how = used.assumed_age(x.mileage_km, getattr(v, "generation_years_from", None),
                                    getattr(v, "generation_years_to", None), now,
                                    km_per_year=int(cfg.get("km_per_year_used", used.KM_PER_YEAR_USED)),
                                    default=int(cfg.get("default_used_age", used.DEFAULT_USED_AGE)))  # fmt: skip
    elif x.year_assumed:
        how = f"{x.mileage_km:,} km at ~15,000 km a year" if x.mileage_km else "no year given"
    if how is not None:
        text = words.t("used_age_assumed", lang, car=short_name(v), age=age, how=how)
        if all(n.get("text") != text for n in notices):
            notices.append(notice(text, "info"))
    return max(1, age)


def used_facts(keyed: list[Any], ages: dict[str, int | None], year: int | None, notices: list[dict[str, Any]],
               lang: str, words: ReportWording) -> dict[str, UsedFacts]:  # fmt: skip
    """Per used car's key: its year, sourced used price and warranty; the missing price and the warranty said."""
    now = year or DEFAULT_YEAR
    out: dict[str, UsedFacts] = {}
    for x, car in keyed:
        if x.condition != "USED":
            continue
        built = x.year or now - (ages.get(x.key) or 1)
        price = used_price(car, built)
        w = used.warranty_status(built, warranty_years(car), now, assumed=x.year_assumed or x.year is None)
        out[x.key] = UsedFacts(built, price, w)
        name = short_name(car["variant"])
        if price is None:
            notices.append(notice(words.t("used_price_missing", lang, car=name, year=built), "info", car_key=x.key))
        if w.state != "UNKNOWN":
            assumed = _YEAR_ASSUMED.get(lang, ", year assumed") if w.assumed else ""
            key = "warranty_remaining" if w.state == "REMAINING" else "warranty_expired"
            notices.append(notice(words.t(key, lang, car=name, year=built, assumed=assumed, years=f"{w.years:g}",
                                          until=w.until), "info", car_key=x.key))  # fmt: skip
    return out


def used_price_of(facts: dict[str, UsedFacts], car_key: str) -> float | None:
    """The sourced used price of a used car (None for a new car or without a source)."""
    u = facts.get(car_key)
    return u.price.eur if u is not None and u.price is not None else None


def used_lines(case: CaseFile, facts: dict[str, UsedFacts]) -> list[str]:
    """The used cars' own figures for the report (FR-027): year (stated or assumed), mileage, price, warranty."""
    out = []
    for x in case.cars:
        u = facts.get(x.key)
        if u is None:
            continue
        bits = [f"{x.label or x.request_text}: USED, year {u.year}" + (" (assumed)" if x.year_assumed else "")]
        if x.mileage_km:
            bits.append(f"{x.mileage_km:,} km")
        bits.append(f"price used €{u.price.eur:,.0f} (sourced)" if u.price else "price used: no sourced data")
        if u.warranty.state != "UNKNOWN":
            bits.append(f"maker's warranty {'until' if u.warranty.state == 'REMAINING' else 'expired in'} "
                        f"{u.warranty.until}" + (" (assumed year)" if u.warranty.assumed else ""))  # fmt: skip
        else:
            bits.append("maker's warranty: no sourced terms")
        out.append("; ".join(bits))
    return out
