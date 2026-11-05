"""Environmental label, incentive status and break-even (spec 006 US5, FR-015, FR-016; research R9, R11). Pure.

- The DGT label follows the published rule from the powertrain, the electric range and the fuel and year
  (Euro standard by first registration): it is DERIVED, shown with the rule and its source.
- An incentive counts only while it is ACTIVE (dates) and has an amount; an expired one is shown as expired.
- Break-even: in how many years the lower running cost pays back the higher price, at the user's km.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date

from .tco import payback_years

DGT_SOURCE = "https://www.dgt.es/muevete-con-seguridad/tecnologia-e-innovacion-en-carretera/distintivo-ambiental/"
ZERO_MIN_RANGE_KM = 40
PETROL_C_FROM, DIESEL_C_FROM = 2006, 2015  # Euro 4 petrol / Euro 6 diesel
PETROL_B_FROM, DIESEL_B_FROM = 2001, 2006  # Euro 3 petrol / Euro 4–5 diesel
ELECTRIFIED = ("BEV", "PHEV", "EREV")


@dataclass(frozen=True)
class EnvLabel:
    label: str  # ZERO | ECO | C | B | NONE | UNKNOWN
    rule: str
    source_url: str = DGT_SOURCE


def env_label(powertrain: str | None, range_ev_km: float | None, fuel: str | None, year: int | None) -> EnvLabel:
    pt = (powertrain or "ICE").upper()
    if pt in ("BEV", "EREV"):
        return EnvLabel("ZERO", f"{'electric' if pt == 'BEV' else 'range extender'}: ZERO")
    if pt == "PHEV":
        if range_ev_km is None:
            return EnvLabel("UNKNOWN", "plug-in: ZERO from 40 km electric range, ECO below; range not found")
        if range_ev_km >= ZERO_MIN_RANGE_KM:
            return EnvLabel("ZERO", f"plug-in with {range_ev_km:.0f} km electric range (≥ 40 km): ZERO")
        return EnvLabel("ECO", f"plug-in with {range_ev_km:.0f} km electric range (< 40 km): ECO")
    if pt in ("HEV", "MHEV"):
        return EnvLabel("ECO", f"{'full' if pt == 'HEV' else 'mild'} hybrid: ECO")
    if year is None:
        return EnvLabel("UNKNOWN", "combustion: the label depends on the year (Euro standard); year not known")
    diesel = (fuel or "petrol") == "diesel"
    c_from, b_from = (DIESEL_C_FROM, DIESEL_B_FROM) if diesel else (PETROL_C_FROM, PETROL_B_FROM)
    kind = "diesel" if diesel else "petrol"
    if year >= c_from:
        return EnvLabel("C", f"{kind} registered from {c_from}: C")
    if year >= b_from:
        return EnvLabel("B", f"{kind} registered {b_from}–{c_from - 1}: B")
    return EnvLabel("NONE", f"{kind} registered before {b_from}: no label")


@dataclass(frozen=True)
class Incentive:
    key: str
    label: str
    amount_eur: float | None = None
    valid_from: date | None = None
    valid_to: date | None = None
    evidence_ids: tuple[str, ...] = ()


def status(i: Incentive, today: date) -> str:
    """ACTIVE / EXPIRED / UNKNOWN from the dates; an unsourced fact is never ACTIVE."""
    if not i.evidence_ids:
        return "UNKNOWN"
    if i.valid_to is not None and i.valid_to < today:
        return "EXPIRED"
    if i.valid_from is not None and i.valid_from > today:
        return "UNKNOWN"
    return "ACTIVE" if i.valid_to is not None or i.valid_from is not None else "UNKNOWN"


def deductible(incentives: list[Incentive], today: date) -> float:
    return sum(i.amount_eur or 0 for i in incentives if status(i, today) == "ACTIVE" and i.amount_eur)


@dataclass(frozen=True)
class BreakEven:
    verdict: str  # YEARS | NEVER | ALREADY_CHEAPER (to buy and to run) | CHEAPER_TO_BUY (dearer to run) | UNKNOWN
    years: float | None
    inputs: list[str] = field(default_factory=list)
    beyond_ownership: bool = False


def break_even(price_e: float | None, price_c: float | None, running_e: float | None, running_c: float | None,
               *, subsidy_eur: float = 0.0, ownership_years: int | None = None,
               curve_e: Sequence[float] | None = None,
               curve_c: Sequence[float] | None = None) -> BreakEven:  # fmt: skip
    """The electrified car (e) against the combustion one (c): years until e's total cost — running costs plus the
    value it loses, year by year (`curve_*`, from domain.tco.cost_curve) — drops to c's. Running costs alone never
    give a payback (chat 5821ac77: a new car losing €5,000 a year "paid back in 3.5 years"): without the curves a
    dearer car's payback is UNKNOWN."""
    if None in (price_e, price_c, running_e, running_c):
        return BreakEven("UNKNOWN", None, ["price or running cost missing"])
    assert price_e is not None and price_c is not None and running_e is not None and running_c is not None
    extra = price_e - subsidy_eur - price_c
    saving = running_c - running_e
    inputs = [f"price difference €{extra:,.0f}" + (f" (after €{subsidy_eur:,.0f} active subsidy)" if subsidy_eur
                                                    else " (no active subsidy counted)"),
              f"running cost €{running_e:,.0f} vs €{running_c:,.0f} a year (without depreciation)"]  # fmt: skip
    if extra <= 0:
        return BreakEven("ALREADY_CHEAPER", 0.0, inputs) if saving >= 0 else BreakEven("CHEAPER_TO_BUY", None, inputs)
    if not curve_e or not curve_c:
        return BreakEven("UNKNOWN", None, [*inputs, "value loss not known for both cars: no payback computed"])
    inputs.append("total cost per year of ownership includes the value each car loses (depreciation)")
    e_total = [x - subsidy_eur for x in curve_e]
    years = payback_years(e_total, curve_c)
    if years is None:
        return BreakEven("NEVER", None, inputs)
    return BreakEven("YEARS", years, inputs, bool(ownership_years and years > ownership_years))
