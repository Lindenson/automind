"""The ownership cost of one car over the period (compute), its year-by-year curve, payback between two cars and the
like-for-like check."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import replace

from automind.chat.domain.cost.tco.items import (
    big_tickets_item,
    depreciation_item,
    energy_item,
    maintenance_item,
    reserve_item,
    road_tax_item,
    tyres_item,
)
from automind.chat.domain.cost.tco.model import TcoCar, TcoEstimate, TcoRates


def compute(car: TcoCar, rates: TcoRates, annual_km: int | None = None, years: int | None = None) -> TcoEstimate:
    km = annual_km or rates.annual_km
    years = years or rates.horizon_years
    items = [
        maintenance_item(car, rates, km, years),
        energy_item(car, rates, km, years),
        tyres_item(car, rates, km, years),
        road_tax_item(car, rates, years),
    ]
    if car.condition == "USED":
        items += big_tickets_item(car, rates, km, years)
        items.append(reserve_item(car, rates, years))
    items.append(depreciation_item(car, years))
    running = [i for i in items if i.kind != "DEPRECIATION"]
    annual = round(sum(i.annual_eur for i in running if i.annual_eur is not None), 2)
    period = round(sum(i.five_year_eur for i in items if i.five_year_eur is not None), 2)
    return TcoEstimate(car.car_id, car.label, car.condition, car.age_years, km, items, annual, period, years=years)


MAX_PAYBACK_YEARS = 15  # beyond this a payback is no payback (incident 2026-11-03: "after 77 years")


def depreciation_known(e: TcoEstimate) -> bool:
    """The period total of `e` includes the value the car loses (chat 5821ac77: a verdict on running costs alone
    called the dearer car the saving)."""
    return not e.depreciation_left_out and any(i.kind == "DEPRECIATION" and i.five_year_eur is not None
                                               for i in e.items)  # fmt: skip


def cost_curve(car: TcoCar, rates: TcoRates, annual_km: int | None = None,
               max_years: int = MAX_PAYBACK_YEARS) -> tuple[float, ...]:  # fmt: skip
    """Total cost of owning `car` (running costs + value lost) after 1..max_years years, from the same model as the
    period total. Empty when the value loss is not known: a payback is never computed from running costs alone."""
    out = []
    for t in range(1, max_years + 1):
        e = compute(car, rates, annual_km, t)
        if not depreciation_known(e):
            return ()
        out.append(e.period_total)
    return tuple(out)


def payback_years(dear: Sequence[float], cheap: Sequence[float]) -> float | None:
    """When the total cost of `dear` (the car that costs more at first) drops to the total of `cheap`: years,
    interpolated between whole years, rounded up to 0.5. None when it never does within the curves."""
    n = min(len(dear), len(cheap))
    prev = 0.0
    for t in range(n):
        d = dear[t] - cheap[t]
        if d <= 0:
            if t == 0:
                return 1.0
            frac = prev / (prev - d) if prev != d else 1.0
            return max(1.0, math.ceil(round((t + frac) * 2, 6)) / 2)
        prev = d
    return None


def like_for_like(estimates: list[TcoEstimate]) -> list[TcoEstimate]:
    """When depreciation is known for some cars and not for others, the period totals leave it out for all, so
    one car is never cheaper only because its value loss is unknown (spec 006 FR-014)."""

    def known(e: TcoEstimate) -> bool:
        return any(i.kind == "DEPRECIATION" and i.annual_eur is not None for i in e.items)

    if len({known(e) for e in estimates}) < 2:
        return estimates
    out = []
    for e in estimates:
        running = round(sum(i.five_year_eur for i in e.items if i.kind != "DEPRECIATION"
                            and i.five_year_eur is not None), 2)  # fmt: skip
        out.append(replace(e, five_year_total=running, depreciation_left_out=True))
    return out
