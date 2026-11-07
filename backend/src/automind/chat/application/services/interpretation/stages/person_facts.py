"""Facts about the person and the cars read by code from the person's own words (spec 005 R11, spec 006 R5/R7,
spec 007 US7): region and climate, a yearly distance, where they charge and their electricity price, the body they
want, and the answer to "new or used?"."""

from __future__ import annotations

from collections.abc import Mapping

from automind.chat.domain import intake, understanding
from automind.chat.domain.case import CaseFile

EVIDENCE_CHARS = 120  # the person's words kept as the evidence of a yearly distance
REGION_CHARS = 60  # the region's name as stored in the profile


def person_from_text(new: CaseFile, before: CaseFile, text: str,
                     regions: Mapping[str, Mapping[str, object]]) -> list[str]:  # fmt: skip
    """Sets what the words state on `new` (in place): region, yearly distance, charging, the wanted body (before any
    car), and "new or used" for every car still UNKNOWN when that was the pending question. Returns the change log."""
    p = new.profile
    log: list[str] = []
    if (r := understanding.region_of(text, regions)) is not None and r[0] != p.region_code:
        p.region, p.region_code, p.climate = r[2][:REGION_CHARS], r[0], r[1]
        p.evidence["region"] = r[2]
        log.append(f"region {r[2]} ({r[1].lower()} climate)")
    if (d := understanding.parse_distance(text)) is not None and (d[0], d[1]) != (p.annual_km_min, p.annual_km_max):
        p.annual_km_min, p.annual_km_max = d
        new.annual_km, new.annual_km_stated = round((d[0] + d[1]) / 2 / 500) * 500, True
        p.evidence["annual_km"] = text[:EVIDENCE_CHARS]
        log.append(f"{d[0]:,}–{d[1]:,} km a year" if d[0] != d[1] else f"{d[0]:,} km a year")
    log += _charging_from_text(new, text)
    if not new.cars and (body := intake.body_of(text)) and body != new.wanted_body:
        new.wanted_body = body
        log.append(f"body wanted: {body}")
    return log + _condition_answered(new, before, text)


def _charging_from_text(new: CaseFile, text: str) -> list[str]:
    """Where the person can charge and their own electricity price (spec 006 R5, R7)."""
    log: list[str] = []
    p = new.profile
    if (ch := understanding.charging_of(text)) is not None and ch[0] != p.home_charging:
        p.home_charging = ch[0]
        p.evidence["home_charging"] = ch[1]
        new.basis["home_charging"] = "STATED"
        log.append(f'charging: {ch[0].lower()} ("{ch[1]}")')
    if (pr := understanding.electricity_price_of(text)) is not None:
        r = new.rates_override
        if pr[0] != r.home_electricity_eur_per_kwh or (pr[1] and not r.night_tariff):
            r.home_electricity_eur_per_kwh, r.night_tariff = pr[0], (pr[1] or r.night_tariff)
            log.append(f"electricity: €{pr[0]:.3f}/kWh (your price){' at night' if pr[1] else ''}")
    return log


def _condition_answered(new: CaseFile, before: CaseFile, text: str) -> list[str]:
    """The answer to a pending "new or used?" for every car still UNKNOWN."""
    asked = before.pending is not None and any(it.get("kind") == "CONDITION" for it in before.pending.items)
    if not asked or (cond := understanding.condition_of(text)) is None:
        return []
    log: list[str] = []
    for car in new.cars:
        if car.condition == "UNKNOWN":
            car.condition = cond
            log.append(f"{car.key}: {cond.lower()}")
    return log
