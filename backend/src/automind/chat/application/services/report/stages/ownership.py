"""Stage ownership (spec 004 FR-027, spec 006 FR-001/FR-014/FR-023, chat 5821ac77): what each car costs to own — the
running costs per year checked for sense, the total over the ownership period including the value lost (only when
every compared car has it), the energy cost per 100 km, and a warning per car whose energy cost cannot be computed."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from automind.chat.application.services.report.blocks.notice import notice
from automind.chat.application.services.report.case_facts import (
    condition_of,
    recent_make,
    usage_context,
    years_of,
)
from automind.chat.application.services.report.contracts import ReportWording
from automind.chat.application.services.report.facts.car import short_name
from automind.chat.application.services.report.stages.used_cars import UsedFacts, used_price_of
from automind.chat.application.services.report.tco_inputs import tco_car
from automind.chat.domain import understanding
from automind.chat.domain.case import CaseFile
from automind.chat.domain.cost import tco
from automind.shared.contracts.config import Reference
from automind.shared.evidence import sense


@dataclass
class Ownership:
    """`costs`: running cost per year of the cars it is compared for; `totals`: over the period incl. value lost;
    `curves`: the total cost year by year; `eff`: energy € per 100 km."""

    tcars: list[tco.TcoCar]
    estimates: list[tco.TcoEstimate]
    costs: dict[str, float]
    totals: dict[str, float]
    curves: dict[str, tuple[float, ...]]
    eff: dict[str, float]
    years: int
    no_energy: set[str] = field(default_factory=set)  # car keys without an energy line


async def price_ownership(case: CaseFile, keyed: list[Any], ages: dict[str, int | None], used: dict[str, UsedFacts],
                          rates: tco.TcoRates, ref: Reference, notices: list[dict[str, Any]], lang: str,
                          words: ReportWording) -> Ownership:  # fmt: skip
    curve = (ref.feasibility or {}).get("depreciation") or {}
    use, recent = usage_context(case), recent_make(ref)
    stated = understanding.stated_for_cars(case.stated_energy, [(x.key, car["variant"].powertrain) for x, car in keyed])
    tcars = [await tco_car(car, condition_of(x.condition), ages[x.key], x.mileage_km, curve, use,
                           recent(getattr(car["variant"], "make", None)), stated.get(x.key), used_price_of(used, x.key))
             for x, car in keyed]  # fmt: skip
    estimates = tco.like_for_like([tco.compute(t, rates, case.annual_km, case.ownership_years) for t in tcars])
    costs = checked_costs(estimates, {car["variant"].id: ages[x.key] for x, car in keyed}, notices)
    totals = period_totals(estimates, costs)
    curves = {tc.car_id: cv for tc in tcars if tc.car_id in totals
              and (cv := tco.cost_curve(tc, rates, case.annual_km))}  # fmt: skip
    names = {car["variant"].id: short_name(car["variant"]) for _, car in keyed}
    notices += energy_notices(estimates, names, lang, words)
    no_energy = {x.key for x, car in keyed
                 if any(e.car_id == car["variant"].id and energy_missing(e) for e in estimates)}  # fmt: skip
    # the energy notice names the missing input; "specs: minimum not reached" for the same car only repeats it
    notices[:] = [n for n in notices if not (n.get("area") == "specs" and n.get("car_key") in no_energy
                                             and "car_id" not in n)]  # fmt: skip
    return Ownership(tcars, estimates, costs, totals, curves, per_100km(estimates), years_of(case, rates), no_energy)


def checked_costs(estimates: list[tco.TcoEstimate], ages: dict[str, int | None],
                  notices: list[dict[str, Any]]) -> dict[str, float]:  # fmt: skip
    """Sense check on the result (spec 004 FR-027): a yearly cost outside the configured range is an error upstream
    (EUR 513,672/year from a unit error). It is shown flagged and never scored."""
    out: dict[str, float] = {}
    for e in estimates:
        if energy_missing(e):  # spec 006 FR-014: a cost without its energy line is not compared
            continue
        r = sense.tco_per_year(e.annual_total, ages.get(e.car_id))
        if r.ok:
            out[e.car_id] = e.annual_total
        else:
            notices.append(notice(f"{e.label}: ownership cost {r.message} looks wrong; shown, not scored", "warning"))
    return out


def period_totals(estimates: list[tco.TcoEstimate], costs: dict[str, float]) -> dict[str, float]:
    """Total over the ownership period, running costs plus the value lost, for the cars whose running cost is
    compared (chat 5821ac77). Empty unless every one of them has its value loss: a total without it would make
    the car with unknown depreciation look cheaper."""
    cars = [e for e in estimates if e.car_id in costs]
    if not cars or not all(tco.depreciation_known(e) for e in cars):
        return {}
    return {e.car_id: e.period_total for e in cars}


def per_100km(estimates: list[tco.TcoEstimate]) -> dict[str, float]:
    """Energy cost per 100 km per car (spec 006 FR-023), only where the energy line could be computed."""
    out = {}
    for e in estimates:
        item = next((i for i in e.items if i.kind == "ENERGY"), None)
        if item is not None and item.estimate is not None and item.estimate.eur_per_100km is not None:
            out[e.car_id] = item.estimate.eur_per_100km
    return out


def energy_missing(e: tco.TcoEstimate) -> list[str]:
    return next((i.missing for i in e.items if i.kind == "ENERGY" and i.missing), [])


def energy_notices(estimates: list[tco.TcoEstimate], names: dict[str, str], lang: str | None,
                   words: ReportWording) -> list[dict[str, Any]]:  # fmt: skip
    """One warning per car whose energy cost cannot be computed, naming the missing inputs (spec 006 FR-001)."""
    out = []
    for e in estimates:
        if miss := energy_missing(e):
            what = ", ".join(words.energy_input(m, lang) for m in miss)
            out.append(notice(words.t("energy_missing", lang, car=names.get(e.car_id, e.label), missing=what),
                              "warning", car_id=e.car_id, area="energy"))  # fmt: skip
    return out


def energy_price(t: tco.TcoCar, r: tco.TcoRates) -> float:
    """What a unit of the car's energy costs (kWh at home, litre of diesel or petrol)."""
    if t.powertrain == "BEV":
        return r.energy.home.value
    return r.diesel_eur_per_l if t.fuel == "diesel" else r.fuel_eur_per_l


def buy_price(t: tco.TcoCar) -> float | None:
    """What the car costs to buy: a used car's sourced used price, never its new price (spec 008 FR-023)."""
    return t.used_price_eur if t.condition == "USED" else t.price_eur


def ownership_facts(estimates: list[tco.TcoEstimate], totals: dict[str, float], years: int,
                    names: dict[str, str], iset: Any = None) -> dict[str, Any]:  # fmt: skip
    """Ownership cost for the writer (chat 5821ac77): the total over the period including depreciation is THE
    comparison; running costs per year are labelled as without depreciation. Code decides which car is cheaper."""
    cars = []
    for e in estimates:
        dep = next((i.five_year_eur for i in e.items if i.kind == "DEPRECIATION"), None)
        row: dict[str, Any] = {
            "car": names.get(e.car_id, e.label),
            "running_costs_per_year_without_depreciation_eur": e.annual_total,
            "items": [{"kind": i.kind, "annual_eur": i.annual_eur, "basis": i.basis} for i in e.items],
        }
        if e.car_id in totals:
            row["total_over_the_period_including_depreciation_eur"] = totals[e.car_id]
            row["depreciation_over_the_period_eur"] = dep
        cars.append(row)
    out: dict[str, Any] = {"period_years": years, "cars": cars}
    period = iset.get("tco_period") if iset is not None else None
    if len(totals) >= 2 and period is not None and period.meaningful:
        cheap = [names.get(c, c) for c in period.tiers[0]]
        out["cheaper_to_own_over_the_period"] = " / ".join(cheap)
        out["costlier_to_own_over_the_period"] = list(costlier_names(iset, names))
        out["difference_over_the_period_eur"] = period.diff
        out["rule"] = (
            "Compare ownership cost ONLY on the totals including depreciation. Running costs per year "
            "may be quoted only as 'running costs (without depreciation)' and never as a saving."
        )
    elif len(totals) >= 2:
        out["about_the_same_over_the_period"] = True
        out["rule"] = (
            "The totals including depreciation are about the same: name no car as cheaper to own. Running "
            "costs per year may be quoted only as 'running costs (without depreciation)'."
        )
    else:
        out["rule"] = (
            "Depreciation is not known for every car: these are running costs only. Say so; never claim "
            "that a car saves money or pays back."
        )
    return out


def costlier_names(iset: Any, names: dict[str, str]) -> tuple[str, ...]:
    """The cars whose total over the period (running + value lost) is meaningfully higher than the cheapest one:
    the text may never call them the saving (chat 5821ac77)."""
    period = iset.get("tco_period") if iset is not None else None
    if period is None or not period.meaningful:
        return ()
    best = set(period.tiers[0])
    return tuple(sorted(names[c.car_id] for c in period.cars if c.car_id not in best and c.car_id in names))
