"""What the case says about the comparison, for the report: the person's facts as lines, the usage the energy
model needs, what the costs assume that the person never said, the ownership period, and the makes new in the
market (spec 004 FR-029, spec 006, spec 007 FR-016, spec 008 FR-027; chat 5821ac77)."""

from __future__ import annotations

from collections.abc import Callable

from automind.chat.application.services.feasibility import feasibility as fz_app
from automind.chat.application.services.report.contracts import ReportWording
from automind.chat.domain.case import CaseFile
from automind.chat.domain.cost import tco
from automind.chat.domain.cost.energy import UsageContext
from automind.shared.contracts.config import Reference


def case_facts(case: CaseFile) -> list[str]:
    """The facts the person gave, as short lines for the case summary (assumed values marked as assumed)."""
    out = []
    if case.profile.age:
        out.append(f"age {case.profile.age}")
    if case.usage:
        out.append("usage: " + ", ".join(u.lower() for u in case.usage))
    out += [x[0].lower() + x[1:] for x in fz_app.constraint_lines(case)]
    if case.priorities:
        out.append("priorities: " + ", ".join(p.criterion.replace("_", " ") for p in case.priorities))
    out.append(f"{case.annual_km:,} km per year" + (" (assumed)" if km_assumed(case) else ""))
    for x in case.cars:  # spec 008 FR-027: a used car is labelled as used, an assumed year as assumed
        if x.condition == "USED":
            yr = (f"~{x.year} (assumed)" if x.year_assumed else str(x.year)) if x.year else "year unknown"
            km = f", {x.mileage_km:,} km" if x.mileage_km else ""
            out.append(f"{x.label or x.request_text}: used, {yr}{km}")
    if len(case.cars) > 1 and any(x.condition != "USED" for x in case.cars):  # spec 004 FR-029
        why = (
            "the level of the version you named"
            if case.compare_level_source == "USER_TRIM"
            else ("the cheapest version on sale; name a version to change it")
        )
        out.append(f"compared at the {case.compare_level.lower()} equipment level ({why})")
    return out


def km_assumed(case: CaseFile) -> bool:
    """The yearly mileage is assumed: the person never stated it."""
    return case.basis.get("annual_km", "ASSUMED") == "ASSUMED" and not case.annual_km_stated


def years_of(case: CaseFile, rates: tco.TcoRates) -> int:
    """The ownership period: the person's, else the rates' horizon."""
    return case.ownership_years or rates.horizon_years


def assumption_lines(case: CaseFile, rates: tco.TcoRates, lang: str | None, words: ReportWording) -> list[str]:
    """One short line for what the costs assume and the user never said (annual km, years of ownership), with the
    value and an invitation to correct it (chat 5821ac77: 15,000 km a year was assumed silently)."""
    km = km_assumed(case)
    yrs = case.ownership_years is None or case.basis.get("ownership_years", "ASSUMED") == "ASSUMED"
    if not km and not yrs:
        return []
    key = "assumed_km_years" if km and yrs else "assumed_km" if km else "assumed_years"
    return [words.t(key, lang, km=words.thousands(case.annual_km, lang), years=years_of(case, rates))]


def usage_context(case: CaseFile) -> UsageContext:
    """What the energy model needs from the case (spec 006): km, daily distance, climate, usage, home charging."""
    return UsageContext(annual_km=case.annual_km, daily_km=case.needs.daily_km, climate=case.profile.climate,
                        usage=tuple(case.usage),
                        home_charging=getattr(case.profile, "home_charging", None) or "UNKNOWN")  # fmt: skip


def recent_make(ref: Reference) -> Callable[[str | None], bool]:
    """A make new in the Spanish market (makes.yaml): no class depreciation curve for it (spec 006 FR-018)."""
    reg = getattr(ref, "makes", None)
    return reg.new_in_market if reg is not None else (lambda _make: False)


def condition_of(condition: str) -> str:
    """The condition the costs know: USED, else NEW."""
    return "USED" if condition == "USED" else "NEW"
