"""A used car costed and scored as used (spec 008 US4). Pure.

- `assumed_age`: the age of a used car whose year was not given: from the mileage, else the middle of its
  generation, else a default — never 0 (chat 9b5c0b0c: an old Audi was costed as new).
- `used_price_for`: the sourced used market price for the car's year (the purchase price of a used car; never
  the new price, FR-023).
- `warranty_status`: the maker's warranty remaining or expired, from the first registration year (FR-026).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

KM_PER_YEAR_USED = 15000  # average Spanish yearly distance (config intake.km_per_year_used)
DEFAULT_USED_AGE = 5


def assumed_age(mileage_km: int | None, gen_from: int | None, gen_to: int | None, now_year: int, *,
                km_per_year: int = KM_PER_YEAR_USED, default: int = DEFAULT_USED_AGE) -> tuple[int, str]:  # fmt: skip
    """(years ≥ 1, how) for a used car without a year."""
    if mileage_km:
        return max(1, round(mileage_km / km_per_year)), f"{mileage_km:,} km at ~{km_per_year:,} km a year"
    if gen_from:
        mid = (gen_from + min(gen_to or now_year, now_year)) / 2
        return max(1, int(now_year - mid + 0.5)), f"middle of its generation ({gen_from}–{gen_to or 'now'})"
    return max(1, default), "no year, mileage or generation known"


@dataclass(frozen=True)
class UsedRange:
    """One sourced used-price range (table used_price_ranges)."""

    min_eur: float
    max_eur: float
    year_from: int | None
    year_to: int | None
    url: str = ""


@dataclass(frozen=True)
class UsedPrice:
    eur: float
    year_from: int | None
    year_to: int | None
    url: str
    exact_year: bool  # the range covers the car's year (else the nearest within a year)


def used_price_for(ranges: Sequence[UsedRange], year: int | None) -> UsedPrice | None:
    """The middle of the sourced range for the car's year; a range one year away when none covers it; else None.
    Without a year, only a range that names no years (a price for the whole generation)."""

    def covers(r: UsedRange, y: int, slack: int) -> bool:
        lo, hi = r.year_from or r.year_to, r.year_to or r.year_from
        return lo is not None and hi is not None and lo - slack <= y <= hi + slack

    pick: UsedRange | None = None
    exact = False
    if year is not None:
        hit = [r for r in ranges if covers(r, year, 0)]
        near = [r for r in ranges if covers(r, year, 1)]
        if hit:
            pick, exact = min(hit, key=lambda r: r.max_eur - r.min_eur), True
        elif near:
            pick = near[0]
    if pick is None:
        loose = [r for r in ranges if r.year_from is None and r.year_to is None]
        pick = loose[0] if loose else None
    if pick is None or pick.max_eur <= 0:
        return None
    return UsedPrice(round((pick.min_eur + pick.max_eur) / 2), pick.year_from, pick.year_to, pick.url, exact)


@dataclass(frozen=True)
class Warranty:
    state: Literal["REMAINING", "EXPIRED", "UNKNOWN"]
    until: int | None = None  # the last year covered
    years: float | None = None
    assumed: bool = False  # the first year was assumed (FR-026)


def warranty_status(first_year: int | None, warranty_years: float | None, now_year: int, *,
                    assumed: bool = False) -> Warranty:  # fmt: skip
    """The maker's warranty from the first registration: remaining until a year, or expired in a year."""
    if first_year is None or not warranty_years:
        return Warranty("UNKNOWN", assumed=assumed)
    until = first_year + int(warranty_years)
    return Warranty("REMAINING" if until >= now_year else "EXPIRED", until, warranty_years, assumed)
